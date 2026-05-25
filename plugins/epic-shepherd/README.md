# epic-shepherd

Shepherd a whole **GitHub Epic** (issue with sub-issues) to completion. Snapshots the open sub-issue topology + `blocked_by` edges into a tier-ordered sequence, then on each tick (Phase 2, roadmap) dispatches an implementer for the next ready issue and hands the resulting PR to [`pr-shepherd`](../pr-shepherd) to merge.

Status: **v0.1.0** — Phase 1 only. Phase 2 (tick loop) + Phase 3 (close-out) on the roadmap. Phase 1 alone is already useful: it tells an operator (or an outer agent) what's actually actionable in a noisy epic.

## How it composes

```
epic-shepherd  (this plugin — issue-level orchestration)
  ↓ Phase 1
  scripts/extract-sequence.py  →  tier-ordered JSON state file
  ↓ Phase 2 (roadmap — v0.2)
  dispatch implementer:
    rfc-loop    (default — TDD, held-implementer subagent)
    autopilot   (lighter — mechanical ports)
    inline      (direct main-agent implementation)
  ↓ PR opens
  pr-shepherd:pr-shepherd <PR>   →   drain reviews + watch CI + merge
  ↓ PR merges → regenerate snapshot → frontier advances → next tick
  ↓ Phase 3 (roadmap — v0.3)
  write close-out report, gh issue close <epic>
```

`pr-shepherd` stays single-purpose. `epic-shepherd` is the issue-level orchestration layer that *calls* it. Install both to use the full Phase 2 loop once it ships.

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

## Phase 2: tick loop (roadmap — v0.2)

`/loop /epic-shepherd:shepherd <epic-N>` — autonomous loop. Each tick:

1. If `paused` → exit (do not reschedule).
2. If `in_flight_pr` is set → invoke `pr-shepherd:pr-shepherd <PR>`. On merge → clear in-flight, regenerate snapshot, recurse. On hard stop → write `paused`, exit.
3. Else if `sequence` non-empty → pop the tier-1 head, dispatch its implementer, poll for the opened PR, record into `in_flight_pr`.
4. Else (sequence empty) → invoke Phase 3.

## Phase 3: close-out (roadmap — v0.3)

When the sequence empties:

1. Verify every sub-issue closed via fresh GraphQL rollup.
2. Compose `docs/reports/<UTC-date>-epic-<N>-closeout.md` summarizing landed PRs + files.
3. Open a PR for the report, shepherd it to merge.
4. `gh issue close <epic> --reason completed`.

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
