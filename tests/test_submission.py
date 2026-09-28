import hashlib
import json
import runpy
from pathlib import Path

import pytest

valid_console_handoff = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/check_submission.py")
)["valid_console_handoff"]


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "missing_attribution",
        "false_person_claim",
        "changed_session",
        "simulation",
        "automation_during_handoff",
        "wrong_artifact",
        "altered_log",
    ],
)
def test_console_evidence_requires_real_transfer_and_honest_attribution(tmp_path, defect):
    directory = tmp_path / "replay-test"
    directory.mkdir()
    log = [
        {"event": "capability_loaded", "sha256": "artifact"},
        {"event": "intervention_requested", "session_id": "session", "generation": 1},
        {
            "event": "control_transferred",
            "owner": "human",
            "session_id": "session",
            "generation": 1,
        },
        {"event": "operator_console_action"},
        {
            "event": "control_transferred",
            "owner": "automation",
            "session_id": "session",
            "generation": 1,
        },
        {"event": "resume_verified"},
    ]
    if defect == "changed_session":
        log[4]["session_id"] = "another-session"
    if defect == "simulation":
        log.append({"event": "operator_simulation"})
    if defect == "automation_during_handoff":
        log.insert(4, {"event": "step_started"})
    raw = "".join(json.dumps({**e, "seq": i}) + "\n" for i, e in enumerate(log)).encode()
    result = json.dumps(
        {"run_id": directory.name, "status": "success", "model_calls": 0, "handoffs": 1}
    ).encode()
    (directory / "events.jsonl").write_bytes(raw)
    (directory / "result.json").write_bytes(result)
    attestation = {
        "test_driver": "ai_computer_use",
        "physical_human_operated": defect == "false_person_claim",
        "run_id": directory.name,
        "events_sha256": hashlib.sha256(raw).hexdigest(),
        "result_sha256": hashlib.sha256(result).hexdigest(),
    }
    if defect != "missing_attribution":
        (directory / "operator-attestation.json").write_text(json.dumps(attestation))
    if defect == "altered_log":
        (directory / "events.jsonl").write_bytes(raw + b"\n")
    assert valid_console_handoff(
        directory, "other" if defect == "wrong_artifact" else "artifact"
    ) is (defect is None)
