"""Minimal real operator console: one session, explicit ownership, same live browser."""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from relay.bank import SCENARIOS
from relay.control import OwnershipError
from relay.policy import PolicyViolation
from relay.runtime import RunManager
from relay.schema import Action
from relay.surface import SurfaceError


def create_console(manager: RunManager) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    token = secrets.token_urlsafe(32)
    app.state.control_token = token

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost"}:
            return Response(status_code=403)
        if request.method == "POST" and not secrets.compare_digest(
            request.headers.get("x-relay-token", ""), token
        ):
            return Response(status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; frame-ancestors 'none'"
        )
        return response

    @app.get("/")
    async def index():
        return HTMLResponse(
            Path(__file__).with_name("console.html").read_text().replace("CONTROL_TOKEN", token)
        )

    @app.get("/api/state")
    async def state():
        current = manager.current
        return {
            "capability": manager.capability.model_dump(),
            "active": bool(manager.task and not manager.task.done()),
            "run": None
            if not current
            else {
                "id": current.journal.run_id,
                "mode": current.mode,
                "scenario": current.scenario,
                "control": current.control.status(),
                "events": current.journal.events[-100:],
                "result": current.journal.redactor.clean(current.result.model_dump())
                if current.result
                else None,
            },
        }

    @app.post("/api/run")
    async def run(request: Request):
        data = await request.json()
        if data.get("scenario", "normal") not in SCENARIOS:
            raise HTTPException(422, "Unknown scenario")
        if data.get("mode", "replay") not in {"replay", "discover"}:
            raise HTTPException(422, "Unknown mode")
        if data.get("mode") == "discover":
            # Resolve the same server-side provider and key requirements as the CLI.
            # Keep the import lazy: replay must remain usable without a model client.
            from relay.models import validate_console_discovery_configuration

            try:
                validate_console_discovery_configuration()
            except ValueError as exc:
                # These configuration errors contain fixed labels, never key values.
                raise HTTPException(
                    422,
                    f"{exc}. Replay is available without model credentials.",
                ) from None
        try:
            manager.start(
                data.get("inputs", {}),
                mode=data.get("mode", "replay"),
                scenario=data.get("scenario", "normal"),
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return {"run_id": manager.current.journal.run_id}

    @app.get("/api/observation")
    async def observation():
        current = manager.current
        if not current or not current.surface or current.control.owner != "human":
            raise HTTPException(409, "Take control of a paused live session first")
        return await current.surface.observe()

    @app.post("/api/control/{command}")
    async def control(command: str, request: Request):
        current = manager.current
        if not current:
            raise HTTPException(409, "No run")
        data = await request.json()
        if data.get("session_id") != current.control.session_id:
            raise HTTPException(409, "Stale session")
        try:
            if command == "claim":
                await current.control.claim(data.get("generation", -1))
            elif command == "resume":
                await current.control.resume(data.get("generation", -1))
            elif command == "abort":
                await current.control.abort(data.get("generation", -1))
            else:
                raise HTTPException(404, "Unknown command")
        except OwnershipError as exc:
            raise HTTPException(409, str(exc)) from None
        return current.control.status()

    @app.post("/api/action")
    async def action(request: Request):
        current = manager.current
        if not current or not current.surface:
            raise HTTPException(409, "No live browser")
        data = await request.json()
        if data.get("session_id") != current.control.session_id:
            raise HTTPException(409, "Stale session")
        try:
            parsed = Action.model_validate(data.get("action", {}))
            await current.surface.act(
                parsed, {}, actor="human", expected_generation=data.get("generation", -1)
            )
            current.journal.emit(
                "operator_console_action",
                kind=parsed.kind,
                target=parsed.target.model_dump() if parsed.target else None,
                values="not recorded",
            )
        except (ValueError, OwnershipError, PolicyViolation, SurfaceError):
            raise HTTPException(
                409, "Action rejected by policy, target resolution, or session ownership"
            ) from None
        return {"ok": True}

    @app.get("/api/screen")
    async def screen():
        current = manager.current
        if not current:
            raise HTTPException(404, "No screen yet")
        if current.surface and current.control.owner in {"paused", "human"}:
            surface = current.surface
            surface._check_destinations()
            masks = [
                frame.locator(selector)
                for frame in surface.page.frames
                for selector in surface.policy.private_selectors
            ]
            masks.extend(
                frame.get_by_text(value, exact=False)
                for frame in surface.page.frames
                for value in current.journal.redactor.private_values
            )
            image = await surface.page.screenshot(mask=masks, mask_color="#16362e")
            return Response(image, media_type="image/png")
        images = sorted(current.journal.directory.glob("*.png"), key=lambda p: p.stat().st_mtime)
        if images:
            return Response(images[-1].read_bytes(), media_type="image/png")
        raise HTTPException(404, "Screen available at a checkpoint or intervention")

    return app
