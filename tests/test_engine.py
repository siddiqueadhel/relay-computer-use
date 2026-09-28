"""Fast state-machine tests. These fakes are never used as discovery evidence."""

import pytest
from playwright.async_api import TimeoutError as BrowserTimeout

from relay.control import SessionControl
from relay.evidence import Journal, Redactor
from relay.replay import Replay
from relay.schema import (
    Action,
    Capability,
    Contract,
    FieldSpec,
    OutcomeRule,
    Output,
    Provenance,
    Step,
    target,
    visible,
)


class FakeSurface:
    def __init__(self, journal, control, *, destination="After", uncertain=False):
        self.journal, self.control = journal, control
        self.state, self.destination, self.uncertain = "Before", destination, uncertain
        self.actions = []

    async def check(self, conditions, inputs):
        return all(
            (c.target.candidates[0].name != self.state)
            if c.kind == "absent"
            else (c.target.candidates[0].name == self.state)
            for c in conditions
        )

    async def wait(self, conditions, inputs, timeout_ms):
        return await self.check(conditions, inputs)

    async def act(self, action, inputs, *, actor="automation"):
        self.control.require(actor)
        self.actions.append(action)
        if action.kind == "navigate":
            self.state = "Before"
            return
        self.state = self.destination
        if self.uncertain:
            raise BrowserTimeout("test-only uncertain action completion")

    async def observe(self):
        return {
            "frames": [
                {"frame_path": ["workspace"], "headings": [{"level": 1, "text": self.state}]}
            ]
        }

    async def read(self, target):
        return "verified"

    async def evidence(self, name):
        self.journal.save_json(name + ".json", {"test_fake": True, "state": self.state})
        return name + ".json"


def setup(tmp_path, *, destination="After", uncertain=False, rules=()):
    journal = Journal(tmp_path, Redactor(), mode="unit-test")
    control = SessionControl(journal)
    surface = FakeSurface(journal, control, destination=destination, uncertain=uncertain)
    capability = Capability(
        version="1.0.0",
        vendor="test",
        app_version="1",
        contract=Contract(
            name="test_flow",
            description="Test only",
            inputs={},
            outputs={
                "value": Output(
                    spec=FieldSpec(description="Test output", enum=["verified"]),
                    target=target("Output"),
                )
            },
            success=[visible("After")],
        ),
        steps=[
            Step(
                id="step",
                action=Action(kind="click", target=target("Go", "button")),
                before=[visible("Before")],
                after=[visible("After")],
                rationale="Test transition",
            )
        ],
        outcomes=list(rules),
        provenance=Provenance(kind="test_fixture", provider="none"),
    )
    return Replay(surface, control, journal, intervention_timeout=0.01), surface, capability


async def test_discovery_provider_failure_is_specific_and_does_not_emit_artifact(tmp_path):
    from relay.discovery import Discovery
    from relay.models import ModelError

    runner, surface, capability = setup(tmp_path)

    class UnavailableModel:
        name, provider, calls = "test", "test_only", 0

        async def decide(self, **request):
            self.calls += 1
            raise ModelError("model_rate_limited", status=429)

    discovery = Discovery(surface, UnavailableModel(), runner.control, runner.journal)
    result, artifact = await discovery.run("Prepare request", capability.contract, {}, [])
    assert result.code == "model_rate_limited"
    assert result.outputs == {} and artifact is None
    assert result.model_calls == 1
    assert any(e["event"] == "provider_error" for e in runner.journal.events)


async def test_uncertain_action_is_accepted_only_when_checkpoint_proves_completion(tmp_path):
    runner, surface, capability = setup(tmp_path, uncertain=True)
    result = await runner.run(capability, {})
    assert result.status == "success"
    assert result.outputs == {"value": "verified"}
    assert len(surface.actions) == 1
    assert result.model_calls == 0


async def test_uncertain_side_effect_is_never_blindly_retried(tmp_path):
    runner, surface, capability = setup(tmp_path, destination="Processing", uncertain=True)
    result = await runner.run(capability, {})
    assert result.code == "intervention_timeout"
    assert len(surface.actions) == 1


@pytest.mark.parametrize(
    "disposition,status", [("business", "business_outcome"), ("fail", "failure")]
)
async def test_known_outcome_is_distinct_from_transport_failure(tmp_path, disposition, status):
    rule = OutcomeRule(code="known_result", when=visible("Known result"), disposition=disposition)
    runner, surface, capability = setup(tmp_path, destination="Known result", rules=[rule])
    result = await runner.run(capability, {})
    assert result.status == status
    assert result.code == "known_result"
    assert result.observed == "Known result"


async def test_recovery_that_does_not_clear_its_condition_stops(tmp_path):
    rule = OutcomeRule(
        code="notice",
        when=visible("Notice"),
        disposition="recover",
        recovery=Action(kind="click", target=target("Dismiss", "button")),
        max_attempts=1,
    )
    runner, surface, capability = setup(tmp_path, destination="Notice", rules=[rule])
    result = await runner.run(capability, {})
    assert result.code == "recovery_did_not_clear_condition"
    assert len(surface.actions) == 2
    assert result.recoveries == 1


