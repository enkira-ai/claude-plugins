---
name: epic-shepherd
description: Shepherd a whole GitHub Epic (issue with sub-issues) to completion. Phase 1 snapshots open sub-issues + blocked_by edges into a tier-ordered sequence JSON. Phase 2 (the autonomous loop) drives each ready issue → dispatches an implementer (rfc-loop / autopilot / inline) → polls for the opened PR → hands off to pr-shepherd to drain reviews + merge → regenerates the snapshot every tick so closed issues advance the frontier. Phase 3 (roadmap) writes the epic close-out report and closes the epic. Triggers on "shepherd epic #N", "drive epic #N to completion", "snapshot epic #N's sequence", "/loop /epic-shepherd:shepherd <N>".
---

# Epic Shepherd — Drive a Whole Epic to Completion

Given a GitHub **Epic** (an issue with sub-issues), Epic Shepherd orchestrates the
issue → implementer → PR → pr-shepherd → merge → next-issue cycle until the
epic empties. It composes cleanly with the existing single-purpose skills:

```
epic-shepherd  (this skill — issue-level orchestration)
  ├─ Phase 1: extract-sequence
  │     scripts/extract-sequence.py  ←  snapshot ranked sub-issue topology
  │
  ├─ Phase 2: tick loop  (ROADMAP — v0.2)
  │     for each ready issue → dispatch implementer:
  │        rfc-loop:rfc-loop      (default — TDD, held-implementer subagent)
  │        autopilot:autopilot    (lighter — mechanical ports)
  │        inline                  (direct implementation in main agent)
  │     ↓ PR opens
  │     pr-shepherd:pr-shepherd <PR>  ←  drain reviews + watch CI + merge
  │     ↓ PR merges
  │     regenerate snapshot via Phase 1 → frontier advances → next tick
  │
  └─ Phase 3: close-out  (ROADMAP — v0.3)
        verify all subs closed → write docs/reports/<epic-closeout>.md →
        gh issue close <epic>
```

`pr-shepherd` stays single-purpose (per-PR shepherd). `epic-shepherd` is the
new orchestration layer that *calls* it. They are independent plugins; install
both to use Phase 2 + 3 of this skill once they ship.

## When to invoke

- **Phase 1 (now, v0.1.0):**
  - "Snapshot epic #437's sequence", "show me what's actionable in epic #N"
  - `/epic-shepherd:extract 437` — write the state JSON to `/tmp/epic-shepherd-state-437.json`
  - Operator-facing: produces a tier-ranked list of currently-actionable
    sub-issues so a human (or a Phase-2 loop) can pick the next one to work on.
- **Phase 2 (roadmap):**
  - "Shepherd epic #437 to completion", "drive epic #437 autonomously"
  - `/loop /epic-shepherd:shepherd 437` — autonomous tick loop until epic closes
- **Phase 3 (roadmap):**
  - Auto-fires inside Phase 2 when the sequence empties; not normally invoked
    directly.

## Phase 1 — extract-sequence (v0.1.0, SHIPPED)

The snapshot job. Read-only against GitHub. Produces a JSON state file that
Phase 2 will later consume.

### Invocation

```bash
python3 <skill-dir>/scripts/extract-sequence.py --epic <N>
    [--repo owner/name]                 # defaults to gh-detected from cwd
    [--out /tmp/epic-shepherd-state-<N>.json | -]   # '-' for stdout
    [--default-implementer rfc-loop|autopilot|inline]
```

The slash command `/epic-shepherd:extract <N>` is the canonical entry point.

### What it does

1. **List sub-issues.** GraphQL `subIssues(first:100)`. Split OPEN → goes into
   sequence; CLOSED → goes into `completed` (audit-only).
2. **Fetch `blocked_by` per OPEN sub-issue.** REST
   `/repos/<owner>/<repo>/issues/<N>/dependencies/blocked_by`. Split blockers
   into **in-epic** (also a sub-issue of this epic) vs **external** (not).
3. **Topologically tier.** Tier 1 = subs with zero open in-epic blockers
   (the *frontier* — start work here right now). Tier 2 = subs whose only
   blockers are in tier 1. Etc. Items sharing a tier are parallel-eligible.
4. **Emit JSON state file.** Schema v1 — see the script's docstring for the
   full shape. Key fields: `sequence` (tier-ranked), `completed`, `paused`,
   and the placeholder slots `in_flight_pr` / `in_flight_issue` that Phase 2
   will own.

### Exit codes

