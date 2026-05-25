# epic-shepherd

Shepherd a whole **GitHub Epic** (issue with sub-issues) to completion. Snapshots the open sub-issue topology + `blocked_by` edges into a tier-ordered sequence, then on each tick (Phase 2, roadmap) dispatches an implementer for the next ready issue and hands the resulting PR to [`pr-shepherd`](../pr-shepherd) to merge.

Status: **v0.3.0** — Phase 1 + Phase 2 + Phase 3 shipped. The loop runs end-to-end and self-closes the epic when done.

## How it composes

```
epic-shepherd  (this plugin — issue-level orchestration)
  ↓ Phase 1 (v0.1.0)
  scripts/extract-sequence.py  →  tier-ordered JSON state file
  ↓ Phase 2 (v0.2.0)
  dispatch implementer:
    rfc-loop    (default — TDD, held-implementer subagent)
    autopilot   (lighter — mechanical ports)
    inline      (direct main-agent implementation)
  ↓ PR opens
  pr-shepherd:pr-shepherd <PR>   →   drain reviews + watch CI + merge
  ↓ PR merges → regenerate snapshot → frontier advances → next tick
  ↓ Phase 3 (v0.3.0)
  closeout.sh start  →  compose docs/reports/<date>-epic-<N>-closeout.md,
                        branch + commit + push, open PR ("Closes #<epic>")
  pr-shepherd:pr-shepherd <closeout-PR>  →  shepherd that PR to merge
  closeout.sh finalize  →  epic auto-closes, state cleared, loop EXITS
```

`pr-shepherd` stays single-purpose. `epic-shepherd` is the issue-level orchestration layer that *calls* it. Install both to use the full Phase 2 + 3 loop end-to-end.

## Phase 1: `extract-sequence` (shipped)

Snapshot job. Read-only against GitHub.

### Command

```
/epic-shepherd:extract <epic-number>
```

### Script

```bash
python3 plugins/epic-shepherd/skills/epic-shepherd/scripts/extract-sequence.py \
  --epic 437 \
  [--repo enkira-ai/cong] \
  [--out /tmp/epic-shepherd-state-437.json] \
  [--default-implementer rfc-loop|autopilot|inline]
```

Defaults: `--repo` auto-detected from cwd via `gh repo view`; `--out` defaults to `/tmp/epic-shepherd-state-<epic>.json`; `--default-implementer` defaults to `rfc-loop` (safer; enforces TDD).

Output is JSON (schema v1). Key fields:

- `sequence` — open sub-issues, sorted into tiers. Tier 1 = ready right now (zero open in-epic blockers). Tier 2 = blocked by tier 1. Etc.
- `completed` — closed sub-issues, audit-only.
- `paused` — set when the blocked-by graph has a cycle; operator must break it.
- `external_blockers_total` — count of blocker references outside this epic. Doesn't block sequencing; surfaced for operator awareness.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Sequence non-empty — state file written |
| `1` | No OPEN sub-issues — epic ready to close |
| `2` | Epic not found, or has no sub-issues at all |
| `3` | Topology has a cycle |
| `4` | Bad usage / `gh` not available / API failure |

### Example output (epic #437 in enkira-ai/cong)

```json
{
  "schema_version": 1,
  "epic": 437,
  "repo": "enkira-ai/cong",
  "sequence": [
    {"issue": 499, "tier": 1},
    {"issue": 500, "tier": 2, "blocked_by_in_epic": [499], "parallel_with": [514]},
    {"issue": 514, "tier": 2, "blocked_by_in_epic": [499], "parallel_with": [500]},
    {"issue": 501, "tier": 3, "blocked_by_in_epic": [499, 500]}
  ],
  "completed": [{"issue": 442}, {"issue": 445}, ...],
  "external_blockers_total": 0,
  "in_flight_pr": null,
  "in_flight_issue": null,
  "paused": null,
  "default_implementer": "rfc-loop"
}
```

## Phase 2: tick loop (v0.2.0, SHIPPED)

```
/loop /epic-shepherd:shepherd <epic-N>
```

Autonomous loop, self-paced via `ScheduleWakeup`. Each tick reads
`/tmp/epic-shepherd-state-<epic>.json`, decides one action, persists,
schedules the next wakeup (cache-friendly intervals — see SKILL.md), and
exits. The `/loop` harness re-fires the slash command on each wakeup.

Per-tick decision (from `scripts/state.sh status <epic>`):

| Status | Action |
|---|---|
| `PAUSED <reason>` | Surface, EXIT (no reschedule). Operator clears via `state.sh resume <epic>`. |
| `CLOSED` | Terminal — closeout PR has merged and the epic auto-closed. EXIT (no reschedule). |
| `CLOSEOUT_SHEPHERD <pr>` | Invoke `pr-shepherd:pr-shepherd <pr>` on the close-out PR. On MERGED → `closeout.sh finalize`, EXIT (no reschedule). On HARD STOP → `state.sh pause`, exit. On IN-FLIGHT → schedule 600s. |
| `SHEPHERD <pr> <issue>` | Invoke `pr-shepherd:pr-shepherd <pr>` skill. On MERGED → `state.sh complete`, regenerate snapshot, schedule 60s. On HARD STOP → `state.sh pause`, exit. On IN-FLIGHT → schedule 600s. |
| `DISPATCH <issue> <implementer> <tier>` | Dispatch implementer (rfc-loop / autopilot / inline). Poll for opened PR via `poll-for-pr.sh` (60s × 30 cap). On found → `state.sh mark-in-flight`, schedule 300s. On timeout → `state.sh pause`, exit. |
| `CLOSEOUT_START` | Phase 3 entry. Run `closeout.sh start <epic>` (verifies rollup → composes report → branch + commit + push → opens close-out PR with `Closes #<epic>` → `state.sh mark-closeout-in-flight`). Schedule 300s. |
| `MISSING` | Bootstrap: run extract-sequence.py, re-enter tick. |
| `IDLE` | Shouldn't happen after a Phase 1 run; surface + exit. |

