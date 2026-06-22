---
name: gedankenexperiment
description: "Use when asked to mentally simulate workflows, imagine realistic or adversarial scenarios, harden a system, find edge cases, audit state transitions or externally observable outputs, review call/chat/order/scheduling/payment/onboarding flows, design durable fixes, trace downstream repercussions and blast radius of proposed fixes through local code before implementation, or decide what to do after a mental simulation report."
---

# Gedankenexperiment

## Overview

Use source-grounded mental simulation to find failures before patching. Scenarios are imagined; runtime behavior is not. Treat the local code as the physics of the system.

## Operating Rule

First mentally execute scenarios through the local code and collect failure modes. Then inspect the full failure set holistically and design durable invariant-level fixes. Implement only after that synthesis, and only when the user's task mode authorizes implementation.

Every proposed fix must also be simulated as a new system behavior before implementation. If a fix changes or reinterprets state, statuses, enum values, API payloads, events, cache behavior, persistence, terminal semantics, permissions, timing, or UI-visible meaning, trace its downstream producers and consumers before accepting it.

Internal availability is not delivery. For every scenario with a user, operator, API client, external service, scheduled job, or downstream consumer, trace what that receiver actually observes. A field, policy, prompt instruction, config value, cached value, background context, or database row is not externally delivered unless local code proves it crosses the relevant output boundary.

