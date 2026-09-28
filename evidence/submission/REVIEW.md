# Evidence and requirement review

Reviewed September 21, 2026 by the coding assistant against the user-supplied assignment text. This is a code/evidence review, not independent certification or a hiring guarantee.

## Verdict

The end-to-end vertical slice is demonstrated, and the identified gateway-console integration bug is **fixed and regression-tested**. The latest suite passed 118 tests. The submission is not yet published: public GitHub publication and the email are outstanding. Green checks cover the tested behavior and evidence, not all possible functionality or publication approval.

## Closed finding — workbench provider check

**Original issue:** workbench gateway discovery checked the wrong key in `src/relay/operator.py`.

Before the fix, with `RELAY_PROVIDER=experiential`, only `EXPLABS_API_KEY` configured, and a valid local control token, POSTing discovery to `/api/run` returned HTTP 422 asking for `OPENAI_API_KEY`. This was reproduced using an in-process request and a placeholder key, with no provider call. The earlier 102 tests did not cover this combination.

After user authorization, the console and model factory now share provider selection and key-validation rules. Preflight does not instantiate a client or contact a provider. Missing/blank/malformed keys and unknown providers produce safe HTTP 422 responses; the stdin bridge is rejected in the workbench because it requires CLI interaction. Replay bypasses discovery configuration and remains key-free.

Sixteen new tests cover provider-only configuration, default OpenAI selection, no cross-provider fallback, errors without secret echo, CSRF protection, bridge rejection, replay without model imports, and both provider paths through the real console endpoint/runner/browser followed by key-free replay. Those browser tests use fake SDK responses and explicitly `test_fixture` provenance; they do not count as new genuine LLM runs. The earlier successful live discovery and artifact remain unchanged.

## Requirement checklist

- [x] **3.1 — goal + target and real agent loop:** CLI accepts natural-language goal and target entry point. The bounded loop observes visible controls, requests one typed model action, binds private values locally, enforces policy, and executes against Chromium. Successful real discovery: `discover-20260920T021923-38965d88`, seven gateway model decisions plus bootstrap navigation. Qualification: this is one reviewed Northstar workflow/contract, not an arbitrary-goal general-purpose agent. The workbench provider check is now corrected.
- [x] **3.2 — reusable artifact:** `prepare_subaccount.json` validates against the strict schema, declares typed inputs/outputs, eight actions, frame-aware targets, checkpoints, version and provenance. Private values are references. Recorded artifact and exported artifact digests match.
- [x] **3.3 — deterministic replay and outcomes:** all 31 saved guarded cases load that exact discovered artifact. They cover 20 varied-input repeats plus not-found, validation, slowness, known notice, denied access, app error, ambiguity, forbidden redirect, two simulated handoffs, and Harbor markup variation. Zero model calls and zero irreversible commits. Timeout/uncertain-submit behavior is separately tested in the browser suite; it is not one of the 31 matrix cases.
- [x] **3.4 — scoped safety:** configurable path/action/control allowlists; actual resolved destination/control inspection; unique-target resolution; blocked final account creation; redacted logs/artifacts and masked screenshots. No recognized API-key patterns found in Git candidates; `.env` is ignored. Limits: reviewed fixture, not bank compliance; operator direct headed-browser use is cooperative, not an OS security boundary. Previously chat-exposed keys should be rotated by their owner; this review cannot verify revocation.
- [x] **3.5 — evidence:** matching discovery receipts, structured action explanations, results, observations and richer failure evidence exist. All 88 current PNG files were covered by viewing all 20 byte-distinct images. See `image-review.json` for exact hashes and paths. No exposed full member names, numbers, account names or credentials were observed; synthetic initial avatars and product names remain visible.
- [x] **3.6 — actual handoff:** the earlier AI-operated console test is labeled separately. The user-reported manual run `replay-20260920T030051-f8c6611b` completed with one handoff and zero model calls. Verified one unchanged session/generation, pause, claim, recorded live operator control, return, checked postcondition and completion, with no automation steps during operator ownership. Its adjacent attestation records user-reported physical operation, not independent identity proof; original logs/results are unchanged.
- [x] **3.7 — heterogeneity and reuse design:** the surface protocol separates perception/actions from the flow; named frames, row labels and controlled Harbor variation work. REPORT explains future OS-accessibility/visual adapters, tenant overlays, version validation and approval. Desktop execution, a tenant registry and unseen-app generalization are explicitly not implemented.
- [x] **README setup/demo:** locked Python dependencies, browser install, private provider configuration, exact discovery/replay commands and offline replay are documented, including corrected workbench configuration. A secret-free source copy with a new environment previously passed 102 tests on this Mac/browser host; that clean-setup result predates the 16 new regressions.
- [x] **REPORT:** all seven required headings exist and cover decisions, trade-offs and cuts. It is about 1,650 words; the brief's approximate 1–3 page target depends on rendering and has not been visually page-counted.
- [x] **Saved end-to-end demonstration:** genuine artifact, discovery, parameterized replay, error cases and human handoff are present under `evidence/`. Screen recording is optional and was not produced.
- [x] **Workbench gateway discovery:** the reported key-check bug is fixed and regression-tested without live API calls.
- [ ] **Public Git repository:** no remote or committed submission snapshot is configured. GitHub CI configuration exists but no actual GitHub Actions run has been demonstrated.
- [ ] **Submission email:** not sent; requires the user's explicit approval and final public repository URL.
- [ ] **Optional comparison with the other repository:** no URL was supplied. It has not been cloned or executed during this review. This comparison is not an assignment requirement.

## Latest verification

After the fix, **118/118 tests passed in 139.58 seconds**; see `../verification/console-provider-fix.xml`. Ruff lint and formatting checks passed. The readiness script now includes this newer full-suite report rather than relying only on the older test files.

Earlier on September 21, a test attempt was blocked during local socket setup (79 passed, 23 setup errors), followed by 102/102 passing after network permission. Both reports remain unchanged as historical diagnostics. The prior live discovery was not rerun; its receipts and artifact remain the genuine evidence. No live model calls, billing changes, deployment or publication occurred during this fix.

Credential handling stays in the server environment, in line with [official OpenAI guidance](https://developers.openai.com/api/reference/overview#authentication). The workbench exposes only safe configuration errors, never key values.

## Deployment and what the user needs to do

This is a local runnable demo, not a deployed public service. Nothing was pushed, hosted or emailed. A hosted bank/operator console is not required by the assignment and should not be exposed publicly in its current local-only form.

The user's handoff already passed; another manual handoff is not needed to establish that evidence. Rehearse explaining normal replay versus not-found versus denied access, then approve the exact publication contents. Additional-machine setup is useful but was not performed. Independent Bugbot/security review was not run; the review above is the main coding assistant's work.
