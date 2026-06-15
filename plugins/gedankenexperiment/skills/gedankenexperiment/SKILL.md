---
name: gedankenexperiment
description: Source-grounded scenario simulation and failure-mode synthesis. Use when asked to mentally simulate workflows, imagine realistic or adversarial scenarios, harden a system, find edge cases, audit state transitions, review call/chat/order/scheduling/payment/onboarding flows, or design durable fixes by tracing local code before implementation.
---

# Gedankenexperiment

## Overview

Use source-grounded mental simulation to find failures before patching. Scenarios are imagined; runtime behavior is not. Treat the local code as the physics of the system.

## Operating Rule

First mentally execute scenarios through the local code and collect failure modes. Then inspect the full failure set holistically and design durable invariant-level fixes. Implement only after that synthesis, and only when the user's task mode authorizes implementation.

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

## Workflow

### 1. Establish Source Of Truth

- Read applicable repository instructions.
- Inspect current git status and preserve unrelated dirty work.
- Identify the real runtime path, state owners, persistence boundaries, side-effect boundaries, and terminal states.
- Prefer local source code over docs. Use docs as intended behavior only after code behavior is clear.
- If code and docs disagree, report the drift explicitly.

### 2. Mentally Simulate Scenarios

Do not start by running the app, simulator, external workflows, deployments, or live systems unless the user explicitly asked for runtime execution. Read code and mentally step through realistic inputs, timing, retries, partial failures, and user behavior.

For each scenario, record:

- Scenario
- Expected behavior
- Actual local code path
- State before and after
- Failure mode or ambiguity
- Evidence with file/function references
- Severity

Cover normal, edge, adversarial, race, timeout, retry, partial-success, invalid-input, cancellation, interruption, and recovery cases appropriate to the domain.

### 3. Build A Failure-Mode Bank

Collect all confirmed and plausible failures before proposing fixes. Keep categories separate:

- Confirmed defects proven from local code
- Risky or unclear behavior
- Intentional behavior
- Unknowns requiring runtime evidence

Do not collapse distinct symptoms into one root cause until the code evidence supports it.

### 4. Synthesize Holistically

Review the whole bank together. Cluster failures by shared root cause and missing invariant. Do not fix failures one by one.

For each proposed fix, answer:

- Which failure modes does this cover?
- What invariant does it enforce?
- Where is the correct ownership boundary?
- Why is this not a band-aid?
- What existing logic does it replace or simplify?
- What tests prove the invariant rather than one transcript or example?
- Could it create duplicate state, duplicate validation, or a parallel implementation?

Prefer fixes that centralize ownership: reducers, validators, schemas, state machines, transition guards, idempotency controls, normalization boundaries, terminalization logic, or side-effect gates.

Reject fixes that add scenario-specific branches, patch one transcript, rely on prompts for code-owned invariants, duplicate state models, silently guess missing data, or make tests pass through exact phrasing.

### 5. Use Multiple Agents When Useful

For large systems, consider independent passes if subagents are available and the task scope justifies it. Keep the main agent responsible for reconciliation and evidence.

Useful roles:

- Runtime tracer: reconstruct the real code path and state owners.
- Scenario generator: produce realistic domain scenarios.
- Adversarial analyst: find races, retries, invalid transitions, and partial failures.
- Invariant synthesizer: cluster failures into shared root causes.
- Fix skeptic: reject band-aids, duplicate state, and fragile parallel logic.
- Test strategist: map invariants to focused tests.

Do not let subagents make findings authoritative without source references checked by the main agent.

### 6. Implement And Validate

If implementation is authorized, make the smallest durable change that fixes the broadest confirmed failure class. Preserve existing architecture and remove obsolete conflicting logic when needed.

Add or update tests at the real boundary where the invariant should hold. Distinguish unit-test evidence from integration, live-system, visual, audible, production, or end-to-end evidence.

Before completion, report:

- Scenario matrix
- Failure-mode bank
- Root-cause clusters
- Durable fix strategy
- Confirmed defects versus risks and unknowns
- Files changed
- Behavior changed
- Tests added or updated
- Tests run and results
- Remaining validation gaps
