"""Compile successful observed UI actions into a parameterized capability."""

from __future__ import annotations

from relay.schema import (
    Action,
    Capability,
    Condition,
    Contract,
    Locator,
    OutcomeRule,
    Provenance,
    Step,
    Target,
)


def heading_checkpoint(observation: dict) -> Condition:
    for frame in reversed(observation["frames"]):
        headings = [h for h in frame["headings"] if h["level"] == 1]
        if len(headings) == 1:
            return Condition(
                kind="visible",
                target=Target(
                    frame_path=frame["frame_path"],
                    candidates=[Locator(by="role", role="heading", name=headings[0]["text"])],
                ),
            )
    raise ValueError("a unique primary heading is required for this browser recorder")


class Recorder:
    def __init__(self, contract: Contract):
        self.contract = contract
        self.steps: list[Step] = []

    def add(self, action: Action, before: dict | None, after: dict, rationale: str) -> None:
        if action.kind in {"fill", "select"}:
            if action.value.source != "input" or action.value.value not in self.contract.inputs:
                raise ValueError("recorded data entry must reference a declared input")
            checkpoint = Condition(kind="value_equals", target=action.target, expected=action.value)
        else:
            checkpoint = heading_checkpoint(after)
        self.steps.append(
            Step(
                id=f"step_{len(self.steps):02d}",
                action=action,
                before=[heading_checkpoint(before)] if before else [],
                after=[checkpoint],
                rationale=rationale[:400],
            )
        )

    def finish(self, rules: list[OutcomeRule], provenance: Provenance) -> Capability:
        return Capability(
            version="1.0.0",
            vendor="northstar-core",
            app_version="1.x",
            contract=self.contract,
            steps=self.steps,
            outcomes=rules,
            provenance=provenance,
        )
