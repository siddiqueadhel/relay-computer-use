import asyncio
import sys

import httpx
import pytest

from relay.cli import simulate_operator
from relay.control import OwnershipError
from relay.operator import create_console
from relay.schema import Action, Step, target, visible

pytestmark = pytest.mark.browser
INPUTS = dict(member_id="67890", account_type="savings", nickname="NeverLogName")


@pytest.mark.parametrize(
    "scenario,changes,status,code",
    [
        ("normal", {}, "success", "completed"),
        ("normal", {"member_id": "99999"}, "business_outcome", "member_not_found"),
        ("normal", {"nickname": "BLOCKED"}, "business_outcome", "validation_error"),
        ("slow", {}, "success", "completed"),
        ("permission_denied", {}, "failure", "permission_denied"),
        ("known_dialog", {}, "success", "completed"),
        ("app_error", {}, "failure", "app_unavailable"),
        ("ambiguous", {}, "failure", "ambiguous_target"),
        ("redirect_escape", {}, "failure", "origin_denied"),
    ],
)
async def test_real_ui_outcomes(manager, bank, scenario, changes, status, code):
    result = await manager.start({**INPUTS, **changes}, scenario=scenario)
    assert (result.status, result.code) == (status, code)
    assert result.model_calls == 0
    assert "openai" not in sys.modules
    assert sum(s.commits for s in bank[0].state.sessions.values()) == 0
    assert result.evidence
    if status == "success":
        assert result.outputs["member_id"] == INPUTS["member_id"]
        assert result.outputs["nickname"] == INPUTS["nickname"]
    for path in manager.current.journal.directory.glob("*.json*"):
        raw = path.read_text()
        assert "NeverLogName" not in raw
        assert INPUTS["member_id"] not in raw
    if scenario == "known_dialog":
        assert result.recoveries == 1


@pytest.mark.parametrize("scenario", ["session_expired", "unknown_dialog"])
async def test_same_session_handoff_and_resume(manager, bank, scenario):
    task = manager.start(INPUTS, scenario=scenario)
    original_session = manager.current.control.session_id
    operator = asyncio.create_task(simulate_operator(manager))
    result = await task
    await operator
    assert result.status == "success"
    assert result.handoffs == 1
    events = manager.current.journal.events
    assert [e["owner"] for e in events if e["event"] == "control_transferred"] == [
        "human",
        "automation",
    ]
    assert all(e.get("session_id", original_session) == original_session for e in events)
    assert any(e["event"] == "human_action" for e in events)
    assert any(e["event"] == "resume_verified" for e in events)
    assert len(bank[0].state.sessions) == 1


async def test_identical_artifact_replays_harbor_markup_variant(manager, bank):
    digest = manager.capability.digest()
    result = await manager.start(INPUTS, variant="harbor")
    assert (result.status, result.code) == ("success", "completed")
    assert result.outputs["member_id"] == INPUTS["member_id"]
    assert manager.capability.digest() == digest
    assert result.model_calls == 0
    assert sum(s.commits for s in bank[0].state.sessions.values()) == 0


async def wait_for_pause(manager):
    async def wait_until(ready, timeout):
        async with asyncio.timeout(timeout):
            while not ready():
                if manager.task.done():
                    pytest.fail(f"Run ended before handoff: {manager.current.result}")
                await asyncio.sleep(0.025)

    # The runner's workflow deadline begins after browser startup. Match that
    # separation here: a slow CDP connection must not consume the UI budget.
    try:
        await wait_until(lambda: manager.current.surface is not None, 60)
    except TimeoutError:
        pytest.fail("Browser did not become ready within 60 seconds")
    try:
        await wait_until(
            lambda: manager.current.control.owner == "paused", manager.total_timeout + 1
        )
    except TimeoutError:
        pytest.fail("No intervention requested within the workflow deadline")


async def test_operator_console_ownership_and_csrf(manager):
    manager.intervention_timeout = 5
    task = manager.start(INPUTS, scenario="session_expired")
    await wait_for_pause(manager)
    app = create_console(manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8766"
    ) as client:
        generation = manager.current.control.generation
        session_id = manager.current.control.session_id
        request = {"generation": generation, "session_id": session_id}
        assert (await client.post("/api/control/claim", json=request)).status_code == 403
        client.headers["X-Relay-Token"] = app.state.control_token
        assert (
            await client.post("/api/control/claim", json={**request, "session_id": "stale"})
        ).status_code == 409
        assert (await client.post("/api/control/claim", json=request)).status_code == 200
        with pytest.raises(OwnershipError):
            await manager.current.surface.act(Action(kind="navigate", path="/"), {})
        observation = (await client.get("/api/observation")).json()
        control = next(
            c
            for f in observation["frames"]
            for c in f["controls"]
            if c["name"] == "Resume staff session"
        )
        response = await client.post(
            "/api/action",
            json={**request, "action": {"kind": "click", "target": control["target"]}},
        )
        assert response.status_code == 200
        assert (
            await client.post("/api/control/resume", json={**request, "generation": generation - 1})
        ).status_code == 409
        assert (await client.post("/api/control/resume", json=request)).status_code == 200
    assert (await task).status == "success"


async def test_resume_wrong_screen_stops_before_more_actions(manager):
    manager.intervention_timeout = 5
    task = manager.start(INPUTS, scenario="session_expired")
    await wait_for_pause(manager)
    current = manager.current
    await current.control.claim(current.control.generation)
    await current.surface.act(Action(kind="navigate", path="/workspace"), {}, actor="human")
    await current.control.resume(current.control.generation)
    assert (await task).code == "resume_checkpoint_mismatch"


async def test_irreversible_step_is_blocked_even_in_valid_artifact(manager, bank):
    manager.capability.steps.append(
        Step(
            id="forbidden_commit",
            action=Action(kind="click", target=target("Create account", "button")),
            before=[visible("Review request")],
            after=[visible("Account created")],
            rationale="An untrusted artifact claims this is safe.",
        )
    )
    result = await manager.start(INPUTS)
    assert result.code == "control_denied"
    assert sum(s.commits for s in bank[0].state.sessions.values()) == 0


async def test_output_verification_rejects_wrong_member_binding(manager):
    manager.capability.contract.outputs["member_id"].equals_input = "nickname"
    result = await manager.start(INPUTS)
    assert result.code == "output_input_mismatch"


async def test_handoff_timeout_is_bounded(manager):
    manager.intervention_timeout = 0.2
    result = await manager.start(INPUTS, scenario="session_expired")
    assert result.code == "intervention_timeout"
    assert result.elapsed_ms < 10000


async def test_load_timeout_does_not_repeat_uncertain_submit(manager, bank):
    manager.intervention_timeout = 0.2
    manager.capability.steps[2].timeout_ms = 250
    result = await manager.start(INPUTS, scenario="timeout")
    assert result.code == "intervention_timeout"
    submits = [
        e
        for e in manager.current.journal.events
        if e["event"] == "step_started" and e["step_id"] == "step_02"
    ]
    assert len(submits) == 1
