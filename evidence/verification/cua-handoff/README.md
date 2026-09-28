# Computer-use-operated live handoff test

Test date: 2026-09-19. Result: **passed for the handoff mechanism**.

This test used the Codex computer-use plugin to operate Relay's real operator
console. The operator was an AI assistant, not a person. The existing `human`
owner and `human_action` event names describe Relay's operator-control role;
they do not establish that a physical human performed this test.

## Scope

- Capability: `examples/prepare_subaccount.json`, an authored offline example.
- Scenario: expired staff session in the local synthetic bank application.
- Console: local port 8896; bank: local port 8895; isolated browser context.
- Run: `replay-20260919T211609-508a9655`.
- No model API key was needed for replay. No discovery was performed.

## Actions performed through the UI

1. Selected **Expired staff session**, then **Run deterministic replay**.
2. Waited for the session-expired intervention at `step_04`.
3. Clicked **Take control**.
4. Clicked the live **Resume staff session** control.
5. Clicked **Return control & resume**.
6. Observed **Review checkpoint verified**, eight completed steps, one handoff,
   and zero model calls inside Relay's replay engine.

The external assistant used an LLM to operate the console. That is distinct from
the replay engine's zero-model-call execution. The simulation helper was not used.

## Evidence checked

- [Structured events](replay-20260919T211609-508a9655/events.jsonl): the same
  session ID is retained through intervention, operator ownership, and return to
  automation. No automation step starts or completes during operator ownership.
- The operator click is captured as both a browser event and an operator command;
  these are two observations of one click, not two separate manual actions.
- `resume_verified` precedes continuation; all eight steps complete successfully.
- [Result](replay-20260919T211609-508a9655/result.json): `completed`,
  `ready_for_review`, `model_calls: 0`, `handoffs: 1`.
- [Intervention screenshot](replay-20260919T211609-508a9655/intervention-1.png)
  and [completed screenshot](replay-20260919T211609-508a9655/completed.png) were
  visually inspected. The final review shows masked member details and account
  name, and states that no account has been created. **Create account** was not
  clicked.

Programmatic assertions checked the session identity, ownership sequence,
absence of automation steps while the operator owned the session, recorded
operator action, verified resume, eight completed steps, and successful result.
All passed. The adjacent `operator-attestation.json` records the driver identity
and hashes of the original evidence; it does not modify the original events.

## Limits and follow-up

This verifies a real control-transfer mechanism through its UI. It is **not**
person-operated evidence and **not** evidence of successful LLM discovery. After
discovery succeeds, repeat this test against the newly discovered capability.

An observability defect was found: the final `run_finished.elapsed_ms` uses the
replay-duration clock, while preceding events use the journal clock, which also
includes browser startup. The final number therefore decreases from the prior
event. Event `seq` still orders the actions correctly. Preserve this original
evidence; fix the clock-field collision and regression-test it before final
submission. This does not invalidate the observed ownership transfer or result.
