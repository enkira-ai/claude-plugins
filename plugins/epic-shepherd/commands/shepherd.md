---
description: Autonomous tick loop that drives a whole GitHub Epic to completion. Snapshots open sub-issues, dispatches the next ready issue's implementer (rfc-loop / autopilot / inline), hands the resulting PR to pr-shepherd to drain reviews + merge, then regenerates the snapshot and recurses. Pair with /loop for unattended self-pacing. Hard stops (human CHANGES_REQUESTED, branch protection, conflict, ping-pong cap, implementer failure) pause the loop and surface the reason; operator resumes via `state.sh resume <epic>` after fixing the cause.
---

Use the `epic-shepherd:epic-shepherd` skill (Phase 2 tick loop) to drive
the epic to completion.

Epic issue number: $ARGUMENTS

Run one tick of the loop. The skill is designed for autonomous use via
`/loop /epic-shepherd:shepherd $ARGUMENTS` — each tick decides one
action (shepherd the in-flight PR / dispatch the next issue / close out)
based on persisted state, then schedules the next wakeup at a
cache-friendly interval.

As of v0.3.0 the loop **self-closes the epic** via Phase 3 once the
sequence empties: it composes a close-out report, opens a PR that
squash-closes the epic via `Closes #<epic>`, hands that PR to
pr-shepherd to merge, and exits. No operator action is needed after
`/loop /epic-shepherd:shepherd <N>` is started — the loop runs end to
end and stops on its own when the epic is fully closed.

Compose with:

- **pr-shepherd** (per-PR merge — already shipped) — Phase 2's SHEPHERD
  branch delegates the actual merge to this skill.
- **rfc-loop** (per-issue TDD implementation — default implementer) —
  Phase 2's DISPATCH branch delegates substantive code to this skill's
  held-implementer subagent pattern.
- **autopilot** (per-issue feedback-loop implementation — opt-in via
  per-item `implementer: "autopilot"`) — lighter alternative for
  mechanical ports.

If no epic number was given, ask for one (do not guess).

Read-only operations:
- `gh` queries against issues + PRs (epic-shepherd snapshot, pr-shepherd
  thread + CI poll, poll-for-pr.sh)

Mutating operations (per tick, gated on state):
- `state.sh mark-in-flight | complete | pause | resume` (atomic JSON writes
  to `/tmp/epic-shepherd-state-<epic>.json` only)
- Implementer dispatch (opens a PR via the chosen sub-skill — rfc-loop /
  autopilot / inline)
- `pr-shepherd:pr-shepherd` invocation on the in-flight PR (which itself
  drains threads, watches CI, and merges when green per its own gate)

Do **not** mutate epic-level state outside the documented state
transitions (no manual issue closes, no manual PR merges) — the loop
relies on its own state machine for idempotency. The only operator
mutation is `state.sh resume <epic>` after fixing the cause of a pause.

See the skill's "Phase 2 — tick loop" section for the full per-tick
decision table, the cache-friendly ScheduleWakeup pacing, and the
hard-stop list.
