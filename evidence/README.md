# Evidence inventory

All application data is synthetic. Run-ID dates are UTC. Historical raw logs and test reports are retained unchanged.

## September 21 review update

The [requirement review](submission/REVIEW.md) found a workbench provider-key defect, which is now **fixed and covered by 16 new tests**. The latest full suite passed **118 tests in 139.58 seconds**: [console-provider-fix.xml](verification/console-provider-fix.xml). Both provider paths were tested through the real console endpoint and browser, using fake SDK responses, then replayed with keys removed. No live model calls were made for the fix; genuine discovery evidence remains the earlier seven-call run. The older 102-test pass and initial sandbox setup errors are retained unchanged. Green checks are not publication approval.

The user's manual run [replay-20260920T030051-f8c6611b](submission/handoff/replay-20260920T030051-f8c6611b/) also passed. Its attestation records user-reported physical operation and matches hashes of unchanged logs/results. A review of all **20 distinct PNGs covering 88 files** found no exposed full private values or credentials; [image-review.json](submission/image-review.json) identifies the exact covered files. No public deployment, repository push or submission email has occurred.

## Current verification — September 20, 2026

- **Genuine discovery succeeded:** [discover-20260920T021923-38965d88](submission/discovery/discover-20260920T021923-38965d88/), using `gpt-5.6-luna` through the Experiential Responses gateway. Seven API decisions plus bootstrap navigation produced eight steps. Workflow time was 14.708 seconds, excluding startup. All seven receipts report serving provider `openai` and cost `0.0`: provider-reported usage, not independent billing verification or a promise about future pricing.
- **Saved capability:** [prepare_subaccount.json](submission/prepare_subaccount.json), provenance `llm_discovery`, canonical SHA-256 `268739182ed583bcbf9fb8f03789efa1e8a7fe8d1c60d35108761301ce2eaca3`. The discovery's copy matches. It contains parameter references, not invocation values. Its completion screenshot was visually inspected: name, member number, and account name are masked; no account was created.
- **31/31 guarded replays passed on that artifact:** [verification-summary.json](submission/replay/verification-summary.json). Twenty fresh-context repetitions use varied inputs; eleven further cases cover business outcomes, recovery, hard failures, simulated handoffs, and a markup variant. Every case reported zero model calls, a fresh fixture session, expected outputs/outcomes, and zero irreversible commits. The process removed model credentials and prohibited model/discovery imports and non-loopback Python connections; neither forbidden operation was attempted. Repeated workflow median: 3,175 ms; maximum: 20,999 ms, excluding startup. These shared-machine measurements are not production reliability or latency claims.
- **Real console handoff passed:** [replay-20260920T024943-b43e21a4](submission/handoff/replay-20260920T024943-b43e21a4/). The computer-use plugin ran the expired-session scenario, claimed the paused session, clicked its recovery control, and returned control. The UI showed success, 8/8 steps, one handoff, and zero model calls. Logs preserve the same session and generation, with no automation steps during operator ownership. The adjacent `operator-attestation.json` labels this **AI-operated, not physical-human-operated**, and hashes unchanged logs/results. The UI role `human` describes ownership, not a physical identity.
- **Full suite:** [gateway-full-suite.xml](verification/gateway-full-suite.xml), **102 passed in 78.44 seconds**, including live-browser normal/delayed-navigation discovery/replay regressions, gateway key isolation, structured decisions, safe errors, evidence timing, and handoff attribution. Scripted test models are not genuine-discovery evidence.
- **Fresh environment:** [gateway-clean-setup.xml](verification/gateway-clean-setup.xml), **102 passed in 162.16 seconds**. A separate source copy installed successfully from `uv.lock` into a new virtual environment; imports resolved to that copy, no `.env` was copied, and both API-key variables were absent. This reused Python 3.12.14, the local package cache, and the same Mac's dedicated browser host. It does not verify a new browser installation or another OS/machine. The first install command hit the sandbox's default uv directory restriction; redirecting uv's managed-Python directory to the writable workspace resolved it.
- [readiness.json](readiness.json) checks evidence consistency, report headings, latest test status, key-pattern scanning, and `.env` Git exclusion. It cannot authenticate receipts or approve publication.

