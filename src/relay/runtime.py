"""Application lifecycle and run orchestration; one isolated browser context per invocation."""

from __future__ import annotations

import asyncio
import time
import traceback
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import uvicorn

from relay.control import SessionControl
from relay.evidence import Journal, Redactor
from relay.policy import Policy
from relay.profile import contract, outcomes
from relay.replay import Replay
from relay.schema import Capability, RunResult
from relay.surface import BrowserSurface


class EmbeddedServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # asyncio.run owns the process signal lifecycle. Two embedded servers must
        # not replace each other's handlers or re-raise the same Ctrl-C twice.
        yield


@asynccontextmanager
async def serve(app, port: int, host: str = "127.0.0.1"):
    server = EmbeddedServer(
        uvicorn.Config(app, host=host, port=port, log_level="error", access_log=False)
    )
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if task.done():
                await task
                raise RuntimeError("server exited during startup")
            if server.started:
                break
            await asyncio.sleep(0.025)
        else:
            raise RuntimeError("server startup timeout")
        yield server
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=3)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@dataclass
class CurrentRun:
    journal: Journal
    control: SessionControl
    mode: str
    scenario: str
    surface: BrowserSurface | None = None
    result: RunResult | None = None
    artifact: Capability | None = None


class RunManager:
    def __init__(
        self,
        *,
        target_url: str,
        evidence_root: Path,
        capability: Capability,
        headless: bool = True,
        policy: Policy | None = None,
        intervention_timeout: float = 180,
        total_timeout: float = 300,
    ):
        self.target_url, self.evidence_root, self.capability = target_url, evidence_root, capability
        self.headless, self.policy = headless, policy or Policy()
        self.intervention_timeout, self.total_timeout = intervention_timeout, total_timeout
        self.current: CurrentRun | None = None
        self.task: asyncio.Task | None = None

    def start(
        self,
        inputs: dict,
        *,
        mode: str = "replay",
        scenario: str = "normal",
        variant: str = "base",
        goal: str = "Prepare a new sub-account for the supplied member, using the supplied account type and nickname. Stop at the review screen.",
        model=None,
    ) -> asyncio.Task:
        if self.task and not self.task.done():
            raise ValueError("a run is already active")
        active_contract = self.capability.contract if mode == "replay" else contract()
        active_contract.validate_inputs(inputs)
        redactor = Redactor(
            [str(inputs[n]) for n, spec in active_contract.inputs.items() if spec.sensitive]
        )
        journal = Journal(self.evidence_root, redactor, mode=mode)
        current = CurrentRun(
            journal=journal, control=SessionControl(journal), mode=mode, scenario=scenario
        )
        self.current = current
        entry = urlsplit(self.target_url)
        query = [
            (key, value)
            for key, value in parse_qsl(entry.query, keep_blank_values=True)
            if key not in {"scenario", "variant"}
        ]
        query.extend([("scenario", scenario), ("variant", variant)])
        url = urlunsplit(
            (entry.scheme, entry.netloc, entry.path or "/", urlencode(query), entry.fragment)
        )
        self.task = asyncio.create_task(self._execute(current, url, inputs, goal, model))
        return self.task

    async def _execute(
        self, current: CurrentRun, url: str, inputs: dict, goal: str, model
    ) -> RunResult:
        try:
            async with BrowserSurface(
                url, self.policy, current.control, current.journal, headless=self.headless
            ) as surface:
                current.surface = surface
                if current.mode == "replay":
                    runner = Replay(
                        surface,
                        current.control,
                        current.journal,
                        intervention_timeout=self.intervention_timeout,
                        total_timeout=self.total_timeout,
                    )
                    current.result = await runner.run(self.capability, inputs)
                else:
                    from relay.discovery import Discovery
                    from relay.models import create_model

                    active_model = model or create_model()
                    runner = Discovery(
                        surface,
                        active_model,
                        current.control,
                        current.journal,
                        total_timeout=self.total_timeout,
                        intervention_timeout=self.intervention_timeout,
                    )
                    try:
                        current.result, current.artifact = await runner.run(
                            goal, contract(), inputs, outcomes()
                        )
                    finally:
                        if hasattr(active_model, "close"):
                            await active_model.close()
                    if current.artifact:
                        self.capability = current.artifact
        except Exception as exc:
            diagnostics = {
                "exception_type": type(exc).__name__,
                "frames": [
                    {"file": Path(f.filename).name, "function": f.name, "line": f.lineno}
                    for f in traceback.extract_tb(exc.__traceback__)[-8:]
                ],
            }
            current.result = RunResult(
                run_id=current.journal.run_id,
                status="failure",
                code="browser_start_failed" if current.surface is None else "runtime_error",
                evidence="runtime-error.json",
                elapsed_ms=round((time.monotonic() - current.journal.started) * 1000),
            )
            current.journal.emit("runtime_error", **diagnostics)
            current.journal.save_json("runtime-error.json", diagnostics)
            current.journal.save_json("result.json", current.result.model_dump())
            current.journal.emit("run_finished", **current.result.model_dump(exclude={"run_id"}))
            current.control.owner = "finished"
        finally:
            current.surface = None
        return current.result

    async def close(self):
        if self.task and not self.task.done():
            await self.current.control.abort()
            try:
                await asyncio.wait_for(self.task, 3)
            except TimeoutError:
                self.task.cancel()
