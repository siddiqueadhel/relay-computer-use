# Computer-Use Automation System — Design Report

## Architecture

Relay implements one complete servicing workflow: find a synthetic member, prepare a sub-account, and reach review. Python is used throughout. A server-rendered bank fixture runs in a named iframe and includes deliberately non-semantic, table-labeled form fields. The automation uses the browser UI only. The fixture's in-memory state is accessible to tests for assertions, never to the agent or replay executor.

Discovery, compilation, and replay are separate modules. Discovery asks an LLM for one structured action from the current visible observation. An executor binds input references and applies policy before touching the browser. The recorder stores successful actions and observed checkpoints. Completion requires the declared success conditions and output values to match the invocation, independently of any model claim. The OpenAI adapter uses structured responses and `store=False`; an external-model bridge implements the same decision protocol with distinctly labeled provenance.

Replay does not import a model client. Both paths share a surface adapter, safety policy, audit journal, and session-control state. The CLI and small operator workbench use the same runner. One process and one browser context per run keep lifecycle and ownership easy to inspect; queues and distributed workers would obscure the central problem at this scope.

An optional Experiential Responses adapter keeps the same decision schema, uses a separate key and fixed HTTPS endpoint, and defaults to `gpt-5.6-luna` with reasoning disabled to preserve the non-reasoning latency baseline. Receipts distinguish gateway attribution from the serving provider; SDK retries are disabled, but upstream gateway routing is external. Direct OpenAI defaults remain unchanged.

## Artifact schema

A capability is a Pydantic-validated JSON document. It has a schema version, capability version, vendor/app compatibility metadata, typed input and output contracts, ordered steps, outcomes, and provenance. Unknown fields, unsupported schema versions, duplicate step/outcome identifiers, invalid action shapes, and undeclared parameter references are rejected.

Each step describes its action, target, preconditions, postconditions, timeout, and a short operational rationale. Values are explicit input references or literals; recorded form entry must use declared input references. Targets separate a frame path from an ordered list of locator candidates. Supported browser locators use roles, associated labels, exact visible text, or controls anchored to a visible table row. Zero matches permit the next declared candidate; multiple visible matches fail immediately. There is no arbitrary JavaScript action or implicit coordinate fallback in the artifact.

Outputs have a declared shape and extraction target. Identity-bearing outputs also specify the input they must equal, preventing a correct-looking review page for the wrong member from passing. Known interventions remain conditional outcome branches with repaired checkpoints and absence of the blocker. Other human-assisted discovery preserves manual work as an explicit mandatory human gate. Provenance distinguishes actual model discovery, test fixtures, and authored examples. A content digest identifies the exact artifact used by replay; it is not an approval signature.

## Determinism & error handling

Determinism means predefined targeting, waiting, branching, and recovery with no model deciding the next replay action. It does not imply unchanging business data or exactly-once backend writes. The runtime waits for actionable controls and checks state after each step, rather than sleeping for an assumed page load duration. A primary-heading checkpoint captures navigation; field-entry checkpoints compare the actual value with its bound input. Final output comparisons provide stronger end-to-end verification than headings alone.

Outcome rules separate business results (`member_not_found`, `validation_error`), bounded recovery (one known service notice), operator intervention (expired session or unknown dialog), and hard failure (permission denial, app error, ambiguity, policy violation). A timed-out click may already have taken effect. Relay checks the postcondition and never automatically repeats an uncertain submission. If an operator leaves the session before the interrupted side effect, the runner requires manual completion rather than guessing whether a repeat is safe.

Results include status, code, step, expected conditions, observed headings, outputs, and evidence references. Discovery has step, elapsed-time, and repeated-action limits. Replay has per-step, run, intervention, and handoff-count limits. The test suite distinguishes fast state-machine tests from real-browser integration checks; evidence records what actually ran.

The dedicated verification process removes model credentials, rejects model/discovery imports, and blocks Python network access outside loopback; browser requests remain constrained by the surface policy. A fixed matrix repeats fresh-session invocations across three synthetic members and two products, then exercises outcomes, recovery, simulated handoff, and a markup variant. A test-only fixture oracle checks zero irreversible commits; it is never available to the automation. Timings exclude browser startup and are not production reliability estimates.

Operator cancellation during a pending discovery request cancels the provider await and discards any late decision. It returns an explicit aborted result, rather than misclassifying cancellation as a provider or ownership failure. Provider errors persist only allowlisted status/code metadata; ambiguous HTTP 429 responses are not assumed to be transient. SDK retries are disabled so each recorded adapter call represents one attempt.

