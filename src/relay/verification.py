"""Synthetic verification harness, not a production agent or discovery implementation."""

from __future__ import annotations

import importlib.abc
import ipaddress
import json
import os
import statistics
import sys
from pathlib import Path


def install_replay_guard() -> dict:
    """Process-lifetime guard. Call only in the dedicated `relay verify` process.

    Python imports/network are checked here. The browser's separate process is
    constrained by BrowserSurface request policy, not by this Python audit hook.
    """
    prefixes = ("openai", "anthropic", "litellm", "relay.models", "relay.discovery")
    if any(n == p or n.startswith(p + ".") for n in sys.modules for p in prefixes):
        raise ValueError("Verification must start in a fresh process without model modules")
    for name in (
        "OPENAI_API_KEY",
        "EXPLABS_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ):
        os.environ.pop(name, None)
    counts = {"blocked_model_imports": 0, "blocked_nonlocal_connections": 0}

    class NoModelImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if any(fullname == p or fullname.startswith(p + ".") for p in prefixes):
                counts["blocked_model_imports"] += 1
                raise ImportError("Model imports are forbidden during verification")
            return None

    def audit(event, args):
        if event == "socket.connect":
            address = args[1]
            if not isinstance(address, tuple):  # Local Unix-domain IPC.
                return
            host = address[0]
        elif event == "socket.getaddrinfo":
            host = args[0]
        else:
            return
        if isinstance(host, bytes):
            host = host.decode("ascii", errors="replace")
        if host == "localhost":
            return
        try:
            allowed = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = False
        if not allowed:
            counts["blocked_nonlocal_connections"] += 1
            raise PermissionError("Only loopback network access is permitted in verification")

    sys.meta_path.insert(0, NoModelImports())
    sys.addaudithook(audit)
    return counts


def cases(repeat: int) -> list[dict]:
    """Frozen synthetic cases; never send this test plan to the discovery model."""
    defaults = {"member_id": "67890", "account_type": "money_market", "nickname": "Travel Fund"}

    def case(
        name,
        *,
        inputs=None,
        scenario="normal",
        variant="base",
        expected=("success", "completed"),
        human=False,
    ):
        return dict(
            name=name,
            inputs=inputs or dict(defaults),
            scenario=scenario,
            variant=variant,
            expected=expected,
            simulated_operator=human,
        )

    result = []
    for i in range(repeat):
        result.append(
            case(
                f"stability_{i + 1:02d}",
                inputs={
                    "member_id": ("12345", "67890", "24680")[i % 3],
                    "account_type": "savings" if i % 2 else "money_market",
                    "nickname": f"Synthetic request {i + 1}",
                },
            )
        )
    result.extend(
        [
            case(
                "not_found",
                inputs={**defaults, "member_id": "99999"},
                expected=("business_outcome", "member_not_found"),
            ),
            case(
                "validation",
                inputs={**defaults, "nickname": "BLOCKED"},
                expected=("business_outcome", "validation_error"),
            ),
            case("slow", scenario="slow"),
            case("known_notice", scenario="known_dialog"),
            case(
                "permission_denied",
                scenario="permission_denied",
                expected=("failure", "permission_denied"),
            ),
            case("app_error", scenario="app_error", expected=("failure", "app_unavailable")),
            case("ambiguous", scenario="ambiguous", expected=("failure", "ambiguous_target")),
            case(
                "forbidden_redirect",
                scenario="redirect_escape",
                expected=("failure", "origin_denied"),
            ),
            case("session_handoff", scenario="session_expired", human=True),
            case("unknown_dialog_handoff", scenario="unknown_dialog", human=True),
            case("harbor_variant", variant="harbor"),
        ]
    )
    return result


async def verify(manager, fixture, *, repeat: int, allow_authored: bool, simulate_operator) -> bool:
    import asyncio

    if not 1 <= repeat <= 100:
        raise ValueError("Repeat count must be between 1 and 100")
    discovered = manager.capability.provenance.kind == "llm_discovery"
    if not discovered and not allow_authored:
        raise ValueError("Use a discovered capability or explicitly pass --allow-authored")
    guard = install_replay_guard()
    records = []
    artifact_digest = manager.capability.digest()
    for case in cases(repeat):
        before_sessions = set(fixture.state.sessions)
        task = manager.start(case["inputs"], scenario=case["scenario"], variant=case["variant"])
        operator = (
            asyncio.create_task(simulate_operator(manager)) if case["simulated_operator"] else None
        )
        result = await task
        if operator:
            await operator
        new_sessions = set(fixture.state.sessions) - before_sessions
        # This is a test oracle only: the automation never reads fixture state.
        commits = sum(s.commits for s in fixture.state.sessions.values())
        events = manager.current.journal.events
        transfers = [e["owner"] for e in events if e["event"] == "control_transferred"]
        output_ok = (
            result.status != "success"
            or all(result.outputs.get(name) == value for name, value in case["inputs"].items())
            and result.outputs.get("status") == "ready_for_review"
        )
        handoff_ok = not case["simulated_operator"] or (
            result.handoffs == 1
            and transfers == ["human", "automation"]
            and any(e["event"] == "resume_verified" for e in events)
            and any(e["event"] == "human_action" for e in events)
        )
        passed = (
            (result.status, result.code) == tuple(case["expected"])
            and result.model_calls == 0
            and output_ok
            and handoff_ok
            and len(new_sessions) == 1
            and commits == 0
            and (case["name"] != "known_notice" or result.recoveries == 1)
            and not any(guard.values())
        )
        record = {
            "case": case["name"],
            "variant": case["variant"],
            "passed": passed,
            "expected": list(case["expected"]),
            "status": result.status,
            "code": result.code,
            "run_id": result.run_id,
            "model_calls": result.model_calls,
            "workflow_elapsed_ms": result.elapsed_ms,
            "outputs_match_inputs": output_ok,
            "new_fixture_sessions": len(new_sessions),
            "irreversible_commits": commits,
            "simulated_operator": case["simulated_operator"],
            "handoff_verified": handoff_ok,
            "evidence": manager.current.journal.directory.name,
        }
        records.append(record)
        print(json.dumps(record), flush=True)
    stability = [r for r in records if r["case"].startswith("stability_")]
    summary = {
        "artifact_sha256": artifact_digest,
        "artifact_provenance": manager.capability.provenance.kind,
        "discovery_evidence_present": discovered,
        "manual_human_demonstration": False,
        "scope": "Synthetic local fixture. Not an independent benchmark or production reliability estimate.",
        "guard": {
            "model_credentials_removed": True,
            "python_network": "loopback only",
            "browser_network": "surface request allowlist",
            **guard,
        },
        "passed": all(r["passed"] for r in records),
        "cases_passed": sum(r["passed"] for r in records),
        "cases_total": len(records),
        "stability": {
            "passed": sum(r["passed"] for r in stability),
            "runs": repeat,
            "median_workflow_ms": statistics.median(r["workflow_elapsed_ms"] for r in stability),
            "max_workflow_ms": max(r["workflow_elapsed_ms"] for r in stability),
        },
        "cases": records,
    }
    destination = Path(manager.evidence_root) / "verification-summary.json"
    destination.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Verification summary: {destination}", flush=True)
    return summary["passed"]
