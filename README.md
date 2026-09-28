# Relay

**Discover once. Replay deliberately.**

Relay turns an LLM's interaction with a real UI into a typed, reviewable capability. Its replay engine executes that capability with new parameters, checks the result, handles known business outcomes, and transfers the same live browser session to an operator when necessary.

The included Northstar Credit Union application is a **synthetic local sandbox**. The workflow searches for a member, prepares a savings sub-account, and stops at review. No real financial system, credentials, or personal data are used.

> **Verification status:** Genuine seven-call discovery, 31 model-free replay checks on its artifact, and separately attributed AI-operated and user-reported person-operated handoffs succeeded. The latest suite passed **118 tests**; an earlier 102-test snapshot also passed in a new key-free environment. See [evidence/README.md](evidence/README.md) for evidence and limitations. The separate `examples/prepare_subaccount.json` is hand-authored; the genuine artifact is `evidence/submission/prepare_subaccount.json`.

> **Provider check corrected (September 21):** Workbench discovery now validates the selected provider's own key using the same rules as the CLI. Replay remains key-free. Configuration preflight does not load a provider SDK or contact the provider; it does not verify account credit or key authentication. See [the review](evidence/submission/REVIEW.md) for verification status. This is a local application, not a publicly deployed service.

## Start the workbench

**Optional video:** [Watch the 86-second narrated demonstration](evidence/demo/Relay-Complete-Demo.mp4). It combines real recorded replay, a not-found outcome, and an AI-operated same-session handoff with explanatory graphics. The presenter and voice are synthetic; see [demo attribution and scope](evidence/demo/README.md). The discovery logs and capability under `evidence/submission/` remain the source evidence.