Every run ends with the [Final Report](#final-report-required-every-run): a single PASS/FAIL verdict, the issues identified, and a fixes rubric that maps each fix to the simulation issues it resolves. The report is required on every run, including analysis-only mode and runs where no fix is implemented. After the report, present [Next Step Options](#next-step-options-required-after-the-final-report) so the human can choose the next phase without losing the report's phase boundary.

## Example Invocations

This skill triggers automatically when the task matches its description. To invoke it explicitly, describe the task in natural language (or run `/gedankenexperiment:gedankenexperiment`). Use one of these prompt shapes:

```text
Run a gedankenexperiment on the Vocce outbound patient survey call flow. Local code is the source of truth. First mentally simulate scenarios and collect failure modes, then synthesize durable fixes.
```

```text
Gedankenexperiment on Panbot call conversation hardening. Trace the local runtime flow, build a failure-mode bank for realistic order scenarios, and only then propose invariant-level fixes.
```

```text
Gedankenexperiment in analysis-only mode on this checkout's payment retry flow. Do not modify code. Produce the scenario matrix, failure-mode bank, root-cause clusters, and durable fix strategy.
```

```text
Gedankenexperiment to harden the onboarding workflow. If implementation is authorized by this prompt, fix only confirmed shared root causes after the mental simulation and synthesis phases.
```

For best results, name the project, workflow, task mode, source-of-truth boundary, and any hard safety limits such as no live calls, no production changes, or analysis only.

## Long Runs

For any run that may exceed one focused turn, create and maintain a durable ledger. Do not rely on chat context as the source of truth.

Default paths:

- Use `.local/gedankenexperiment/YYYY-MM-DD-topic.md` for local, uncommitted working memory.
- Use `docs/gedankenexperiment/YYYY-MM-DD-topic.md` only when the user wants a committed/shared artifact.

Keep an `Active Context` section at the top with:

- Current phase
- Latest task-mode boundary
- Source files inspected
- Key state owners and invariants found
- Next action
- Explicit non-goals and safety limits

Use stable IDs throughout:

- `SCN-001` for scenarios
- `FM-001` for failure modes
- `RC-001` for root-cause clusters
- `INV-001` for invariants
- `FIX-001` for fix strategies
- `OUT-001` for externally observable output traces
- `CC-001` for changed contracts introduced or reinterpreted by fixes
- `FIFM-001` for fix-induced failure modes
- `TST-001` for tests

Update the ledger after each phase and before any long pause. Preserve traceability, for example: `FIX-001 enforces INV-001 and covers FM-003, FM-007, FM-011`.

When resuming, read the ledger first, verify current git status and relevant file drift, then continue from the recorded `Next action`. If the ledger and local code disagree, local code wins and the ledger must be corrected before proceeding.

## Workflow

### 1. Establish Source Of Truth

- Read applicable repository instructions.
- Inspect current git status and preserve unrelated dirty work.
- Identify the real runtime path, state owners, persistence boundaries, side-effect boundaries, and terminal states.
- Identify externally observable output boundaries: API responses, UI render state, spoken/audio output, chat/email/SMS content, webhook/event payloads, files/exports, notifications, terminal statuses, logs or monitoring status intended for operators, and any other receiver-facing artifact.
- Prefer local source code over docs. Use docs as intended behavior only after code behavior is clear.
- If code and docs disagree, report the drift explicitly.
- For long runs, create or resume the durable ledger before deep analysis.

### 2. Generate Code-Informed Scenarios

Before mentally executing scenarios, generate the scenario set from how the system is actually built and used.

Use repository context to understand the domain and architecture:

- Read `AGENTS.md`, `CLAUDE.md`, or equivalent repo instructions when present.
- Skim architecture docs, runbooks, API docs, product docs, tests, fixtures, and workflow docs that are directly relevant.
- Inspect entrypoints, routers/controllers, state-machine or reducer modules, background jobs, model/prompt boundaries, persistence models, and tests to infer real usage paths.
- Identify actors, external systems, normal flows, exceptional flows, terminal outcomes, retries, cancellations, permissions, and safety constraints.

Then create a scenario inventory before tracing:

- Happy-path scenarios that prove the expected workflow.
- Realistic user/operator/system behavior based on product usage.
- Edge cases from state boundaries, required fields, ordering, concurrency, retries, and partial completion.
- Adversarial or messy inputs the current architecture is likely to encounter.
- Failure-prone handoffs between modules, queues, callbacks, models, databases, external APIs, and UI/runtime layers.
- Scenarios already implied by tests, TODOs, comments, bug reports, docs drift, or recent changes.

Every scenario must be plausible for this local system. Do not import assumptions from another project. If a scenario comes from docs or intuition, mark it as a candidate until local code confirms the path exists.

For each generated scenario, assign an ID and record:

- `SCN-*` ID and short title
- User/system story
- Why this scenario is realistic for this codebase
- Entry point and expected runtime path
- Main state or invariant under pressure
- Expected terminal outcome

### 3. Mentally Simulate Scenarios

Do not start by running the app, simulator, external workflows, deployments, or live systems unless the user explicitly asked for runtime execution.

Imagine the scenario, but execute the system in your head from the local code. Walk the scenario step by step through the actual functions, calls, callbacks, reducers, state writes, validations, side effects, output selection, and terminal paths. The imagined part is the input sequence and timing; the system behavior must come from source code.

Use cause-and-effect reasoning:

```text
The user/system does X.
That enters function A with state S0.
Function A calls B with payload P.
B normalizes/validates/mutates this into S1.
Because S1 has property Y, C chooses branch Z.
That persists/emits/calls D.
Now the next event arrives, and the code resumes at E.
Therefore the final state is S2, which is correct/incorrect because...
```

Do not stop at "scenario might fail." Continue the mental trace until the workflow reaches a stable state, terminal state, explicit blocker, or contradiction. If the trace crosses async boundaries, queues, model outputs, callbacks, database writes, retries, or external side-effect wrappers, include those handoffs.

For each scenario, build an observable output trace before judging pass/fail:

- Assign `OUT-*` IDs to receiver-facing artifacts that matter to the scenario.
- Trace source fields or policies -> transformation/selection owner -> output boundary -> actual emitted value or state.
- Include the first observable output after major gates, handoffs, and accepted actions.
- Mark internal-only material as not delivered until code proves it reaches the output boundary.
- Treat "available internally but absent from required observable output" as a defect or explicit risk when it affects comprehension, correctness, safety, status, validation, or next-step behavior.

For each scenario, record:

- Scenario
- Expected behavior
- Step-by-step local code path
- State before, intermediate state, and final state
- Function calls and branch decisions that matter
- Persistence, emitted events, external calls, or terminalization
- Observable output trace, including intended-but-missing output fields or policies
- Failure mode or ambiguity
- Evidence with file/function references
- Severity

Use the generated scenario inventory as the input set. Add more scenarios during tracing only when the code reveals a missing realistic branch.

### 4. Build A Failure-Mode Bank

Collect all confirmed and plausible failures before proposing fixes. Keep categories separate:

- Confirmed defects proven from local code
- Observable-output defects where the correct source field, state, policy, or instruction exists internally but does not reach the receiver-facing boundary
- Risky or unclear behavior
- Intentional behavior
- Unknowns requiring runtime evidence

Do not collapse distinct symptoms into one root cause until the code evidence supports it.

### 5. Synthesize Holistically

Review the whole bank together. Cluster failures by shared root cause and missing invariant. Do not fix failures one by one.

For each proposed fix, answer:

- Which failure modes does this cover?
- What invariant does it enforce?
- Where is the correct ownership boundary?
- Which observable output boundary should own the receiver-facing value, and what test proves the emitted artifact rather than merely proving internal context exists?
- Why is this not a band-aid?
- What existing logic does it replace or simplify?
- What tests prove the invariant rather than one transcript or example?
- Could it create duplicate state, duplicate validation, or a parallel implementation?

Prefer fixes that centralize ownership: reducers, validators, schemas, state machines, transition guards, idempotency controls, normalization boundaries, terminalization logic, or side-effect gates.

Reject fixes that add scenario-specific branches, patch one transcript, rely on prompts for code-owned invariants, duplicate state models, silently guess missing data, or make tests pass through exact phrasing.

### 6. Simulate Proposed Fix Repercussions

Treat each proposed `FIX-*` as a new scenario input, not as the end of the analysis. The fix is not acceptable until its repercussions are traced through the local code.

Run this phase for every fix. It is mandatory when a fix touches or changes any of these contract surfaces:

- State-machine transitions, terminal states, status sets, enum values, or persisted fields.
- API request or response payloads, schema names, display outcomes, error codes, or fallback behavior.
- Events, queues, webhooks, realtime messages, cache keys, cache invalidation, retries, or polling.
- Permission, tenant, PHI/logging, audit, rate-limit, or auth boundaries.
- Externally observable content or state: UI-visible labels, spoken/audio text, chat/email/SMS bodies, files/exports, notifications, operator logs, filters, counts, sorting, grouping, badges, disabled states, or empty states.
- External provider assumptions, timeout behavior, idempotency, ordering, or concurrency.

For each changed or reinterpreted contract, assign `CC-*` and record:

- Producer and ownership boundary.
- Persistence or transport boundary.
- Observable output boundary and actual receiver-facing value.
- Backend aggregators, normalizers, validators, and side-effect emitters.
- API schemas and compatibility expectations.
- Realtime, cache, polling, retry, and fallback consumers.
- Frontend renderers, parsers, filters, sorters, counters, and copy.
- Tenant, permission, PHI/logging, and audit implications.
- Tests and docs needed to prove and explain the contract.

For each downstream surface, ask:

- What breaks if the new value or meaning arrives here today?
- Does the existing code fail closed, mislabel, silently coerce, loop forever, over-count, under-count, leak data, or hide work?
- Is this surface intentionally unaffected, and what source search or trace proves that no-impact claim?

Record new issues as `FIFM-*` fix-induced failure modes. Do not merge them into earlier `FM-*` items unless the same root cause and evidence genuinely cover both. If a fix changes user-visible, API, persisted, event, cache, or status semantics, the final report must include a changed-contract inventory and consumer blast-radius matrix.

### 7. Evidence And Scope Gate

Before posting the Final Report, run this gate. Do not treat a report as complete until every item is satisfied or explicitly downgraded to an unknown.

1. **Main-agent evidence only**
   - Any finding, no-impact claim, or blast-radius claim derived from a subagent must be re-verified by the main agent with direct file/function/search evidence.
   - Do not cite "Agent A/B/C trace" as final evidence. Replace it with concrete code references or mark the item as unverified.

2. **Scenario matrix completeness**
   - Every report must include a scenario coverage table, even when the causal trace is obvious.
   - Each scenario must map to at least one `OUT-*`, `FM-*`, or `FIX-*`, or be explicitly marked as a no-finding scenario.

3. **Fix scope classification**
   - Classify every proposed fix as one of:
     - `Required for reported defect`
     - `Required to prevent fix-induced failure`
     - `Architectural hardening`
     - `Separate follow-up`
   - Do not recommend bundling hardening fixes with the reported-defect fix unless omitting them creates a confirmed regression or fix-induced failure.

4. **No-impact evidence floor**
   - "Unaffected" claims require direct evidence: `rg` result, caller trace, schema/API boundary trace, or a specific reason the surface cannot consume the changed contract.
   - If direct evidence is missing, downgrade the claim to `Unknown` and list the validation needed.

5. **Implementation readiness**
   - A fix is implementation-ready only when all confirmed defects are mapped to fixes, all changed contracts have consumer coverage, and every no-impact claim meets the evidence floor.

### 8. Post The Mental Simulation Report

Before implementation, or before stopping in analysis-only mode, post a compact but complete report. This is a required phase gate, not an optional summary.

The report must include:

- Verdict: `PASS`, `FAIL`, or `PASS WITH RISKS`.
- Verdict reason: one or two sentences grounded in the scenario matrix and failure bank.
- Scenario coverage: a table of scenario IDs, outcome, severity, and linked failure IDs.
- Observable output trace: a table of `OUT-*` items mapping source fields or policies to the actual output boundary and emitted value or missing output.
- Issues identified: a table of `FM-*` items with status, severity, evidence, and whether each is a confirmed defect, risk, intentional behavior, or unknown.
- Root-cause clusters: `RC-*` items mapped to the failure modes they explain.
- Fixes rubric: `FIX-*` items mapped to the exact `SCN-*` and `FM-*` items they address.
- Changed contract inventory: `CC-*` items created or reinterpreted by proposed fixes.
- Consumer blast-radius matrix: downstream producers/consumers affected by each `CC-*`.
- Fix-induced failure modes: `FIFM-*` items found by simulating the fixes themselves.
- No-impact claims: surfaces intentionally unaffected, with search or trace evidence.
- Non-fixes rejected: notable tempting fixes rejected as band-aids, with reason.
- Validation plan: `TST-*` or runtime checks mapped to the invariant and failure mode they prove.
- Remaining unknowns: evidence that cannot be obtained from mental simulation alone.

Use the [Final Report](#final-report-required-every-run) format below. Do not omit scenario outcomes, observable output traces, fixes, changed contracts, consumer blast radius, no-impact claims, rejected non-fixes, validation, or unknowns.

Verdict rules:

- `FAIL`: at least one confirmed defect or high-severity unresolved risk in the simulated flow.
- `PASS WITH RISKS`: no confirmed defect, but meaningful unknowns or medium/high risks remain.
- `PASS`: all simulated scenarios meet intended behavior, with no material unresolved risks.

The fixes rubric is mandatory even in analysis-only mode. If no fix is needed, include `FIX-000: no code change` and explain why.

### 9. Use Multiple Agents When Useful

For large systems, consider independent passes if subagents are available and the task scope justifies it. Keep the main agent responsible for reconciliation and evidence.

Useful roles:

- Runtime tracer: reconstruct the real code path and state owners.
- Scenario generator: produce realistic domain scenarios.
- Adversarial analyst: find races, retries, invalid transitions, and partial failures.
- Invariant synthesizer: cluster failures into shared root causes.
- Fix skeptic: reject band-aids, duplicate state, and fragile parallel logic.
- Test strategist: map invariants to focused tests.

Do not let subagents make findings authoritative without source references checked by the main agent.

### 10. Implement And Validate

If implementation is authorized, make the smallest durable change that fixes the broadest confirmed failure class. Preserve existing architecture and remove obsolete conflicting logic when needed.

Add or update tests at the real boundary where the invariant should hold. Distinguish unit-test evidence from integration, live-system, visual, audible, production, or end-to-end evidence.

### 11. Report

Always finish by posting the [Final Report](#final-report-required-every-run) below, whether or not any code was changed. In analysis-only mode the Implementation Appendix is omitted; otherwise it is filled in. Then append the [Next Step Options](#next-step-options-required-after-the-final-report).

## Final Report (Required Every Run)

Post this report in the chat at the end of the simulation and synthesis phases, even in analysis-only mode and even when no fix is implemented. For long runs, also append it to the ledger. Use these sections in order.

### Verdict

State a single `PASS` or `FAIL` for the simulated flow, with a one-line justification.

- `FAIL` if the failure-mode bank contains one or more **confirmed defects** proven from local code.
- `FAIL` if a required externally observable output is absent, truncated, stale, misclassified, or misleading and local code proves the receiver would see that bad output.
- `PASS` only if there are zero confirmed defects. Name any residual risks or unknowns that keep the pass conditional.
- Report the count of confirmed defects and the highest severity among them, for example: `FAIL - 3 confirmed defects, max severity High`.

### Observable Output Trace

List every receiver-facing artifact that matters to the simulated scenarios. Do not count data as delivered merely because it exists in a prompt, config, cache, database row, background context, or internal state.

| ID | Scenario | Receiver / Boundary | Source Field or Policy | Actual Output | Finding |
| --- | --- | --- | --- | --- | --- |
| OUT-001 | SCN-001 | API response / `router.py::handler` | `model.status` | `{"status":"running"}` | correct |

### Issues Identified

Summarize the failure-mode bank, one row per issue. Keep the categories from step 4 distinct (confirmed defect, risk, intentional, unknown) - do not collapse them.

| ID | Status | Severity | Evidence (file/function) | Summary |
| --- | --- | --- | --- | --- |
| FM-001 | Confirmed defect | High | `file.py::fn` | ... |

### Fixes Rubric

Score every proposed fix against the rubric and make the issue mapping explicit. **Each confirmed defect must be covered by at least one fix, or marked won't-fix with a reason - no confirmed defect may be left unmapped.**

| Fix | Scope classification | Covers (FM / SCN) | Enforces (INV) | Ownership boundary | Not a band-aid (why) | Replaces / simplifies | Proof test (TST) | Duplicate-state risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FIX-001 | Required for reported defect | FM-001, FM-007 | INV-001 | reducer | ... | ... | TST-001 | none |

A fix passes the rubric only when every column is satisfied. Do not list as a chosen fix any candidate that adds scenario-specific branches, patches one transcript, relies on prompts for code-owned invariants, duplicates state, guesses missing data, or makes tests pass through exact phrasing.

End the rubric with a coverage line that ties fixes back to the issues, for example: `Coverage: FM-001..FM-008 all mapped; FM-005 won't-fix (needs runtime evidence)`.

### Changed Contract Inventory

List every `CC-*` state, status, enum value, API payload, event, cache behavior, persisted meaning, terminal semantic, permission rule, timing behavior, or UI-visible meaning introduced or reinterpreted by the proposed fixes.

| Contract | Introduced/Reinterpreted By | Producer/Owner | Consumers | Required Handling |
| --- | --- | --- | --- | --- |
| CC-001 | FIX-001 | `file.py::owner` | API, UI, cache, realtime | ... |

If no contracts changed, write `CC-000: no contract changes` and include source-search evidence.

### Consumer Blast-radius Matrix

Trace each changed contract through downstream consumers. Include backend and frontend surfaces that aggregate, normalize, validate, render, filter, sort, count, poll, subscribe, cache, retry, authorize, or log the new behavior.

| Contract | Surface | Current Behavior | Required Behavior | Evidence |
| --- | --- | --- | --- | --- |
| CC-001 | `frontend/file.tsx` | ... | ... | `rg`, code trace |

### Fix-induced Failure Modes

List failures discovered by simulating the proposed fixes themselves.

| Issue | Caused By Fix | Classification | Severity | Evidence | Disposition |
| --- | --- | --- | --- | --- | --- |
| FIFM-001 | FIX-001 / CC-001 | Confirmed defect | High | ... | covered by FIX-002 |

### No-impact Claims

For every plausible downstream surface that does not need a change, state the no-impact claim and the source-search or code-trace evidence. Do not omit a surface merely because it feels unrelated.

| Surface | Claim | Evidence |
| --- | --- | --- |
| `service/file.py` | unaffected because ... | `rg` found no consumer; code path uses separate enum |

### Implementation Appendix (only when code was changed)

Include only when implementation was authorized and performed:

- Files changed
- Behavior changed
- Tests added or updated, mapped to TST IDs
- Tests run and results, with red/green evidence
- Evidence type (unit versus integration, live-system, visual, audible, production, or end-to-end)
- Remaining validation gaps

## Next Step Options (Required After The Final Report)

After posting the Final Report, offer a stable decision menu. This menu is a phase handoff, not part of the verdict, and it does not authorize code changes by itself. Preserve task-mode boundaries: if the report was analysis-only, implementation still requires the human to choose an implementation option or give explicit implementation authorization.

Use the stable option labels below. Do not replace them with report-specific labels such as `Fix contract first`, `Harden recovery identity`, or `Documentation-only phase`. Put report-specific guidance inside the rationale and prompt body for the appropriate stable option.

Use native choice/question UI when the current runtime exposes it in the current session and mode. In Claude Code, use the native multiple-choice question tool if available. In Codex, use the native choice/request-user-input tool if available. If native choice UI is unavailable, limited, or would hide the exact prompt text, render the Markdown fallback list. Never claim choices are clickable unless the runtime actually rendered native choices.

Always make the exact prompt text visible either inside the native choice body or immediately next to the fallback option. The human must be able to inspect what choosing the option will ask the next agent to do.

### Menu Composition

- If the report found confirmed defects or material risks and there is not yet an approved implementation plan, show: `Write implementation plan`, `Deepen analysis`, `Request independent review`, and `Stop at report`.
- If an approved implementation plan already exists, or the human explicitly authorized code changes in the current prompt, also show `Implement approved plan`.
- If the report is `PASS` with no material risks, show `Stop at report` first and include only options that still make sense.
- If a native choice UI supports fewer than all relevant options, prioritize `Write implementation plan`, `Deepen analysis`, and `Stop at report` unless an approved plan already exists; in that case include `Implement approved plan` instead of `Deepen analysis`.

### Stable Options

1. **Write implementation plan** - recommended when the report found confirmed defects or risks and there is not yet an approved plan. Use the rationale line to name the highest-priority `FIX-*`, `CC-*`, `FIFM-*`, or `TST-*` IDs.
   ```text
   Use the gedankenexperiment report above as the source of truth. Use superpowers:writing-plans if available. Write an implementation plan that preserves every FIX-*, CC-*, FIFM-*, and TST-* ID, covers downstream consumers and no-impact claims, and stops before modifying code.
   ```

2. **Deepen analysis** - use when the report has important unknowns, thin evidence, or a risky `FIX-*`. Replace the bracketed placeholder with the specific IDs or uncertainty pockets from the report.
   ```text
   Run another gedankenexperiment pass on the report above, focused on [FM/FIX/CC/unknown IDs]. Do not modify code. Expand scenarios, downstream consumers, no-impact evidence, and validation requirements.
   ```

3. **Request independent review** - use before implementation when the fix strategy is high-risk, cross-module, or likely to have hidden downstream impact. Name the report's riskiest root-cause, contract, and no-impact claims in the rationale.
   ```text
   Review the gedankenexperiment report and proposed plan independently. Challenge the root-cause clusters, FIX-* coverage, CC-* blast radius, FIFM-* handling, no-impact claims, and validation plan. Do not modify code. End with Review Follow-up Options.
   ```

4. **Implement approved plan** - use only when a concrete implementation plan already exists, or the human explicitly authorized implementation in the current prompt.
   ```text
   Implement the approved plan using superpowers:executing-plans or superpowers:subagent-driven-development if available. Preserve the gedankenexperiment IDs in commits/tests. Stop and report if implementation reveals a new changed contract, downstream consumer, or fix-induced failure mode not covered by the plan.
   ```

5. **Stop at report** - use when the human only wanted analysis or wants to decide later.
   ```text
   Stop here. Treat the gedankenexperiment report as the current artifact of record.
   ```

### Fallback Rendering Rules

When rendering Markdown fallback, use this shape so Codex and Claude outputs stay aligned:

````markdown
### Next Step Options

1. **Write implementation plan** - recommended because [report-specific reason].
   ```text
   [exact prompt]
   ```
2. **Deepen analysis** - use if [report-specific uncertainty].
   ```text
   [exact prompt]
   ```
3. **Request independent review** - use if [report-specific review risk].
   ```text
   [exact prompt]
   ```
4. **Implement approved plan** - include only when an approved plan exists or implementation was explicitly authorized.
   ```text
   [exact prompt]
   ```
5. **Stop at report** - no further action now.
   ```text
   Stop here. Treat the gedankenexperiment report as the current artifact of record.
   ```
````

## Review Follow-up Options (Required After Independent Review)

When the current task is an independent review of a gedankenexperiment report, proposed plan, or fix strategy, do not end with only recommendations. After the review findings, present a stable follow-up decision menu using the same native choice/question UI rules from Next Step Options. If native UI is unavailable, use Markdown fallback.

Use these stable labels. Put review-specific findings in the rationale or prompt body, not in the option label.

1. **Write revised implementation plan** - recommended when the review found blockers, ambiguity, missing downstream coverage, or test gaps in the current plan.
   ```text
   Write a revised implementation plan using the gedankenexperiment report and independent review above as sources of truth. Use superpowers:writing-plans if available. Preserve every relevant FIX-*, CC-*, FIFM-*, TST-*, and review finding. Resolve the review blockers explicitly, cover downstream consumers and no-impact claims, and stop before modifying code.
   ```

2. **Deepen analysis** - use when the review exposed unresolved evidence gaps or uncertainty that should be traced before planning.
   ```text
   Run a focused gedankenexperiment pass on the review findings above, especially [review finding / FM / FIX / CC IDs]. Do not modify code. Expand the scenario traces, changed contracts, downstream consumers, no-impact evidence, and validation requirements.
   ```

3. **Request another independent review** - use when the review and original report conflict, or the remaining risk is cross-module/high-severity enough to merit a second read.
   ```text
   Independently review the gedankenexperiment report, current plan, and prior independent review. Focus on conflicts, unsupported assumptions, changed-contract coverage, fix-induced failure modes, and validation gaps. Do not modify code.
   ```

4. **Implement approved revised plan** - use only when a revised plan already exists and the human explicitly wants code changes now.
   ```text
   Implement the approved revised plan using superpowers:executing-plans or superpowers:subagent-driven-development if available. Preserve gedankenexperiment and review IDs in commits/tests. Stop and report if implementation reveals a new changed contract, downstream consumer, or fix-induced failure mode not covered by the plan.
   ```

5. **Stop at review** - use when the human wanted an independent read only or wants to decide later.
   ```text
   Stop here. Treat the gedankenexperiment report and independent review as the current artifacts of record.
   ```