For this server-rendered profile, links and submit controls must complete navigation in their owning frame before recording an after-checkpoint, including same-URL redirects. Observation retries only known navigation-context races within a fixed deadline; it never re-clicks. Journal timestamps and workflow durations use distinct fields to preserve event ordering.

## Heterogeneity & multi-tenant

The surface seam is `observe`, `act`, `check`, and `read`; the flow records intent, references, and predicates rather than browser objects. The current adapter handles named frame chains and legacy table labels without relying on test IDs. It does not implement pixel-only controls or native desktop execution. Those require a second adapter with OS accessibility locators or reviewed visual anchors; a screenshot coordinate alone would need a stable anchor and context validation before being replayable.

For reuse, separate a vendor capability from institution configuration: entry origin, permitted routes/actions, credentials supplied at runtime, labels/frame mappings, and supported product versions. A future tenant overlay should be schema-validated, version-pinned, and reviewed; it must not silently weaken policy or change business semantics. Compatibility metadata is present but is not an implemented tenant registry. Unknown versions should undergo replay validation before approval. The Harbor fixture variant changes branding, transient field IDs, wrappers, and field order, while preserving semantic labels. The same artifact and policy replay without overrides. This is a controlled synthetic compatibility test, not independent or unseen-site generalization.

## Escalation & handoff

The control state is `automation → paused → human → automation`, or terminal `finished`. An async lock serializes actions and ownership transitions. An intervention carries the goal/capability context through the run, step, reason, expected checkpoint, and masked evidence. Claim and resume requests carry a generation number so a stale browser tab cannot resume a later intervention. The automation actor is rejected while a human owns the session.

The operator can use the console's live controls or the headed browser. Both operate the same page/context and cookies. A browser event listener records clicked/changed controls without field values. Return of control is not enough: replay validates the interrupted step's postcondition first, then its precondition, and stops on an unrelated state. Known scenario tests use a clearly labeled simulated operator through the same mechanism; this is distinct from evidence of a person physically operating the UI.

The console is intentionally local and single-operator. Production would need authenticated assignment, durable intervention storage, leases with fencing across workers, access-scoped screen streaming, and a recovery strategy for process/browser death. Cooperative direct browser use is assumed; the implementation is not an OS-level exclusive-input security boundary.

## Safety

Policy is trusted configuration independent of artifacts and model output. Before an action, the adapter resolves a unique visible control and inspects its actual name, type, link, and form destination. Exact origin/path checks cover redirects and requests; final `/commit` and its control are not allowed. Risky controls are blocked, not automatically approved by a model. Browser popups, downloads, service workers, and WebSockets are restricted. No credential-entry automation is implemented.

The model receives redacted visible observations and parameter names; private values are bound by the executor. Artifacts store references. Audit records contain structured metadata and short operational explanations, not model reasoning transcripts. Evidence masks declared private UI regions, input fields, and known private values, and avoids raw DOM dumps and trace archives that could capture credentials. Sensitive outputs are available to the caller in memory while saved results are redacted. Failed screenshot masking does not fall back to saving a raw screenshot.

These are scoped safeguards, not banking compliance. Redaction coverage depends on the target profile. A label allowlist does not prove arbitrary JavaScript is harmless, and allowed endpoints still need application-specific review. A real deployment requires approved model/data arrangements, network isolation, secrets management, retention/access policies, and adversarial testing. All included fixture data is synthetic.

Experiential documents default 30-day prompt/response capture for new Free organizations. Its ZDR-enforceable badge and our `store=False` do not guarantee gateway-wide zero retention. Only redacted synthetic observations are sent; billing, retention, and routing settings are not changed by Relay. Gateway keys are included in secret-pattern redaction and removed by the replay verification guard.

## Cuts

Implemented scope is one workflow, one browser adapter, local artifact storage, bounded recovery, a minimal real operator interface, and a callable local capability contract. Desktop execution, OCR/visual replay, a tenant registry, distributed infrastructure, persisted authenticated sessions, and unattended artifact approval are deliberately excluded. Replay never falls back to an LLM. An OpenAI API integration is available; whether a live run has actually been captured is reported in the evidence inventory, not inferred from its existence.

The two focused extensions are a multi-run stability harness and a controlled markup-variant check. Next priorities would be approval tied to an artifact digest, stronger redaction tests for additional surfaces, and one reviewed tenant override. Genuine seven-call discovery through Experiential's gateway completed with `gpt-5.6-luna`; its artifact passed 31 guarded model-free cases. Separate AI-operated and user-reported person-operated console handoffs passed with explicit attribution. A gateway-console key-check defect found during review was corrected with shared configuration validation and regression coverage; the latest suite passes 118 tests. See `evidence/README.md` for scope and evidence. Readiness checks establish consistency, not authenticity or overall readiness; publication remains a reviewed human decision.
