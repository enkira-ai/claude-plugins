---
name: epic-shepherd
description: Shepherd a whole GitHub Epic (issue with sub-issues) to completion. Phase 1 snapshots open sub-issues + blocked_by edges into a tier-ordered sequence JSON. Phase 2 (the autonomous loop) drives each ready issue → dispatches an implementer (rfc-loop / autopilot / inline) → polls for the opened PR → hands off to pr-shepherd to drain reviews + merge → regenerates the snapshot every tick so closed issues advance the frontier. Phase 3 (v0.3.0) writes a close-out report, opens a PR that squash-closes the epic, shepherds that PR to merge, and exits the loop. Triggers on "shepherd epic #N", "drive epic #N to completion", "snapshot epic #N's sequence", "/loop /epic-shepherd:shepherd <N>".
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
  └─ Phase 3: close-out  (v0.3.0, SHIPPED)
        verify all subs closed → compose docs/reports/<epic-closeout>.md →
        branch + commit + push + gh pr create ("Closes #<epic>") →
        record closeout_pr in state → on next tick hand off to
        pr-shepherd → on merge: epic auto-closes via "Closes #",
        loop exits (terminal).
```

`pr-shepherd` stays single-purpose (per-PR shepherd). `epic-shepherd` is the
new orchestration layer that *calls* it. They are independent plugins; install
both to use Phases 2 + 3 of this skill.

## When to invoke

- **Phase 1 (now, v0.1.0):**
  - "Snapshot epic #437's sequence", "show me what's actionable in epic #N"
  - `/epic-shepherd:extract 437` — write the state JSON to `/tmp/epic-shepherd-state-437.json`
  - Operator-facing: produces a tier-ranked list of currently-actionable
    sub-issues so a human (or a Phase-2 loop) can pick the next one to work on.
- **Phase 2 (roadmap):**
  - "Shepherd epic #437 to completion", "drive epic #437 autonomously"
  - `/loop /epic-shepherd:shepherd 437` — autonomous tick loop until epic closes
- **Phase 3 (v0.3.0):**
  - Auto-fires inside Phase 2 when the sequence empties + no in-flight PR +
    at least one completed sub-issue; not normally invoked directly. The
    `closeout.sh start|finalize|verify` helper is the operator-facing
    handle if the loop ever needs manual nudging.

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

   "CLOSEOUT_START" → invoke Phase 3 (v0.3.0). Run:
         scripts/closeout.sh start <epic>
       which verifies the rollup, composes the close-out report,
       branch/commit/push, opens the close-out PR ("Closes #<epic>"),
       and calls `state.sh mark-closeout-in-flight` to record it.
       On success → ScheduleWakeup 300s (let CI bots fire on the
                    newly-opened PR before SHEPHERD takes over).
       On failure → `state.sh pause <epic> "closeout start failed:
                    <reason>"` → EXIT.

   "CLOSEOUT_SHEPHERD <pr>" → same as SHEPHERD but the PR is the
       close-out report PR. Invoke `pr-shepherd:pr-shepherd <pr>`.
       On its return:
         MERGED   → run `closeout.sh finalize <epic>` (verifies the
                    epic auto-closed via "Closes #", falls back to
                    `gh issue close` if not, calls `state.sh
                    complete-closeout`). Loop EXITS — no reschedule.
                    Print "Epic #N complete, X PRs merged across Y
                    sub-issues."
         HARD STOP → `state.sh pause <epic> "<pr-shepherd hard stop
                    on closeout PR #N: <reason>>"` → EXIT.
         IN-FLIGHT → ScheduleWakeup 600s.

   "CLOSED" → terminal. Closeout already finalized. EXIT without
       reschedule. Loop is done.

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
| Sub-issue REOPENED mid-closeout (Phase 3) | `closeout.sh verify` (run manually); state must be paused + closeout PR closed before resuming |
| Closeout PR's CI / review hard-stops | pr-shepherd surfaces (same as a normal in-flight PR) |

### State file mutation contract

Phase 2 is the only writer that mutates `in_flight_pr`, `in_flight_issue`,
`completed`, and `paused`. The `sequence` field is rewritten only by
regenerating the snapshot (via Phase 1's `extract-sequence.py`) — never
mutated in place.

All mutation goes through `scripts/state.sh` (atomic-write via
flock + rename). Never write the state file directly — concurrent ticks
will race.

## Phase 3 — close-out (v0.3.0, SHIPPED)

Autonomous close-out. When Phase 2's tick sees `CLOSEOUT_START` (sequence
empty, no in-flight PR, no closeout PR, at least one completed sub-issue),
it hands off to `scripts/closeout.sh start <epic>`. Subsequent ticks
shepherd the close-out PR via `pr-shepherd:pr-shepherd`; on merge,
`closeout.sh finalize <epic>` finalizes and the loop exits.