Requires Python 3.11+ (3.12 recommended), [uv](https://docs.astral.sh/uv/), and Chromium. The lockfile pins the Python dependencies.

```bash
uv sync --locked --extra dev --python 3.12
uv run playwright install chromium
uv run relay studio
```

Open **http://127.0.0.1:8766**. The workbench starts the target app on port 8765. It shows the saved workflow, verified steps, model-call count, masked evidence, structured results, and operator controls. Replay works without model credentials.

Use `--headed` to also show the actual controlled Chromium window. Use `--artifact PATH` to load a discovered capability instead of the authored example. All servers bind to loopback.

## Exact discovery → replay demo

Set `OPENAI_API_KEY` in your shell environment. Never put the key in the repository or a command argument. `RELAY_MODEL` optionally selects the model; the default is `gpt-4.1-mini`. Model access and billing belong to your provider account.

Alternatively, create a local `.env` from the empty `.env.example` template and enter your key there. `.env` is ignored by Git; **never put a real key in `.env.example`**. On macOS/Linux, restrict the local file with `chmod 600 .env`. Load it explicitly with `uv run --env-file .env relay discover` (or `uv run --env-file .env relay studio`). Relay itself does not automatically load `.env`. Keep the file out of screenshots, shared archives, and uploads; Git exclusion is not encryption. Revoke and replace any key exposed in chat or source control.

To check only whether the key is configured, without printing it or making an API request:

```bash
uv run --env-file .env python -c 'import os; print("Key configured:", bool(os.getenv("OPENAI_API_KEY")))'
```

The commands below assume the shell environment is already configured. When using `.env`, add `--env-file .env` immediately after `uv run` for the discovery command only. Replay requires neither the key nor that file.

```bash
uv run relay discover \
  --goal "Find the supplied member, prepare the requested sub-account, and stop at review." \
  --inputs '{"member_id":"12345","account_type":"savings","nickname":"Holiday Fund"}' \
  --output evidence/submission/prepare_subaccount.json \
  --evidence evidence/submission/discovery

uv run relay replay \
  --artifact evidence/submission/prepare_subaccount.json \
  --inputs '{"member_id":"67890","account_type":"money_market","nickname":"Travel Fund"}' \
  --evidence evidence/submission/replay

uv run relay replay \
  --artifact evidence/submission/prepare_subaccount.json \
  --inputs '{"member_id":"99999","account_type":"savings","nickname":"Travel Fund"}' \
  --evidence evidence/submission/replay
```

Run these separately from `studio`, or choose unused `--bank-port` and `--console-port` values. The first command genuinely calls the model, drives browser controls, validates the goal, and writes an artifact only after success. The second invokes the recorded capability with new inputs. The third should return `business_outcome / member_not_found`.

No target business APIs are used. The browser submits ordinary UI forms. The agent sees visible controls and redacted page text, not application source or backend state. The runtime binds private parameter values locally; the model chooses parameter references.

Provider errors stop the run without emitting a capability. Safe diagnostics distinguish authentication, permission, known quota/spend codes, rate limits, and unavailable service. An unclassified HTTP 429 is `model_api_limited`; do not assume it is transient. Each adapter call makes one HTTP attempt, with no hidden SDK retries. Check API credits and project limits before retrying billing-related failures. Raw provider error messages and response bodies are never logged.

### Optional Experiential gateway

Put `EXPLABS_API_KEY` in the Git-ignored `.env`, never `.env.example`. It must be
a gateway inference key, not a direct OpenAI credential. The adapter uses
`https://api.experientiallabs.ai/v1` and records `experiential_responses`
provenance, returned model/response IDs, token usage, and serving-provider
attribution when known. Neither adapter honors `OPENAI_BASE_URL` overrides.

```bash
uv run --env-file .env relay discover --provider experiential --model gpt-5.6-luna \
  --goal "Find the supplied member, prepare the requested sub-account, and stop at review." \
  --inputs '{"member_id":"12345","account_type":"savings","nickname":"Holiday Fund"}' \
  --output evidence/submission/prepare_subaccount.json \
  --evidence evidence/submission/discovery
```

Then use the same model-free replay/verification commands. `EXPLABS_MODEL`
optionally overrides this provider's default, `gpt-5.6-luna`; `RELAY_MODEL`
remains the direct OpenAI setting. For gateway discovery in the workbench, set
`RELAY_PROVIDER=experiential` in the private environment and start with
`uv run --env-file .env relay studio`. Only `EXPLABS_API_KEY` is required for that
provider; no unrelated OpenAI key is needed. Missing/malformed configuration
returns a safe HTTP 422 before a run starts. The stdin bridge is CLI-only and
is rejected by workbench discovery. These settings do not affect key-free replay.

The gateway adapter explicitly uses `reasoning.effort=none`, preserving the
existing non-reasoning latency baseline, with at most 1,200 output tokens per
decision, a 40-second request timeout, and no SDK retries. Advertised parameter
drops fail closed before acting. The typed decision schema remains unchanged.

Account eligibility, free allowances, paid overflow, routing, and retention are
external settings: this code does not modify them or guarantee free calls. Keep
paid overflow off for a free-only demonstration. According to Experiential's
documentation, new Free organizations normally capture prompts and responses
for 30 days. `store=False` and **ZDR enforceable** are not end-to-end retention
guarantees. Use only synthetic, redacted data. See the
[quickstart](https://platform.experientiallabs.ai/docs/quickstart),
[compatibility](https://platform.experientiallabs.ai/docs/openai-compatibility),
and [data controls](https://platform.experientiallabs.ai/docs/data-controls).

### External LLM bridge

`discover --provider bridge --model "your-external-host-label"` supports a tool-using LLM host without embedding a provider SDK in that host. Each stdout `llm_request` contains the current live observation, contract, and recent actions. The host returns one `Decision` JSON object on stdin. This is an interactive protocol, not a canned discovery script.

The artifact records `provider: external_llm_bridge`; direct API runs record `openai_responses` with model response receipts. The bridge's model label is an attribution supplied by its caller, not cryptographic proof of a provider invocation. A real LLM host must actually supply decisions for a bridge run to qualify as discovery evidence. Unit-test models and authored examples are separately labeled.

## Try failure handling without a model

```bash
uv run relay replay --artifact examples/prepare_subaccount.json
uv run relay demo --artifact examples/prepare_subaccount.json --evidence runs/demo
```

The demo matrix includes a second member, member not found, validation rejection, slow response, known notice, permission denial, expired session, unknown dialog, app error, ambiguous control, and forbidden redirect. Its operator actions are explicitly **simulated**, exercising the real ownership mechanism without claiming a human performed them.

For a human-controlled handoff, start the workbench, select **Expired staff session**, and run replay. When paused:

1. Select **Take control**.
2. Select **Resume staff session** in the live controls. This acts on the existing browser context and session cookies.
3. Select **Return control & resume**.
4. Relay verifies the interrupted step's checkpoint before proceeding.

For submission evidence, load the genuinely discovered artifact and save a live console handoff in the expected location:

```bash
uv run relay studio --artifact evidence/submission/prepare_subaccount.json \
  --bank-port 8875 --console-port 8876 --evidence evidence/manual \
  --timeout 900 --intervention-timeout 600
```

Open `http://127.0.0.1:8876`, perform the handoff above, and note the run ID. This command needs no API key. Do not pass `--simulate-operator`. An external computer-use assistant may test the console, but label it **AI-operated**, never person-operated. The UI's `human` ownership role describes control transfer, not the physical identity of the test driver. Add `operator-attestation.json` beside the run's events/result, declaring `test_driver` (`physical_human` or `ai_computer_use`), `physical_human_operated`, `run_id`, and the SHA-256 hashes `events_sha256` and `result_sha256`. The checker also accepts such runs under `evidence/submission/handoff/`.

For a missing member, use `99999`. For business validation rejection, use nickname `BLOCKED`. For load timeout, select **Load timeout**. A wrong resume state stops with `resume_checkpoint_mismatch`. Final **Create account** is denied even if it appears in a valid artifact.

## Capability and execution contract

```text
Natural-language goal + typed contract
                  ↓
        LLM discovery → recorded capability JSON
                               ↓
Parameters → deterministic replay → verified output / business outcome / failure
                      ↕
          pause → operator → validate → resume
```

The JSON includes schema and capability versions, vendor compatibility metadata, typed inputs/outputs, ordered actions, frame-aware targets with ordered locator candidates, before/after checkpoints, bounded error rules, and provenance. `Value(source="input", value="member_id")` binds invocation data without embedding it in the artifact.

Replay is deterministic in its **decision policy**: for a given observed state, it takes the same declared branch. Runtime data, latency, and business outcomes can change. It does not promise a transactional backend or identical output values from a changing application.

Results distinguish `success`, `business_outcome`, `failure`, and `aborted`, with a machine-readable code, interrupted step, expected checkpoint, observed headings, evidence reference, and recovery/handoff counts. Actual outputs are returned by the Python runner; saved logs and CLI output redact private values.

An uncertain click is **not blindly retried**. Relay checks whether its postcondition already holds; otherwise it requests intervention. Known notice dismissal is separately declared and bounded. Ambiguous locators fail instead of picking the first control.

```bash
uv run relay catalog --artifact examples/prepare_subaccount.json
uv run relay schema
```

The catalog command exposes the typed invocation contract; the workbench invokes that registered capability by its inputs. This is a small local interface, not a multi-tenant capability service.

## Safety, evidence, and limits

- Policy is checked against the actual resolved control and destination, independently of model/artifact claims. `--policy FILE` loads a trusted JSON policy; see `config/northstar-policy.json`.
- Browser network interception enforces the configured origin, paths, and methods. Popups, downloads, service workers, and WebSocket connections are restricted. The mock `/commit` route is excluded.
- The operator endpoint uses a per-process CSRF token, same-session ownership generation checks, loopback binding, and no CORS grants. It is a **local single-operator demo**, not production authentication.
- Artifacts contain parameter references. Structured logs redact known private values and credential-like patterns. Screenshots mask configured private regions and fields; raw DOM dumps, browser profiles, network traces, and model transcripts are not persisted.
- Redaction depends on a reviewed surface profile. Unknown layouts, unmarked sensitive regions, canvas text, and arbitrary PII require stronger controls before real banking use. No production compliance claim is made.
- Screenshot capture failures produce restricted structured evidence instead of falling back to an unmasked image.
- Human actions are recorded as control/action metadata, with field values omitted. Known interventions remain conditional outcome branches. Other operator-assisted discovery steps become explicit human gates rather than invented autonomous actions.

Each run writes `events.jsonl`, `result.json`, and masked checkpoint/failure evidence beneath its own directory. A successful discovery adds `capability.json`. Its provenance hash covers exactly the first `evidence_event_count` newline-terminated log events, before artifact creation, avoiding a circular hash. `runs/` is ignored by Git; review evidence before deliberately checking it in.

## Verification

Run the frozen local verification matrix against the **discovered** artifact:

```bash
uv run relay verify --artifact evidence/submission/prepare_subaccount.json \
  --repeat 20 --evidence evidence/submission/replay
```

This uses a fresh Python process, removes model credentials, forbids model/discovery imports, and blocks Python network connections outside loopback. Browser traffic is separately restricted by the surface policy. It runs 20 fresh-context repetitions across three synthetic members and two products, plus 11 outcome, recovery, handoff, and markup-variant cases. It checks actual outputs, a fresh fixture session, and zero irreversible commits. Operator actions in this matrix are **simulated**, not person-operated evidence. The summary measures workflow time, excluding browser startup; it is not a production reliability estimate.

Without API access, the same checks can validate the explicitly authored example:

```bash
uv run relay verify --artifact examples/prepare_subaccount.json --allow-authored \
  --repeat 20 --evidence evidence/verification/guarded-authored
```

The Harbor variant changes branding, transient input IDs, DOM wrappers, and form-field order while preserving the reviewed labels and business contract. It uses the same artifact and policy with no override. This is a controlled synthetic compatibility test, **not** an independent benchmark, unseen-site discovery, or implemented multi-tenant platform.

After discovery/replay and an explicitly attributed workbench handoff, check evidence consistency:

```bash
uv run pytest -q --junitxml=evidence/verification/final-verification.xml
uv run python scripts/check_submission.py
```

The checklist checks required headings, matching discovery receipts/log digests, replay artifact identity, a same-session console handoff with explicit driver attribution and evidence hashes, the final test report, Git exclusion of `.env`, and recognized secret patterns (including gateway keys). It intentionally exits nonzero while required evidence is missing. It cannot authenticate a provider receipt or driver attestation, prove a person performed a recorded action, or replace visual privacy review and fresh-setup testing.

```bash
uv run ruff check src tests scripts
uv run pytest -q
# Linux CI requires browser OS dependencies:
uv run playwright install --with-deps chromium
```

The test suite includes schema validation, destination bypasses, sensitive-data redaction, ownership races/stale generations, uncertain side effects, real Chromium scenarios, a same-session operator takeover, output identity checks, and a forbidden final submission. Tests marked `browser` require a working Chromium launch. `uv run pytest -m 'not browser'` runs the checks that do not launch a browser.

If an execution sandbox on macOS prevents Chromium from launching, run this **in an ordinary local terminal**:

```bash
uv run python scripts/browser_host.py
```

Then run Relay/tests with `RELAY_CDP_ENDPOINT=http://127.0.0.1:9223`. The host creates a disposable browser, not your personal browser profile. Each run still creates and closes its own isolated context. Only loopback endpoints are accepted. Stop the host with Ctrl-C after testing. This optional development accommodation does not bypass the app's policy checks.

Port **9223 is an automation connection, not a website**: a blank page at that address is normal, and the headless host does not open a browser window. Keep its Terminal open. The operator workbench is at `http://127.0.0.1:8766` after starting `relay studio`; `/json/version` on port 9223 is only a browser-host readiness check.

## Repository guide

- `src/relay/schema.py`: portable capability and result contracts.
- `surface.py`: browser observation, targeting, actions, checks, and safe evidence.
- `discovery.py`, `models.py`, `recorder.py`: bounded model loop and compilation.
- `replay.py`: model-free execution, outcome classification, and resume verification.
- `policy.py`, `control.py`, `evidence.py`: policy, ownership, and audit boundaries.
- `bank.py`, `bank.css`: synthetic target application.
- `operator.py`, `console.html`: small live operator workbench.
- `tests/`: contract, state-machine, fixture, and real-browser tests.
- [REPORT.md](REPORT.md): the seven requested design sections and deliberate cuts.

The project uses the [OpenAI structured-output API](https://developers.openai.com/api/docs/guides/structured-outputs), [Playwright locators](https://playwright.dev/python/docs/locators), and [Playwright actionability checks](https://playwright.dev/python/docs/actionability). The application-specific policy, capability schema, replay state machine, and evidence handling are implemented here rather than delegated to an agent framework.
