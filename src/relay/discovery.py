"""A bounded live observe -> decide -> act loop, with checked artifact compilation."""

from __future__ import annotations

import asyncio
import json
import time
import traceback
from pathlib import Path

from relay.control import OwnershipError, SessionControl
from relay.evidence import Journal
from relay.models import Decision, Model, ModelError
from relay.policy import PolicyViolation
from relay.recorder import Recorder, heading_checkpoint
from relay.replay import StopRun, verify_outputs
from relay.schema import Action, Capability, Condition, Contract, OutcomeRule, Provenance, RunResult
from relay.surface import Surface, SurfaceError


class Discovery:
    def __init__(
        self,
        surface: Surface,
        model: Model,
        control: SessionControl,
        journal: Journal,
        *,
        max_steps: int = 25,
        total_timeout: float = 300,
        intervention_timeout: float = 180,
    ):
        self.surface, self.model, self.control, self.journal = surface, model, control, journal
        self.max_steps, self.total_timeout = max_steps, total_timeout
        self.intervention_timeout = intervention_timeout
        self.history: list[dict] = []
        self.recoveries: dict[str, int] = {}

    def check_aborted(self) -> None:
        if self.control.aborted:
            raise StopRun("operator_aborted", "aborted")

    async def decide(self, goal: str, contract: Contract, observation: dict) -> Decision:
        """Abort promptly even while a provider request is pending; ignore late decisions."""
        self.check_aborted()
        decision_task = asyncio.create_task(
            self.model.decide(
                goal=self.journal.redactor.text(goal),
                contract=contract,
                observation=observation,
                history=self.history,
            )
        )
        abort_task = asyncio.create_task(self.control.abort_requested.wait())
        try:
            await asyncio.wait({decision_task, abort_task}, return_when=asyncio.FIRST_COMPLETED)
            # Cancellation wins when the request and the abort arrive together.
            self.check_aborted()
            return await decision_task
        finally:
            for task in (decision_task, abort_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(decision_task, abort_task, return_exceptions=True)

    async def observation(self) -> dict:
        for _ in range(100):
            self.check_aborted()
            state = await self.surface.observe()
            try:
                heading_checkpoint(state)
                return state
            except ValueError:
                await asyncio.sleep(0.05)
        raise StopRun("unobservable_surface")

    async def human(
        self, reason: str, recorder: Recorder, blocked: Condition | None = None
    ) -> None:
        if self.control.handoffs >= 3:
            raise StopRun("handoff_limit")
        before = await self.observation()
        evidence = await self.surface.evidence(f"intervention-{self.control.generation + 1}")
        await self.control.pause(
            reason=reason,
            step_id=f"discovery_{len(recorder.steps)}",
            expected="Resolve the blocker in this live session, then return control.",
            evidence=evidence,
        )
        try:
            await asyncio.wait_for(self.control.resumed.wait(), self.intervention_timeout)
        except TimeoutError:
            raise StopRun("intervention_timeout") from None
        if self.control.aborted:
            raise StopRun("operator_aborted", "aborted")
        after = await self.observation()
        if blocked:
            absent = blocked.model_copy(update={"kind": "absent", "expected": None})
            if not await self.surface.check([absent], {}):
                raise StopRun("operator_did_not_clear_blocker")
            # This conditional intervention is already represented by the outcome rule.
            recorder.steps[-1].after = [heading_checkpoint(after), absent]
            self.journal.emit(
                "conditional_handoff_recorded", step_id=recorder.steps[-1].id, code=reason
            )
        else:
            recorder.add(
                Action(kind="human"),
                before,
                after,
                "Explicit operator intervention; preserved as a mandatory human gate on replay.",
            )
            self.journal.emit("discovery_human_gate_recorded", step_id=recorder.steps[-1].id)

    async def conditions(self, rules: list[OutcomeRule], recorder: Recorder) -> None:
        for rule in rules:
            if not await self.surface.check([rule.when], {}):
                continue
            self.journal.emit("condition_detected", code=rule.code, disposition=rule.disposition)
            if rule.disposition in {"business", "fail"}:
                raise StopRun(
                    rule.code, "business_outcome" if rule.disposition == "business" else "failure"
                )
            if rule.disposition == "intervene":
                await self.human(rule.code, recorder, rule.when)
            else:
                count = self.recoveries.get(rule.code, 0)
                if count >= rule.max_attempts:
                    raise StopRun("recovery_exhausted")
                self.recoveries[rule.code] = count + 1
                await self.surface.act(rule.recovery, {})
                self.journal.emit("recovery_applied", code=rule.code, attempt=count + 1)

    async def run(
        self, goal: str, contract: Contract, inputs: dict, rules: list[OutcomeRule]
    ) -> tuple[RunResult, Capability | None]:
        started = time.monotonic()
        recorder = Recorder(contract)
        artifact = None
        status, code, outputs = "success", "completed", {}
        last_signature, repeats = None, 0
        self.journal.emit(
            "discovery_started",
            goal=self.journal.redactor.text(goal),
            provider=self.model.provider,
            model=self.model.name,
            max_steps=self.max_steps,
        )
        try:
            contract.validate_inputs(inputs)
            async with asyncio.timeout(self.total_timeout):
                self.check_aborted()
                entry = Action(kind="navigate", path="/")
                await self.surface.act(entry, inputs)
                recorder.add(
                    entry,
                    None,
                    await self.observation(),
                    "Open the configured application entry point.",
                )
                for iteration in range(self.max_steps + 1):
                    self.check_aborted()
                    await self.conditions(rules, recorder)
                    self.check_aborted()
                    if await self.surface.check(contract.success, inputs):
                        outputs = await verify_outputs(self.surface, contract, inputs)
                        self.check_aborted()
                        if self.model.calls == 0:
                            raise StopRun("discovery_requires_model_actions")
                        provenance = Provenance(
                            kind="test_fixture"
                            if getattr(self.model, "test_only", False)
                            else "llm_discovery",
                            provider=self.model.provider,
                            model=self.model.name,
                            run_id=self.journal.run_id,
                            model_calls=self.model.calls,
                            evidence_sha256=self.journal.digest(),
                            evidence_event_count=len(self.journal.events),
                        )
                        artifact = recorder.finish(rules, provenance)
                        # Refuse literal private values anywhere in the serialized artifact.
                        serialized = artifact.model_dump_json()
                        if self.journal.redactor.text(serialized) != serialized:
                            raise StopRun("artifact_contains_private_values")
                        self.journal.save_json("capability.json", artifact.model_dump())
                        self.journal.emit(
                            "capability_recorded",
                            sha256=artifact.digest(),
                            steps=len(artifact.steps),
                        )
                        break
                    if iteration == self.max_steps:
                        raise StopRun("max_steps_reached")
                    before = await self.observation()
                    self.journal.emit("observation", state=before)
                    decision = await self.decide(goal, contract, before)
                    self.check_aborted()
                    record = self.journal.redactor.clean(decision.model_dump())
                    self.history.append(record)
                    self.journal.emit("model_decision", turn=self.model.calls, decision=record)
                    if getattr(self.model, "receipts", None):
                        self.journal.emit("model_receipt", **self.model.receipts[-1])
                    if decision.intent == "intervene":
                        await self.human("model_requested_intervention", recorder)
                        continue
                    if decision.intent == "finish":
                        raise StopRun("premature_model_completion")
                    action = decision.action
                    if not action or action.kind == "human":
                        raise StopRun("invalid_model_action")
                    if action.value and (
                        action.value.source != "input" or action.value.value not in contract.inputs
                    ):
                        raise StopRun("unbound_model_input")
                    signature = json.dumps([record.get("action"), before], sort_keys=True)
                    repeats = repeats + 1 if signature == last_signature else 0
                    last_signature = signature
                    if repeats >= 2:
                        await self.human("discovery_no_progress", recorder)
                        repeats = 0
                        continue
                    await self.surface.act(action, inputs)
                    after = await self.observation()
                    # Record the observed action first; error handling remains explicit in the artifact.
                    recorder.add(
                        action, before, after, self.journal.redactor.text(decision.rationale)
                    )
                    self.journal.emit("step_recorded", step=recorder.steps[-1].model_dump())
                else:
                    raise StopRun("max_steps_reached")
        except ModelError as exc:
            status, code = "failure", exc.code
            self.journal.emit("provider_error", **exc.details)
        except StopRun as exc:
            status, code = exc.status, exc.code
        except PolicyViolation as exc:
            status, code = "failure", exc.code
        except SurfaceError as exc:
            status, code = "failure", exc.code
        except OwnershipError:
            status, code = (
                ("aborted", "operator_aborted")
                if self.control.aborted
                else ("failure", "ownership_violation")
            )
        except TimeoutError:
            status, code = "failure", "discovery_timeout"
        except Exception as exc:
            status, code = "failure", "discovery_error"
            self.journal.emit(
                "discovery_error",
                exception_type=type(exc).__name__,
                frames=[
                    {"file": Path(f.filename).name, "function": f.name, "line": f.lineno}
                    for f in traceback.extract_tb(exc.__traceback__)[-8:]
                ],
            )
        if status != "success":
            artifact = None
            outputs = {}
        evidence = await self.surface.evidence("completed" if status == "success" else "stopped")
        self.control.owner = "finished"
        result = RunResult(
            run_id=self.journal.run_id,
            status=status,
            code=code,
            outputs=outputs,
            evidence=evidence,
            model_calls=self.model.calls,
            handoffs=self.control.handoffs,
            recoveries=sum(self.recoveries.values()),
            elapsed_ms=round((time.monotonic() - started) * 1000),
        )
        self.journal.emit("run_finished", **result.model_dump(exclude={"run_id"}))
        self.journal.save_json("result.json", result.model_dump())
        return result, artifact