## Assignment coverage

- **3.1:** bounded live observe/decide/act discovery is demonstrated by actual provider receipts and completion.
- **3.2:** its typed/versioned artifact declares inputs, outputs, targets, actions, checkpoints, error branches, and provenance.
- **3.3:** the same artifact passed model-free replay with verified outputs, legitimate business outcomes, recoveries, and deliberate failures.
- **3.4:** destination/action allowlists, forbidden final creation, redaction, and ownership checks are tested. These are fixture safeguards, not banking compliance.
- **3.5:** event logs, structured results, sanitized observations, and masked screenshots are saved for discovery and replay.
- **3.6:** real same-session console takeover/resume passed in separately attributed AI-operated and user-reported person-operated runs; matrix operators are labeled simulated.
- **3.7:** legacy-frame/table handling and a controlled Harbor variant are implemented. Desktop and institution-scale reuse are design seams in `REPORT.md`, not implemented platforms.
- **Deliverables:** code, README, seven-section REPORT, and end-to-end evidence exist locally. No public remote or submission email has been created.

## Reproduce without more API calls

After repository setup:

```bash
uv run relay verify --artifact evidence/submission/prepare_subaccount.json \
  --repeat 20 --evidence runs/reverification
uv run relay studio --artifact evidence/submission/prepare_subaccount.json \
  --bank-port 8875 --console-port 8876 --evidence evidence/manual \
  --timeout 900 --intervention-timeout 600
```

Choose unused ports if necessary. On this development Mac, commands used `RELAY_CDP_ENDPOINT=http://127.0.0.1:9223` to connect to the user-started dedicated browser, with both model keys removed for replay. Port 9223 is not an application page. The root README documents live discovery and provider configuration; no key is needed to replay the included artifact.

## Historical evidence, retained unchanged

- [final-verification.xml](verification/final-verification.xml): earlier 78-test suite. [clean-setup.xml](verification/clean-setup.xml): that earlier snapshot also passed 78 tests in a new locked environment without secrets, on this same Mac/browser host. The later 102-test fresh-environment result is linked above and predates the current 118-test suite; a second-machine test remains unperformed.
- [guarded-authored/verification-summary.json](verification/guarded-authored/verification-summary.json): earlier 31-case pass with an authored example, not the discovery-derived matrix above.
- `verification/cua-handoff/`: earlier AI-operated console test on the authored artifact; its historical timing limitation is documented there.
- Discovery attempts `discover-20260919T204050-7ebe9c3f` and `discover-20260919T204257-49affa9f` failed at the direct OpenAI API with HTTP 429 before a decision.
- Gateway attempt `discover-20260919T215019-1d214e8a` obtained two decisions but hit a navigation/observation race. Attempt `discover-20260920T021420-e90e44b7` obtained eight decisions and reached review visually but correctly failed premature completion validation. Neither emitted a successful artifact. The adapter now waits for committed navigation and a usable document and retries only transient observation-context changes; success conditions were not weakened.
- Other older XML/CLI failures diagnose sandbox launch, frame readiness, and timeout issues. They are superseded by the current report, not erased.

## Remaining pre-publication review

Rehearse the demo and explanations, confirm the exact public file selection and data-handling limitations, and obtain explicit approval before publishing or emailing. The gateway-console finding is resolved. The current screenshot inventory was reviewed on September 21; new or modified evidence needs another review. A second-machine setup would provide additional confidence beyond the earlier clean-copy check. Key-pattern checks and visual review are not a comprehensive secret/PII audit. No billing, retention, or routing settings were changed.