| Code | Meaning | What the caller does |
|------|---------|----------------------|
| `0`  | Sequence non-empty — state file written | Hand off to Phase 2 / operator |
| `1`  | No OPEN sub-issues — epic ready to close | Operator closes the epic (or Phase 3 does) |
| `2`  | Epic not found / has no sub-issues at all | Verify the issue number; if intentional, the epic doesn't need shepherding |
| `3`  | Topology has a cycle | Operator must break the cycle (an issue's blocked_by chain forms a loop) |
| `4`  | Bad usage / `gh` not available / API failure | Fix the invocation; install `gh`; re-auth |

A `paused: {reason, at}` block in the output is the structured form of
exit-code 3 — same information, surviving across tick boundaries.

### Snapshot semantics

The output is a *snapshot of the current state* — re-run after any sub-issue
closes to advance the frontier. Phase 2's tick loop calls this script on
every tick so the sequence stays in sync with reality (issues closed by other
agents, blockers cleared externally, new sub-issues filed mid-flight, etc.).

### Read-only contract

The script never mutates GitHub state — no issue closes, no PR opens, no
project-board flips. It is safe to run repeatedly with no side-effects beyond
overwriting the state file. Phase 2 owns all mutation.

## Phase 2 — tick loop (v0.2.0, SHIPPED)

Autonomous loop. Each tick decides one action based on persisted state.

### Invocation

```
/loop /epic-shepherd:shepherd <epic-N>
```

(Slash command is `/epic-shepherd:shepherd`; `/loop` is the harness that
re-fires self-paced via `ScheduleWakeup`. Omit `/loop` for a single tick.)

If the state file doesn't exist yet, the first tick bootstraps it by
running Phase 1 (`extract-sequence.py`). Subsequent ticks regenerate the
sequence portion of state after every merge so closed issues advance the
frontier; the persisted `in_flight_*`, `completed`, and `paused` fields
are preserved across regenerations.

### The tick — one decision per invocation

Read the current state, branch exactly once, persist, schedule wakeup
(or exit if terminal).

```
0. Load state. If state file missing → run extract-sequence (Phase 1)
   first, then re-enter the tick.

1. status = scripts/state.sh status <epic>

2. case status of:

   "PAUSED <reason>" → surface reason to operator, EXIT (no reschedule).
       Operator clears the pause via `scripts/state.sh resume <epic>`
       once they have fixed the cause.

   "SHEPHERD <pr> <issue>" → invoke `pr-shepherd:pr-shepherd` skill on
       <pr>. Wait for it to complete (pr-shepherd itself uses
       watch-pr.sh as observe-only CI poll). On its return:
         MERGED   → `state.sh complete <epic> <issue> <pr>`
                  → re-run extract-sequence.py to refresh the sequence
                    (preserves completed + paused; rebuilds sequence
                    from current GitHub state)
                  → ScheduleWakeup 60s (handoff to next item)
         HARD STOP (pr-shepherd surfaced and stopped) → `state.sh pause
                    <epic> "<pr-shepherd hard stop on PR #N: <reason>>"`
                  → EXIT (no reschedule)
         IN-FLIGHT (still draining / CI pending — pr-shepherd's
                    watch-pr.sh exited 6/timeout or 7/threads) →
                    ScheduleWakeup 600s (10 min — matches the watcher
                    cap; long enough to wait through a slow CI run but
                    not so long we burn cache for nothing)

   "DISPATCH <issue> <implementer> <tier>" → dispatch the implementer:
         rfc-loop  → invoke rfc-loop:rfc-loop skill, scoped to one
                     sub-issue (the LLM agent passes the sub-issue
                     context + epic context, lets rfc-loop's
                     held-implementer subagent do TDD)
         autopilot → invoke autopilot:autopilot skill once (the
                     mechanical-port path — autopilot opens the PR and
                     addresses feedback but stops at "ready to merge";
                     pr-shepherd takes over from there in step
                     SHEPHERD on the next tick)
         inline    → use the Agent tool with a focused implementer
                     prompt; only for trivial changes (≤50 LoC,
                     single-file). Anything substantive uses rfc-loop.
       After dispatch returns (PR opened OR a deterministic "no PR
       opened" signal), poll for the opened PR via:
         scripts/poll-for-pr.sh <issue> --interval 60 --cap 1800
       On found → `state.sh mark-in-flight <epic> <issue> <PR>`
                → ScheduleWakeup 300s (let CI bots fire so SHEPHERD
                  has something to drain on the next tick)
       On timeout → `state.sh pause <epic> "no PR opened for issue
                    #<issue> within 30 min — implementer dispatch
                    may have failed; check the implementer's run
                    artifacts"`
                  → EXIT (no reschedule)

   "CLOSEOUT" → invoke Phase 3 (roadmap — v0.3). Until v0.3 ships,
       surface a one-line "epic ready for close-out — run
       `gh issue close <epic> --reason completed` manually OR wait
       for Phase 3 v0.3" and EXIT.

   "IDLE" → no sequence, no completed work. This shouldn't happen after
       a successful Phase 1 run; surface and EXIT.

   "MISSING" → bootstrap: run extract-sequence.py, then re-enter the
       tick.

3. After the action, ScheduleWakeup as noted above. Pass back the EXACT
   same /loop input verbatim so the next firing re-enters the skill.
```

### Cache-friendly wakeup pacing

Per `/loop` skill's pacing guidance: the Anthropic prompt cache has a
5-minute TTL. Sleeping past 300s loses the cache. Phase-2 picks reflect
that:

- **60s** — after a merge (about to start next item; cache stays warm).
- **270s** — when actively draining reviews on a fast PR (under the
  5-min cache window).
- **300-600s** — pr-shepherd is in-flight with CI; expected delay is
  minutes, accept the cache miss.
- **1200s (20 min)** — long fallback when truly idle waiting on
  external state (e.g. a CI run that takes 30+ min).

### Implementer dispatch

| `implementer` | What it invokes | Best for |
|---------------|-----------------|----------|
| `rfc-loop` (default) | rfc-loop:rfc-loop skill, scoped to one sub-issue | Substantive work needing TDD + design discipline |
| `autopilot` | autopilot:autopilot skill — one pass | Mechanical ports, well-defined small changes |
| `inline` | Agent tool with focused implementer prompt | Trivial single-file changes (≤50 LoC) |

Each sequence item may override the default per-issue at extract time
or via post-extract hand-edit of the state JSON:
`{"issue": 500, "implementer": "autopilot"}`.

The default-implementer choice matters: **safer (rfc-loop) is the right
default** because the loop runs unattended — slow-but-correct beats
fast-but-needs-rework when nobody is watching.

### Hard stops that pause the loop

When any of these trip, the tick writes `paused: {reason, at}` to state
and exits without scheduling. The operator unblocks via
`state.sh resume <epic>` after fixing the cause.

| Hard stop | Source |
|-----------|--------|
| Human `CHANGES_REQUESTED` on the in-flight PR | pr-shepherd surfaces (Phase 1 §1.7) |
| `mergeStateStatus=BLOCKED` (branch protection unsatisfied) | pr-shepherd surfaces |
| Unresolvable merge conflict | pr-shepherd surfaces |
| Review ping-pong > 3 rounds | pr-shepherd surfaces |
| Implementer failed / no PR opened in 30 min | epic-shepherd, this skill |
| In-flight PR closed without merge (operator action) | epic-shepherd (detected on next SHEPHERD) |
| Cycle in regenerated sequence (rare — only if blocked-by edges change mid-run) | epic-shepherd (extract-sequence exits 3) |

### State file mutation contract

Phase 2 is the only writer that mutates `in_flight_pr`, `in_flight_issue`,
`completed`, and `paused`. The `sequence` field is rewritten only by
regenerating the snapshot (via Phase 1's `extract-sequence.py`) — never
mutated in place.

All mutation goes through `scripts/state.sh` (atomic-write via
flock + rename). Never write the state file directly — concurrent ticks
will race.

## Phase 3 — close-out (ROADMAP — v0.3)

When `sequence` is empty AND no `in_flight_pr`:

1. Verify every sub-issue closed via fresh GraphQL rollup.
2. Compose a close-out report at `docs/reports/<UTC-date>-epic-<N>-closeout.md`
   summarizing what landed (which sub-issues → which PRs → key files touched).
3. Open a PR for the report (delegate to `autopilot:autopilot` with a one-shot
   issue tied to the closeout).
4. Once report PR merges, `gh issue close <epic> --reason completed`.
5. Exit the loop (no further reschedule).

## DO / DO NOT

### DO
- Re-run `extract-sequence` after every sub-issue closes to refresh the
  snapshot. The sequence is a *state machine*, not a one-shot plan.
- Atomic-write the state file (tmp + rename) so a Phase-2 tick reading it
  mid-write never sees a partial JSON.
- Trust the in-epic dep graph over operator intuition. The blocked-by edges
  ARE the contract.
- Surface `external_blockers` even though they don't block sequencing — the
  operator may want to chase the external blocker out-of-band.

### DO NOT
- **NEVER mutate GitHub from `extract-sequence`.** It is read-only. All
  mutation lives in Phase 2 / Phase 3.
- **NEVER infer a sequence from labels or order-in-issue-body.** Use only the
  `blocked_by` edges + sub-issue relationships. Labels evolve; edges are the
  durable contract.
- **NEVER assume an external blocker (issue outside this epic) blocks
  scheduling.** Just surface it. Cross-epic chase is operator-driven.

## When stuck

1. `gh: command not found` → install `gh` (https://cli.github.com/) and
   `gh auth login`.
2. Exit code 2 (epic not found / no sub-issues) → verify with
   `gh issue view <N> --json subIssues` that the issue actually has sub-issues
   wired (the GitHub UI's "Convert to issue" doesn't add sub-issue edges).
3. Exit code 3 (cycle) → run
   `gh api repos/<owner>/<repo>/issues/<N>/dependencies/blocked_by` for each
   sub-issue in the `paused.reason` list; one of them has a backward edge that
   needs deleting via `DELETE
   /repos/<owner>/<repo>/issues/<N>/dependencies/blocked_by/<M>`.
4. Sequence is non-empty but every item has `external_blockers` → none are
   actionable right now; chase the external blockers or treat the snapshot as
   informational only.

## Related plugins

- **pr-shepherd** — drives an individual open PR to merge. Phase 2 of this
  skill delegates the merge step to it.
- **rfc-loop** — default implementer when Phase 2 dispatches a sub-issue;
  enforces TDD via a held-implementer subagent.
- **autopilot** — lighter alternative implementer; opens a PR + addresses
  feedback but stops at "ready to merge" (pr-shepherd handles from there).
- **codex-review** — fresh-context second-opinion review on a PR; Phase 2 may
  invoke it as part of drain when bot review surface is shallow.
