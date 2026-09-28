"""Clearly labeled, hand-authored artifact for offline evaluation. Not discovery evidence."""

from relay.profile import contract, outcomes, row
from relay.schema import Action, Capability, Condition, Provenance, Step, Value, target, visible


def example_capability() -> Capability:
    stages = [
        (Action(kind="navigate", path="/"), None, "Find a member", "Open the configured app."),
        (
            Action(
                kind="fill",
                target=target("Member number", "textbox"),
                value=Value(source="input", value="member_id"),
            ),
            "Find a member",
            None,
            "Bind the member parameter.",
        ),
        (
            Action(kind="click", target=target("Search", "button")),
            "Find a member",
            "Search results",
            "Find the requested relationship.",
        ),
        (
            Action(kind="click", target=target("Open member", "link")),
            "Search results",
            "Member overview",
            "Open the uniquely matched member.",
        ),
        (
            Action(kind="click", target=target("Add sub-account", "link")),
            "Member overview",
            "Prepare sub-account",
            "Start a reversible preparation form.",
        ),
        (
            Action(
                kind="select",
                target=row("Account type", "select"),
                value=Value(source="input", value="account_type"),
            ),
            "Prepare sub-account",
            None,
            "Select the supplied product code.",
        ),
        (
            Action(
                kind="fill",
                target=row("Account name", "input"),
                value=Value(source="input", value="nickname"),
            ),
            "Prepare sub-account",
            None,
            "Bind the supplied account name.",
        ),
        (
            Action(kind="click", target=target("Review request", "button")),
            "Prepare sub-account",
            "Review request",
            "Reach review without committing an account.",
        ),
    ]
    steps = []
    for i, (action, before, after, reason) in enumerate(stages):
        check = (
            visible(after)
            if after
            else Condition(kind="value_equals", target=action.target, expected=action.value)
        )
        steps.append(
            Step(
                id=f"step_{i:02d}",
                action=action,
                before=[visible(before)] if before else [],
                after=[check],
                rationale=reason,
            )
        )
    return Capability(
        version="1.0.0",
        vendor="northstar-core",
        app_version="1.x",
        contract=contract(),
        steps=steps,
        outcomes=outcomes(),
        provenance=Provenance(kind="authored_example", provider="none"),
    )
