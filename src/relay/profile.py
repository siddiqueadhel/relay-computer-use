"""Reviewed Northstar contract and error vocabulary. No discovery route is specified here."""

from relay.policy import Policy
from relay.schema import (
    Action,
    Condition,
    Contract,
    FieldSpec,
    Locator,
    OutcomeRule,
    Output,
    Target,
    Value,
    target,
    visible,
)


def row(name: str, control: str = "value") -> Target:
    return Target(
        frame_path=["workspace"], candidates=[Locator(by="row", name=name, control=control)]
    )


def contract() -> Contract:
    return Contract(
        name="prepare_subaccount",
        description="Prepare a savings or money-market sub-account for a member and stop at review; never create an account.",
        inputs={
            "member_id": FieldSpec(
                description="Member number", pattern=r"\d{5}", sensitive=True, max_length=5
            ),
            "account_type": FieldSpec(description="Product code", enum=["savings", "money_market"]),
            "nickname": FieldSpec(description="Account name", sensitive=True, max_length=40),
        },
        outputs={
            "member_id": Output(
                spec=FieldSpec(description="Verified member", sensitive=True),
                target=row("Member number"),
                equals_input="member_id",
            ),
            "account_type": Output(
                spec=FieldSpec(description="Requested product"),
                target=row("Product"),
                equals_input="account_type",
            ),
            "nickname": Output(
                spec=FieldSpec(description="Requested account name", sensitive=True),
                target=row("Account name"),
                equals_input="nickname",
            ),
            "status": Output(
                spec=FieldSpec(description="Request state", enum=["ready_for_review"]),
                target=row("Request status"),
            ),
        },
        success=[
            visible("Review request"),
            Condition(
                kind="text_equals",
                target=row("Request status"),
                expected=Value(source="literal", value="ready_for_review"),
            ),
        ],
    )


def outcomes() -> list[OutcomeRule]:
    return [
        OutcomeRule(
            code="member_not_found", when=visible("Member not found"), disposition="business"
        ),
        OutcomeRule(
            code="validation_error", when=visible("Validation error"), disposition="business"
        ),
        OutcomeRule(code="permission_denied", when=visible("Access denied"), disposition="fail"),
        OutcomeRule(
            code="app_unavailable", when=visible("Service unavailable"), disposition="fail"
        ),
        OutcomeRule(
            code="session_expired", when=visible("Staff session expired"), disposition="intervene"
        ),
        OutcomeRule(code="session_lost", when=visible("Session expired"), disposition="intervene"),
        OutcomeRule(
            code="unexpected_dialog",
            when=visible("Supervisor review required"),
            disposition="intervene",
        ),
        OutcomeRule(
            code="service_notice",
            when=visible("Service notice"),
            disposition="recover",
            recovery=Action(kind="click", target=target("Acknowledge message", "button")),
            max_attempts=1,
        ),
    ]


def default_policy() -> Policy:
    return Policy()
