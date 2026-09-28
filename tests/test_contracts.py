import copy

import pytest
from pydantic import ValidationError

from relay.control import OwnershipError, SessionControl
from relay.evidence import Journal, Redactor
from relay.example import example_capability
from relay.policy import Policy, PolicyViolation
from relay.profile import contract
from relay.schema import Action, Capability


def test_contract_rejects_extra_wrong_and_unbound_data():
    spec = contract()
    valid = dict(member_id="12345", account_type="savings", nickname="Holiday Fund")
    spec.validate_inputs(valid)
    for invalid in (
        {**valid, "member_id": 12345},
        {**valid, "account_type": "checking"},
        {**valid, "extra": True},
        {**valid, "member_id": "../../etc"},
    ):
        with pytest.raises(ValueError):
            spec.validate_inputs(invalid)


def test_schema_rejects_versions_ambiguity_and_invalid_references():
    source = example_capability().model_dump()
    for mutation in ("version", "reference", "duplicate", "extra"):
        value = copy.deepcopy(source)
        if mutation == "version":
            value["schema_version"] = "9.0"
        elif mutation == "reference":
            value["steps"][1]["action"]["value"]["value"] = "secret"
        elif mutation == "duplicate":
            value["steps"][1]["id"] = value["steps"][0]["id"]
        else:
            value["run_shell"] = "not allowed"
        with pytest.raises(ValidationError):
            Capability.model_validate(value)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.invalid/search",
        "http://127.0.0.1:8765/commit",
        "http://127.0.0.1:8766/",
        "http://user:pass@127.0.0.1:8765/search",
        "file:///etc/passwd",
        "http://127.0.0.1:8765/%63ommit",
        "http://127.0.0.1:8765/%252e%252e/search",
        "http://127.0.0.1:8765/a/../search",
        "http://127.0.0.1:8765/\\search",
    ],
)
def test_policy_rejects_destination_bypasses(url):
    with pytest.raises(PolicyViolation):
        Policy().check_url(url, "http://127.0.0.1:8765")


def test_policy_uses_real_control_name_and_does_not_allow_secret_fields():
    for info in (
        {"name": "Create account", "tag": "button"},
        {"name": "Member number", "tag": "input", "type": "password"},
    ):
        with pytest.raises(PolicyViolation):
            Policy().check_control("click", info)
    with pytest.raises(ValidationError):
        Action(kind="navigate", path="//evil.invalid")


def test_redaction_covers_nested_outputs_credentials_and_pii(tmp_path):
    log = Journal(tmp_path, Redactor(["12345", "Holiday Fund"]), mode="test")
    log.emit(
        "sample",
        outputs={"member_id": "12345", "name": "Holiday Fund", "email": "person@example.com"},
        password="do-not-save",
        note="123-45-6789",
    )
    raw = log.path.read_text()
    for forbidden in ["12345", "Holiday Fund", "person@example.com", "do-not-save", "123-45-6789"]:
        assert forbidden not in raw


async def test_control_requires_claim_and_rejects_stale_resumes(tmp_path):
    state = SessionControl(Journal(tmp_path, Redactor(), mode="test"))
    await state.pause(reason="test", step_id="s", expected="checkpoint", evidence=None)
    with pytest.raises(OwnershipError):
        await state.resume(state.generation)
    with pytest.raises(OwnershipError):
        await state.claim(state.generation - 1)
    await state.claim(state.generation)
    with pytest.raises(OwnershipError):
        state.require("automation")
    await state.resume(state.generation)
    state.require("automation")


def test_redaction_preserves_usage_counts_and_masks_typed_private_outputs():
    redactor = Redactor(["428.75"])
    assert redactor.clean({"input_tokens": 14, "access_token": "private"}) == {
        "input_tokens": 14,
        "access_token": "[SECRET]",
    }
    assert redactor.clean({"outputs": {"balance": 428.75}}) == {
        "outputs": {"balance": "[REDACTED]"}
    }


def test_gateway_keys_are_redacted_in_free_text():
    key = "xpl_" + "a" * 40
    assert key not in Redactor().text(f"Provider failed with {key}")


def test_result_duration_cannot_overwrite_journal_clock(tmp_path, monkeypatch):
    times = iter([10.0, 10.0, 20.0])
    monkeypatch.setattr("relay.evidence.time.monotonic", lambda: next(times))
    journal = Journal(tmp_path, Redactor(), mode="test")
    event = journal.emit("run_finished", elapsed_ms=25, seq=-1)
    assert event["elapsed_ms"] == 10000
    assert event["workflow_elapsed_ms"] == 25
    assert event["seq"] == 1