### Hard stops that pause the loop

- Human `CHANGES_REQUESTED` on the in-flight PR (pr-shepherd surfaces)
- `mergeStateStatus=BLOCKED` (branch protection)
- Unresolvable merge conflict
- Review ping-pong > 3 rounds (pr-shepherd's cap)
- Implementer failed / no PR opened in 30 min
- In-flight PR closed without merge (operator action)
- Cycle in regenerated sequence (`extract-sequence` exit 3)
- Sub-issue REOPENED mid-closeout (Phase 3 — `closeout.sh verify` flags it)
- Close-out PR's CI / review hard-stops (same path as a regular SHEPHERD)

### State machine helpers

- `scripts/state.sh status|show|mark-in-flight|complete|pause|resume|mark-closeout-in-flight|complete-closeout` — atomic state I/O with flock + rename
- `scripts/poll-for-pr.sh <issue> [--once] [--interval] [--cap]` — read-only poll for an opened PR closing the given issue
- `scripts/extract-sequence.py` — re-run after every merge to refresh the sequence (in-flight + completed + paused preserved across regenerations)
- `scripts/closeout.sh start|finalize|verify` — Phase 3 orchestration (rollup verify → report Markdown → branch/commit/push → `gh pr create` with `Closes #<epic>` → state plumbing)

## Phase 3: close-out (v0.3.0, SHIPPED)

When the sequence empties + no in-flight PR + at least one completed sub-issue, the tick fires `closeout.sh start <epic>`:

1. **Verify rollup.** GraphQL: epic OPEN, every sub-issue CLOSED. Any open sub-issue → refuse (exit 2). A `--dry-run` flag skips this step so an operator can preview the report against a synthetic state file.
2. **Compose report.** `docs/reports/<UTC-date>-epic-<N>-closeout.md` — Markdown table of every completed sub-issue → its merged PR (with title, merge date, top-5 files touched) + a "what landed" bullet list. Template is a heredoc inline in `closeout.sh`.
3. **Branch + commit + push.** `docs/epic-<N>-closeout`; refuses to clobber if the branch already exists locally or upstream.
4. **Open the close-out PR.** `gh pr create` with body `Closes #<epic>` so the squash-merge auto-closes the epic + a checklist of every completed sub-issue with PR numbers.
5. **Record in state.** `state.sh mark-closeout-in-flight` — sets `closeout_pr` + `closeout_branch`.
6. **Subsequent ticks** see `CLOSEOUT_SHEPHERD <pr>` and hand the close-out PR to `pr-shepherd:pr-shepherd` like any other PR.
7. **On merge:** the squash-merge auto-closes the epic via `Closes #<epic>`. `closeout.sh finalize` verifies, falls back to `gh issue close` if somehow needed, then `state.sh complete-closeout` sets `closed_at` and clears the closeout slots. The loop exits — no further reschedule.

### Schema additions (v1.1 backward-compatible)

- `closeout_pr: int | null` — the close-out PR number once opened.
- `closeout_branch: str | null` — the branch name we created.
- `closed_at: <ISO8601> | null` — set when the loop finalizes; non-null makes `state.sh status` return `CLOSED`.

Old v0.1 / v0.2 state files load unchanged (all three default to `null` via jq's `// null`).

### Operator handle

If the loop ever stalls mid-closeout, `closeout.sh verify <epic>` reports the state-file contents alongside the live GitHub rollup and flags inconsistencies (e.g. a sub-issue reopened after the closeout PR was opened). Read-only; safe to run any time.

## DO / DO NOT (Phase 1)

### DO
- Re-run `extract-sequence` after every sub-issue closes to refresh the snapshot. The sequence is a *state machine*, not a one-shot plan.
- Trust the in-epic dep graph over operator intuition. The `blocked_by` edges are the contract.

### DO NOT
- **NEVER mutate GitHub from `extract-sequence`.** It is read-only by contract.
- **NEVER infer a sequence from labels or order-in-issue-body.** Use only `blocked_by` + sub-issue relationships.
- **NEVER assume an external blocker (issue outside this epic) blocks scheduling.** Just surface it.

## Related

- [`pr-shepherd`](../pr-shepherd) — drives a single PR to merge. Phase 2 of this skill delegates the merge step to it.
- [`rfc-loop`](../rfc-loop) — default implementer when Phase 2 dispatches a sub-issue.
- [`autopilot`](../autopilot) — lighter implementer; opens PRs + addresses feedback but stops at "ready to merge" (pr-shepherd handles from there).