@pytest.mark.parametrize("at_handoff", [True, False])
async def test_replay_abort_during_evidence_wins_over_failure_or_success(tmp_path, at_handoff):
    runner, surface, capability = setup(
        tmp_path, destination="Processing" if at_handoff else "After", uncertain=at_handoff
    )
    save_evidence = surface.evidence

    async def abort_while_saving(name):
        if name.startswith("intervention" if at_handoff else "completed"):
            await runner.control.abort()
        return await save_evidence(name)

    surface.evidence = abort_while_saving
    result = await runner.run(capability, {})
    assert (result.status, result.code) == ("aborted", "operator_aborted")
    assert len(surface.actions) == 1
    assert result.outputs == {}
    assert runner.control.handoffs == 0


async def test_discovery_verifies_success_after_the_last_allowed_action(tmp_path):
    from relay.discovery import Discovery
    from relay.models import Decision

    runner, surface, capability = setup(tmp_path)

    class FixtureModel:
        test_only = True
        name, provider, calls = "fixture", "test_only", 0

        async def decide(self, **kwargs):
            self.calls += 1
            return Decision(
                intent="act",
                action=Action(kind="click", target=target("Go", "button")),
                rationale="Test transition",
            )

    model = FixtureModel()
    discovery = Discovery(surface, model, runner.control, runner.journal, max_steps=1)
    result, artifact = await discovery.run("Test", capability.contract, {}, [])
    assert result.status == "success"
    assert artifact.provenance.kind == "test_fixture"
    assert artifact.provenance.model_calls == 1
    assert len(artifact.steps) == 2
    import hashlib

    prefix = b"".join(
        runner.journal.path.read_bytes().splitlines(keepends=True)[
            : artifact.provenance.evidence_event_count
        ]
    )
    assert hashlib.sha256(prefix).hexdigest() == artifact.provenance.evidence_sha256


async def test_discovery_preserves_known_intervention_as_a_conditional_branch(tmp_path):
    import asyncio

    from relay.discovery import Discovery
    from relay.recorder import Recorder

    runner, surface, capability = setup(tmp_path)
    recorder = Recorder(capability.contract)
    before = await surface.observe()
    surface.state = "Session expired"
    recorder.add(
        Action(kind="click", target=target("Go", "button")),
        before,
        await surface.observe(),
        "Test action",
    )
    discovery = Discovery(surface, None, runner.control, runner.journal)
    task = asyncio.create_task(
        discovery.human("session_expired", recorder, visible("Session expired"))
    )
    for _ in range(100):
        if runner.control.owner == "paused":
            break
        await asyncio.sleep(0.001)
    await runner.control.claim(runner.control.generation)
    surface.state = "After"
    await runner.control.resume(runner.control.generation)
    await task
    assert len(recorder.steps) == 1
    assert recorder.steps[0].after[0].target.candidates[0].name == "After"
    assert recorder.steps[0].after[1].kind == "absent"


@pytest.mark.parametrize("raise_after_abort", [False, True])
async def test_discovery_abort_wins_over_a_late_model_response(tmp_path, raise_after_abort):
    from relay.discovery import Discovery
    from relay.models import Decision

    runner, surface, capability = setup(tmp_path)

    class AbortingModel:
        test_only = True
        name, provider, calls = "fixture", "test_only", 0

        async def decide(self, **kwargs):
            self.calls += 1
            await runner.control.abort()
            if raise_after_abort:
                raise ValueError("A late provider failure after cancellation")
            return Decision(
                intent="act",
                action=Action(kind="click", target=target("Go", "button")),
                rationale="A response that must not be executed after abort.",
            )

    result, artifact = await Discovery(
        surface, AbortingModel(), runner.control, runner.journal
    ).run("Test abort", capability.contract, {}, [])
    assert (result.status, result.code) == ("aborted", "operator_aborted")
    assert artifact is None
    assert [a.kind for a in surface.actions] == ["navigate"]
    assert not (runner.journal.directory / "capability.json").exists()


async def test_discovery_abort_cancels_an_inflight_model_request(tmp_path):
    import asyncio

    from relay.discovery import Discovery

    runner, surface, capability = setup(tmp_path)
    entered, cancelled = asyncio.Event(), asyncio.Event()

    class BlockingModel:
        test_only = True
        name, provider, calls = "fixture", "test_only", 0

        async def decide(self, **kwargs):
            self.calls += 1
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    task = asyncio.create_task(
        Discovery(surface, BlockingModel(), runner.control, runner.journal).run(
            "Test abort", capability.contract, {}, []
        )
    )
    await asyncio.wait_for(entered.wait(), 1)
    await runner.control.abort()
    result, artifact = await asyncio.wait_for(task, 1)
    assert (result.status, result.code) == ("aborted", "operator_aborted")
    assert cancelled.is_set()
    assert artifact is None
    assert [a.kind for a in surface.actions] == ["navigate"]


async def test_discovery_does_not_navigate_if_already_aborted(tmp_path):
    from relay.discovery import Discovery

    runner, surface, capability = setup(tmp_path)

    class UnusedModel:
        test_only = True
        name, provider, calls = "fixture", "test_only", 0

        async def decide(self, **kwargs):
            raise AssertionError("An aborted run must not call the model")

    await runner.control.abort()
    result, artifact = await Discovery(surface, UnusedModel(), runner.control, runner.journal).run(
        "Test abort", capability.contract, {}, []
    )
    assert (result.status, result.code) == ("aborted", "operator_aborted")
    assert artifact is None
    assert surface.actions == []