### Per-tick flow

```
status = CLOSEOUT_START
  → scripts/closeout.sh start <epic>
        1. Verify GraphQL rollup: epic OPEN, ALL sub-issues CLOSED.
           Any open sub-issue → exit 2 (refuse to close out).
        2. Load completed list from state; for each entry with a PR
           number, fetch PR title + merge SHA + merged_at + top-5 files.
        3. Compose docs/reports/<UTC-date>-epic-<N>-closeout.md (heredoc
           template inline in the script; renderable under --dry-run).
        4. git checkout -b docs/epic-<N>-closeout; git add + commit + push.
        5. gh pr create with body "Closes #<epic>" + checklist of all
           completed sub-issues with their PR numbers.
        6. state.sh mark-closeout-in-flight <epic> <pr> <branch>.
        7. Print PR number to stdout.
  → ScheduleWakeup 300s (let CI bots fire before SHEPHERD)

status = CLOSEOUT_SHEPHERD <pr>
  → invoke pr-shepherd:pr-shepherd <pr> (same as SHEPHERD)
  → on MERGED:
        scripts/closeout.sh finalize <epic>
            1. Verify epic state == CLOSED (squash-merge of "Closes #N"
               should have auto-closed it).
            2. Fallback: gh issue close <epic> --reason completed if
               epic somehow still OPEN.
            3. state.sh complete-closeout <epic> <pr> — clears closeout_*
               slots, appends final entry to completed, sets closed_at.
        Print "Epic #N closed — X completed sub-issues (Y PRs merged),
        closeout PR #M". EXIT — no reschedule.
  → on HARD STOP: state.sh pause + EXIT
  → on IN-FLIGHT: ScheduleWakeup 600s

status = CLOSED → terminal. Tick exits without reschedule.
```

### Schema additions (v1.1 backward-compatible)

Two new nullable fields, no `schema_version` bump:

- `closeout_pr: int | null` — the close-out PR number once opened.
- `closeout_branch: str | null` — branch name (e.g. `docs/epic-437-closeout`).
  Useful for resuming a paused close-out.

Plus, set by `complete-closeout`:

- `closed_at: <ISO8601> | null` — non-null marks the epic terminal. The
  `status` subcommand returns `CLOSED` when this is set so the loop knows
  to exit.

Old v0.1/v0.2 state files load fine — all three default to `null` via
jq's `// null` defaulting.

### New `state.sh` subcommands

```bash
state.sh mark-closeout-in-flight <epic> <pr> <branch>  # set both slots
state.sh complete-closeout       <epic> <pr>           # clear + closed_at
```

### Phase 3 example

```
tick 1: status=CLOSEOUT_START
        closeout.sh start 437  → opens PR #999
        ScheduleWakeup 300s
tick 2: status=CLOSEOUT_SHEPHERD 999
        pr-shepherd #999 → IN-FLIGHT (CI still running)
        ScheduleWakeup 600s
tick 3: status=CLOSEOUT_SHEPHERD 999
        pr-shepherd #999 → MERGED
        closeout.sh finalize 437  → epic auto-closed, state cleared
        prints: "Epic #437 closed — 8 completed sub-issues (8 PRs merged),
                 closeout PR #999"
        EXIT (no reschedule)
```

### Hard stops specific to Phase 3

| Hard stop | Detected by | What to do |
|-----------|-------------|------------|
| Closeout-time rollup verify finds an OPEN sub-issue | `closeout.sh start` exits 2 | A sub-issue was reopened after the prior `state.sh complete` recorded it. Re-run `extract-sequence.py` to refresh the snapshot — Phase 2 will resume on the (now non-empty) sequence. |
| Closeout PR's CI / review fails | `pr-shepherd` surfaces | Same as a regular SHEPHERD hard stop. Operator fixes the PR; loop resumes on next tick. |
| Sub-issue reopened WHILE closeout PR is in flight | `closeout.sh verify` (run manually) | Pause the loop, close the closeout PR + delete the branch, re-extract, resume. |

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
