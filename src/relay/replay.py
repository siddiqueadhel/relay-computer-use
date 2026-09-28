"""The production execution path. This module never imports a model client."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from playwright.async_api import Error as BrowserError
from playwright.async_api import TimeoutError as BrowserTimeout

from relay.control import OwnershipError, SessionControl
from relay.evidence import Journal
from relay.policy import PolicyViolation
from relay.schema import Capability, Contract, OutcomeRule, RunResult, Step
from relay.surface import Surface, SurfaceError


class StopRun(Exception):
    def __init__(self, code: str, status: str = "failure"):
        self.code, self.status = code, status
        super().__init__(code)


async def verify_outputs(surface: Surface, contract: Contract, inputs: dict) -> dict:
    if not await surface.check(contract.success, inputs):
        raise StopRun("success_checkpoint_failed")
    outputs = {}
    for name, output in contract.outputs.items():
        raw = await surface.read(output.target)
        try:
            value = {
                "integer": int,
                "number": float,
                "boolean": lambda x: {"true": True, "false": False}[x],
            }.get(output.spec.type, str)(raw)
        except (ValueError, KeyError):
            raise StopRun("output_type_mismatch") from None
        if not output.spec.accepts(value):
            raise StopRun("output_contract_mismatch")
        if output.equals_input and value != inputs[output.equals_input]:
            raise StopRun("output_input_mismatch")
        outputs[name] = value
        if output.spec.sensitive:
            surface.journal.redactor.add_private(value)
    return outputs


class Replay:
    def __init__(
        self,
        surface: Surface,
        control: SessionControl,
        journal: Journal,
        *,
        intervention_timeout: float = 180,
        total_timeout: float = 300,
    ):
        self.surface, self.control, self.journal = surface, control, journal
        self.intervention_timeout, self.total_timeout = intervention_timeout, total_timeout
        self.recovery_counts: dict[str, int] = {}
        self.step: Step | None = None
        self.inputs: dict[str, Any] = {}
        self.rules: list[OutcomeRule] = []
        self.last_evidence = None

    async def handoff(self, reason: str, step: Step, *, require_after: bool = False) -> str:
        if self.control.handoffs >= 3:
            raise StopRun("handoff_limit")
        self.last_evidence = await self.surface.evidence(
            f"intervention-{self.control.generation + 1}"
        )
        await self.control.pause(
            reason=reason,
            step_id=step.id,
            expected="Restore the interrupted step's before or after checkpoint.",
            evidence=self.last_evidence,
        )
        try:
            await asyncio.wait_for(self.control.resumed.wait(), self.intervention_timeout)
        except TimeoutError:
            raise StopRun("intervention_timeout") from None
        if self.control.aborted:
            raise StopRun("operator_aborted", "aborted")
        self.control.require("automation")
        await self.surface.evidence(f"resumed-{self.control.generation}")
        # Prioritize the postcondition: the operator may already have completed the interrupted step.
        if await self.surface.check(step.after, self.inputs):
            self.journal.emit("resume_verified", step_id=step.id, checkpoint="after")
            return "after"
        if not require_after and step.before and await self.surface.check(step.before, self.inputs):
            self.journal.emit("resume_verified", step_id=step.id, checkpoint="before")
            return "before"
        raise StopRun("resume_checkpoint_mismatch")

    async def handle_outcomes(self, step: Step) -> str | None:
        for rule in self.rules:
            if not await self.surface.check([rule.when], self.inputs):
                continue
            self.journal.emit(
                "condition_detected", step_id=step.id, code=rule.code, disposition=rule.disposition
            )
            if rule.disposition == "business":
                raise StopRun(rule.code, "business_outcome")
            if rule.disposition == "fail":
                raise StopRun(rule.code)
            if rule.disposition == "intervene":
                return await self.handoff(rule.code, step)
            count = self.recovery_counts.get(rule.code, 0)
            if count >= rule.max_attempts:
                raise StopRun("recovery_exhausted")
            self.recovery_counts[rule.code] = count + 1
            await self.surface.act(rule.recovery, self.inputs)
            self.journal.emit("recovery_applied", code=rule.code, attempt=count + 1)
            if await self.surface.check([rule.when], self.inputs):
                raise StopRun("recovery_did_not_clear_condition")
        return None

    async def execute_step(self, step: Step) -> None:
        self.step = step
        self.surface.default_timeout_ms = step.timeout_ms
        self.journal.emit(
            "step_started",
            step_id=step.id,
            action=step.action.model_dump(),
            rationale=step.rationale,
        )
        if step.action.kind == "human":
            await self.handoff("recorded_human_gate", step, require_after=True)
            self.journal.emit("step_completed", step_id=step.id, by="operator")
            return
        resumed_at = await self.handle_outcomes(step)
        if resumed_at == "after":
            self.journal.emit("step_completed", step_id=step.id, by="operator")
            return
        if step.before and not await self.surface.wait(step.before, self.inputs, step.timeout_ms):
            resumed_at = await self.handle_outcomes(step) or await self.handoff(
                "precondition_failed", step
            )
            if resumed_at == "after":
                self.journal.emit("step_completed", step_id=step.id, by="operator")
                return
        action_error = None
        try:
            await self.surface.act(step.action, self.inputs)
        except (BrowserTimeout, SurfaceError) as exc:
            action_error = exc
            self.journal.emit(
                "action_incomplete", step_id=step.id, code=getattr(exc, "code", "action_timeout")
            )
            # An ambiguous locator is never resolved by selecting the first match.
            if isinstance(exc, SurfaceError) and exc.code.startswith("ambiguous"):
                raise StopRun(exc.code) from None
        resumed_at = await self.handle_outcomes(step)
        if resumed_at == "before":
            # No automatic action retry after a side effect with an uncertain outcome.
            raise StopRun("manual_step_completion_required")
        if not await self.surface.wait(step.after, self.inputs, step.timeout_ms):
            await self.handle_outcomes(step)
            if not await self.surface.check(step.after, self.inputs):
                location = await self.handoff(
                    "action_timeout" if action_error else "postcondition_failed", step
                )
                if location != "after":
                    raise StopRun("manual_step_completion_required")
        self.journal.emit(
            "step_completed", step_id=step.id, by="automation" if not resumed_at else "operator"
        )

    async def run(self, capability: Capability, inputs: dict[str, Any]) -> RunResult:
        started = time.monotonic()
        self.inputs, self.rules = inputs, capability.outcomes
        status, code, outputs = "success", "completed", {}
        self.journal.emit(
            "capability_loaded",
            name=capability.contract.name,
            version=capability.version,
            sha256=capability.digest(),
            schema_version=capability.schema_version,
            input_fields=sorted(inputs),
            model_calls=0,
        )
        try:
            capability.contract.validate_inputs(inputs)
            async with asyncio.timeout(self.total_timeout):
                for step in capability.steps:
                    if self.control.aborted:
                        raise StopRun("operator_aborted", "aborted")
                    await self.execute_step(step)
                await self.handle_outcomes(capability.steps[-1])
                outputs = await verify_outputs(self.surface, capability.contract, inputs)
                self.last_evidence = await self.surface.evidence("completed")
        except StopRun as exc:
            status, code = exc.status, exc.code
        except ValueError:
            status, code = "failure", "invalid_inputs"
        except PolicyViolation as exc:
            status, code = "failure", exc.code
        except SurfaceError as exc:
            status, code = "failure", exc.code
        except OwnershipError:
            status, code = "failure", "ownership_violation"
        except TimeoutError:
            status, code = "failure", "run_timeout"
        except BrowserError:
            status, code = "failure", getattr(self.surface, "blocked", None) or "browser_error"
        # An operator abort can race an awaited browser/evidence operation,
        # including the final checkpoint or preparation of a handoff.
        if self.control.aborted:
            status, code = "aborted", "operator_aborted"
        if status != "success":
            outputs = {}
            self.last_evidence = await self.surface.evidence("stopped")
        observed = None
        if status != "success":
            try:
                state = await self.surface.observe()
                observed = "; ".join(h["text"] for f in state["frames"] for h in f["headings"])
            except Exception:
                observed = "Observation restricted by policy or browser state"
        self.control.owner = "finished"
        result = RunResult(
            run_id=self.journal.run_id,
            status=status,
            code=code,
            outputs=outputs,
            step_id=self.step.id if self.step else None,
            expected=json.dumps([c.model_dump() for c in self.step.after])
            if status != "success" and self.step
            else None,
            observed=observed,
            evidence=self.last_evidence,
            model_calls=0,
            recoveries=sum(self.recovery_counts.values()),
            handoffs=self.control.handoffs,
            elapsed_ms=round((time.monotonic() - started) * 1000),
        )
        self.journal.emit("run_finished", **result.model_dump(exclude={"run_id"}))
        self.journal.save_json("result.json", result.model_dump())
        return result
