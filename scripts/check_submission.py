"""Read-only readiness checks; writes only a sanitized local checklist JSON.

This verifies evidence consistency, not provider authenticity, screenshot privacy,
or hiring readiness. Review those manually before publishing.
"""

import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from relay.schema import Capability

ROOT = Path(__file__).resolve().parents[1]


def valid_console_handoff(directory: Path, artifact_digest: str) -> bool:
    """Check one real console transfer plus explicit test-driver attribution.

    This checks consistency, not whether a human physically clicked the controls.
    """
    try:
        raw = (directory / "events.jsonl").read_bytes()
        log = [json.loads(line) for line in raw.splitlines()]
        result_raw = (directory / "result.json").read_bytes()
        result = json.loads(result_raw)
        attestation = json.loads((directory / "operator-attestation.json").read_text())
        transfers = [e for e in log if e["event"] == "control_transferred"]
        if [e["owner"] for e in transfers] != ["human", "automation"]:
            return False
        claim, resume = transfers
        session = claim["session_id"]
        operator_actions = [e for e in log if e["event"] == "operator_console_action"]
        return (
            attestation["test_driver"] in {"physical_human", "ai_computer_use"}
            and attestation["physical_human_operated"]
            == (attestation["test_driver"] == "physical_human")
            and attestation["run_id"] == result["run_id"] == directory.name
            and attestation["events_sha256"] == hashlib.sha256(raw).hexdigest()
            and attestation["result_sha256"] == hashlib.sha256(result_raw).hexdigest()
            and result["status"] == "success"
            and result["model_calls"] == 0
            and result["handoffs"] == 1
            and all(e.get("session_id", session) == session for e in log)
            and claim["generation"] == resume["generation"]
            and any(
                e["event"] == "capability_loaded" and e["sha256"] == artifact_digest for e in log
            )
            and any(e["event"] == "intervention_requested" and e["seq"] < claim["seq"] for e in log)
            and any(claim["seq"] < e["seq"] < resume["seq"] for e in operator_actions)
            and any(e["event"] == "resume_verified" and e["seq"] > resume["seq"] for e in log)
            and not any(e["event"] == "operator_simulation" for e in log)
            and not any(
                e["event"] in {"step_started", "step_completed"}
                and claim["seq"] < e["seq"] < resume["seq"]
                for e in log
            )
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def check_submission(root: Path) -> dict:
    checks = []

    def check(name, operation):
        try:
            passed = bool(operation())
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError):
            passed = False
        checks.append({"check": name, "passed": passed})

    def data(path):
        return json.loads((root / path).read_text())

    def events(path):
        return [json.loads(line) for line in (root / path).read_text().splitlines()]

    def capability():
        return Capability.model_validate(data("evidence/submission/prepare_subaccount.json"))

    def discovery():
        cap = capability()
        p = cap.provenance
        if (
            p.kind != "llm_discovery"
            or p.provider not in {"openai_responses", "experiential_responses"}
            or not p.run_id
        ):
            return False
        directory = Path("evidence/submission/discovery") / p.run_id
        log = root / directory / "events.jsonl"
        prefix = b"".join(log.read_bytes().splitlines(keepends=True)[: p.evidence_event_count])
        receipt = [e for e in events(directory / "events.jsonl") if e["event"] == "model_receipt"]
        result = data(directory / "result.json")
        recorded = Capability.model_validate(data(directory / "capability.json"))
        return (
            p.model_calls > 0
            and p.evidence_event_count > 0
            and hashlib.sha256(prefix).hexdigest() == p.evidence_sha256
            and len(receipt) == p.model_calls
            and all(r.get("response_id") for r in receipt)
            and result["status"] == "success"
            and result["model_calls"] == p.model_calls
            and recorded.digest() == cap.digest()
        )

    def replays():
        cap = capability()
        base = Path("evidence/submission/replay")
        report = data(base / "verification-summary.json")
        if not (
            report["passed"]
            and report["discovery_evidence_present"]
            and report["artifact_sha256"] == cap.digest()
            and len(report["cases"]) >= 12
        ):
            return False
        for case in report["cases"]:
            if Path(case["evidence"]).name != case["evidence"]:
                return False
            directory = base / case["evidence"]
            result = data(directory / "result.json")
            loaded = [
                e for e in events(directory / "events.jsonl") if e["event"] == "capability_loaded"
            ]
            if (
                not case["passed"]
                or result["model_calls"] != 0
                or [result["status"], result["code"]] != case["expected"]
                or not loaded
                or loaded[0]["sha256"] != cap.digest()
            ):
                return False
        return not (
            report["guard"]["blocked_model_imports"]
            or report["guard"]["blocked_nonlocal_connections"]
        )

    def human():
        cap = capability()
        for base in ("evidence/manual", "evidence/submission/handoff"):
            for path in (root / base).glob("*/events.jsonl"):
                if valid_console_handoff(path.parent, cap.digest()):
                    return True
        return False

    headings = [
        "Architecture",
        "Artifact schema",
        "Determinism & error handling",
        "Heterogeneity & multi-tenant",
        "Escalation & handoff",
        "Safety",
        "Cuts",
    ]
    check(
        "required_report_headings",
        lambda: re.findall(r"^## (.+)$", (root / "REPORT.md").read_text(), re.M) == headings,
    )
    check("successful_live_discovery_with_matching_receipts_and_digest", discovery)
    check("guarded_replay_of_that_discovered_artifact", replays)
    check("attributed_live_console_handoff_on_that_artifact", human)

    def tests():
        reports = [
            root / "evidence/verification/final-verification.xml",
            root / "evidence/verification/gateway-full-suite.xml",
            root / "evidence/verification/console-provider-fix.xml",
        ]
        latest = max((p for p in reports if p.is_file()), key=lambda p: p.stat().st_mtime)
        suites = ET.parse(latest).getroot().iter("testsuite")
        suites = list(suites)
        return bool(suites) and all(
            int(s.get("tests", "0")) > 0
            and all(int(s.get(k, "0")) == 0 for k in ("failures", "errors", "skipped"))
            for s in suites
        )

    check("latest_full_test_report_passed", tests)
    check(
        "private_env_is_git_ignored",
        lambda: (
            subprocess.run(
                ["git", "check-ignore", "--quiet", ".env"], cwd=root, capture_output=True
            ).returncode
            == 0
        ),
    )

    def secrets():
        listing = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            check=True,
        )
        pattern = re.compile(
            rb"\b(?:sk-[A-Za-z0-9_-]{20,}|xpl_[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{30,})"
        )
        for name in listing.stdout.decode().split("\0"):
            if name and (root / name).is_file() and pattern.search((root / name).read_bytes()):
                return False
        return True

    check("no_recognized_api_key_patterns_in_git_candidates", secrets)
    return {
        "automated_checks_passed": all(c["passed"] for c in checks),
        "checks": checks,
        "manual_review_still_required": [
            "Screenshot privacy",
            "Fresh-checkout setup",
            "Evidence authenticity and limitations",
            "Explicit approval before publication or email",
        ],
    }


if __name__ == "__main__":
    report = check_submission(ROOT)
    (ROOT / "evidence/readiness.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["automated_checks_passed"] else 1)
