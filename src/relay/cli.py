"""Explicit commands for discovery, replay, demos, the operator workbench, and schemas."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from relay.bank import create_bank
from relay.example import example_capability
from relay.operator import create_console
from relay.policy import Policy
from relay.runtime import RunManager, serve
from relay.schema import Action, Capability, target

DEFAULT_INPUTS = {"member_id": "12345", "account_type": "savings", "nickname": "Holiday Fund"}


def load_capability(path: str | None) -> Capability:
    return Capability.model_validate_json(Path(path).read_text()) if path else example_capability()


async def simulate_operator(manager: RunManager) -> None:
    """Explicitly labeled test driver, exercising the same control-transfer mechanism."""
    current = manager.current
    while not manager.task.done():
        if current.control.owner == "paused":
            current.journal.emit(
                "operator_simulation", note="Automated test driver, not a real human."
            )
            await current.control.claim(current.control.generation)
            reason = current.control.request["reason"]
            name = {
                "session_expired": "Resume staff session",
                "unexpected_dialog": "Dismiss supervisor notice",
            }.get(reason)
            if not name:
                await current.control.abort()
                return
            await current.surface.act(
                Action(kind="click", target=target(name, "button")), {}, actor="human"
            )
            await current.control.resume(current.control.generation)
        await asyncio.sleep(0.05)


def print_result(manager: RunManager) -> None:
    current = manager.current
    print(json.dumps(current.journal.redactor.clean(current.result.model_dump()), indent=2))
    print(f"Evidence: {current.journal.directory}")


async def command(args) -> int:
    if args.command == "bank":
        async with serve(create_bank(), args.bank_port):
            print(f"Northstar demo: http://127.0.0.1:{args.bank_port}", flush=True)
            await asyncio.Event().wait()
    if args.command == "schema":
        print(json.dumps(Capability.model_json_schema(), indent=2))
        return 0
    if args.command == "example":
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(example_capability().model_dump_json(indent=2) + "\n")
        print(f"Authored offline example (not discovery evidence): {path}")
        return 0
    capability = load_capability(getattr(args, "artifact", None))
    if args.command == "verify" and args.target:
        raise ValueError("Verification uses only the bundled synthetic fixture")
    if args.command == "catalog":
        print(
            json.dumps(
                {
                    "name": capability.contract.name,
                    "version": capability.version,
                    "contract": capability.contract.model_dump(),
                    "provenance": capability.provenance.model_dump(),
                },
                indent=2,
            )
        )
        return 0
    policy = Policy.model_validate_json(Path(args.policy).read_text()) if args.policy else Policy()
    manager = RunManager(
        target_url=args.target or f"http://127.0.0.1:{args.bank_port}",
        evidence_root=Path(args.evidence),
        capability=capability,
        headless=not args.headed,
        policy=policy,
        intervention_timeout=args.intervention_timeout,
        total_timeout=args.timeout,
    )
    bank_app = create_bank()

    async def run():
        if args.command == "verify":
            from relay.verification import verify

            passed = await verify(
                manager,
                bank_app,
                repeat=args.repeat,
                allow_authored=args.allow_authored,
                simulate_operator=simulate_operator,
            )
            return 0 if passed else 1
        if args.command == "studio":
            print(f"Relay workbench: http://127.0.0.1:{args.console_port}", flush=True)
            print(f"Capability provenance: {capability.provenance.kind}", flush=True)
            await asyncio.Event().wait()
            return 0
        if args.command == "demo":
            cases = [
                ("normal", {**DEFAULT_INPUTS, "member_id": "67890", "nickname": "Travel Fund"}),
                ("normal", {**DEFAULT_INPUTS, "member_id": "99999"}),
                ("normal", {**DEFAULT_INPUTS, "nickname": "BLOCKED"}),
                ("slow", DEFAULT_INPUTS),
                ("known_dialog", DEFAULT_INPUTS),
                ("permission_denied", DEFAULT_INPUTS),
                ("session_expired", DEFAULT_INPUTS),
                ("unknown_dialog", DEFAULT_INPUTS),
                ("app_error", DEFAULT_INPUTS),
                ("ambiguous", DEFAULT_INPUTS),
                ("redirect_escape", DEFAULT_INPUTS),
            ]
            report = []
            all_expected = True
            for scenario, inputs in cases:
                task = manager.start(inputs, scenario=scenario)
                operator = asyncio.create_task(simulate_operator(manager))
                await task
                await operator
                print_result(manager)
                expected = (
                    ("business_outcome", "member_not_found")
                    if inputs["member_id"] == "99999"
                    else ("business_outcome", "validation_error")
                    if inputs["nickname"] == "BLOCKED"
                    else {
                        "permission_denied": ("failure", "permission_denied"),
                        "app_error": ("failure", "app_unavailable"),
                        "ambiguous": ("failure", "ambiguous_target"),
                        "redirect_escape": ("failure", "origin_denied"),
                    }.get(scenario, ("success", "completed"))
                )
                matched = (
                    manager.current.result.status,
                    manager.current.result.code,
                ) == expected and manager.current.result.model_calls == 0
                all_expected = all_expected and matched
                report.append(
                    {
                        "matched_expectation": matched,
                        "expected_status": expected[0],
                        "expected_code": expected[1],
                        "scenario": scenario,
                        "input_case": "not_found"
                        if inputs["member_id"] == "99999"
                        else "validation"
                        if inputs["nickname"] == "BLOCKED"
                        else "valid",
                        **manager.current.result.model_dump(exclude={"outputs"}),
                    }
                )
            Path(args.evidence).mkdir(parents=True, exist_ok=True)
            (Path(args.evidence) / "matrix.json").write_text(json.dumps(report, indent=2) + "\n")
            return 0 if all_expected else 1
        inputs = json.loads(args.inputs)
        model = None
        if args.command == "discover":
            from relay.models import create_model

            model = create_model(args.provider, args.model)
        task = manager.start(
            inputs,
            mode="discover" if args.command == "discover" else "replay",
            scenario=args.scenario,
            variant=args.variant,
            goal=getattr(args, "goal", ""),
            model=model,
        )
        operator = (
            asyncio.create_task(simulate_operator(manager)) if args.simulate_operator else None
        )
        await task
        if operator:
            await operator
        print_result(manager)
        if args.command == "discover" and manager.current.artifact and args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(manager.current.artifact.model_dump_json(indent=2) + "\n")
            print(f"Recorded capability: {output}")
        return 0 if manager.current.result.status in {"success", "business_outcome"} else 1

    try:
        async with serve(create_console(manager), args.console_port):
            if args.target:
                return await run()
            async with serve(bank_app, args.bank_port):
                return await run()
    finally:
        await manager.close()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="relay", description="Discover once. Replay deliberately.")
    sub = root.add_subparsers(dest="command", required=True)
    bank = sub.add_parser("bank", help="Serve the synthetic target application")
    bank.add_argument("--bank-port", type=int, default=8765)
    sub.add_parser("schema", help="Print the versioned capability JSON schema")
    example = sub.add_parser("example", help="Write a labeled offline example")
    example.add_argument("--output", default="examples/prepare_subaccount.json")
    catalog = sub.add_parser("catalog", help="Inspect a callable capability contract")
    catalog.add_argument("--artifact")
    for name in ("studio", "replay", "discover", "demo", "verify"):
        cmd = sub.add_parser(name)
        cmd.add_argument(
            "--artifact", help="Saved capability; otherwise use the labeled offline example"
        )
        cmd.add_argument("--bank-port", type=int, default=8765)
        cmd.add_argument("--console-port", type=int, default=8766)
        cmd.add_argument(
            "--target", help="Use an already-running target instead of starting the demo bank"
        )
        cmd.add_argument(
            "--headed", action="store_true", help="Also show the actual controlled Chromium window"
        )
        cmd.add_argument("--policy", help="Trusted policy JSON configuration")
        cmd.add_argument("--evidence", default="runs")
        cmd.add_argument("--timeout", type=float, default=300)
        cmd.add_argument("--intervention-timeout", type=float, default=180)
        if name in {"replay", "discover"}:
            cmd.add_argument("--inputs", default=json.dumps(DEFAULT_INPUTS))
            cmd.add_argument("--scenario", default="normal")
            cmd.add_argument("--variant", choices=["base", "harbor"], default="base")
            cmd.add_argument(
                "--simulate-operator",
                action="store_true",
                help="Explicitly simulated operator for repeatable tests",
            )
        if name == "verify":
            cmd.add_argument("--repeat", type=int, default=20)
            cmd.add_argument(
                "--allow-authored",
                action="store_true",
                help="Permit offline verification; never claim it as discovery evidence",
            )
        if name == "discover":
            cmd.add_argument(
                "--provider",
                choices=["openai", "experiential", "bridge"],
                help="Discovery provider; defaults to RELAY_PROVIDER or openai",
            )
            cmd.add_argument("--model")
            cmd.add_argument(
                "--goal",
                default="Prepare a new sub-account for the supplied member, using the supplied account type and nickname. Stop at the review screen.",
            )
            cmd.add_argument("--output", default="runs/recorded-capability.json")
    return root


def main() -> None:
    args = parser().parse_args()
    try:
        code = asyncio.run(command(args))
    except KeyboardInterrupt:
        code = 130
    except (ValueError, OSError) as exc:
        # Pydantic errors can include rejected values; never echo the whole exception.
        print(
            f"Configuration error ({type(exc).__name__}). Check arguments, schema, and environment."
        )
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
