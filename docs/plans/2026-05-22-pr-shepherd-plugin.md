# Design — `pr-shepherd` plugin

- **Date:** 2026-05-22
- **Status:** implemented
- **Author:** Enkira AI

## Motivation

"Shepherding a PR" — monitor and drain every review comment, get all CI green,
finish the test plan, then merge — had become an ad-hoc process re-derived each
session. Re-deriving it is error-prone: in one session a healthy multi-hour CI
run was wrongly cancelled because "stuck" was judged from elapsed time instead
of the logs. This plugin codifies the process once so every Claude session, in
any repo, runs the identical, audited loop.

## Scope

A new marketplace plugin, `pr-shepherd`. It takes **already-open** PRs and
drives them to merge. It does not open PRs (that is `autopilot`'s job) or
implement issues (that is `rfc-loop`'s job).

## Design decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Merge autonomy | **Auto-merge on a green gate** — squash + delete branch, no confirmation. Hard stops still block it. |
| 2 | CI/review poll loop | **Hardened helper script** (`watch-pr.sh`) — a tested, observe-only loop, not re-derived per session. |
| 3 | Invocation | **Skill + slash command**, both accepting an **ordered PR sequence**. |
| 4 | Sequence safety | Each later PR is **rebased onto the freshly-merged `main`** (just-in-time) before it is shepherded — `--force-with-lease`, `rebase --onto` for stacked PRs. A non-trivial conflict halts the sequence. |

## Components

```
plugins/pr-shepherd/
  .claude-plugin/plugin.json
  commands/shepherd.md                    # /pr-shepherd:shepherd <PR#> [<PR#> ...]
  skills/pr-shepherd/SKILL.md
  skills/pr-shepherd/scripts/watch-pr.sh  # observe-only poll loop, pure bash
```

## The merge gate (a fixpoint)

A PR merges only when all four conditions hold **together**, re-verified after
every push and immediately before merge:

1. every review comment (human + bot) has an inline reply on its thread;
2. zero unresolved review threads (reply BEFORE resolve);
3. all CI checks green;
4. every runnable test-plan checkbox ticked.

A fix-push re-triggers the review bots → new threads; reviewers also leave late
comments. So the gate is re-checked in a loop until a full pass finds nothing
new — a fixpoint, not a one-shot check.

### Hard stops (never auto-merge)

Human "Request changes" outstanding · draft PR · `mergeStateStatus == BLOCKED`
· unresolvable conflict · review ping-pong past the 3-round cap. Surface and
stop; for a sequence, halt it there.

## Sequence loop + rebase

For an ordered list `[P1 … Pn]`: shepherd `P1` to merge, then for every later
PR — before draining it — rebase its branch onto the now-updated `main`:

- branched off `main` → `git rebase origin/main`;
- stacked off the predecessor → `git rebase --onto origin/main <pred-tip> <branch>`
  (replays only this PR's own commits, since the predecessor is now a single
  squash commit on `main`);
- push with `--force-with-lease` (never `--force`, never `main`, never a branch
  outside the sequence);
- non-trivial conflict → `git rebase --abort`, hard stop, halt the sequence.

This is the explicit guard against later PRs colliding once an earlier one
merges.

## watch-pr.sh contract

Observe-only — never merges, cancels, pushes, or resolves. Polls `gh pr view`,
`gh pr checks`, and the `reviewThreads` GraphQL query; exits with a code telling
the agent what to do:

| Code | Meaning |
|------|---------|
| 0 | gate green (CI green, 0 unresolved threads) |
| 2 | needs resync (`BEHIND`/`DIRTY`) |
| 3 | CI no-show (no checks past the grace window) |
| 4 | CI failed |
| 5 | hard stop (draft / human CHANGES_REQUESTED / BLOCKED / closed) |
| 6 | timeout (non-fatal — re-run to keep waiting) |
| 7 | CI green but unresolved threads remain |

Guards: wall-clock cap, conflict short-circuit, CI-no-show detection — the
guards whose absence caused the wrongful CI cancel.

## Relationship to existing plugins

- **autopilot** — opens PRs + addresses feedback, *stops* at "ready to merge".
  pr-shepherd is its merging counterpart; autopilot preps, pr-shepherd finishes.
- **rfc-loop** — its per-PR steps 3e–3g are exactly per-PR shepherding;
  rfc-loop could delegate to pr-shepherd in a future revision. Not changed here.

## Out of scope (v1)

- Opening PRs or implementing issues.
- `watch-pr.sh` on GitLab (the skill body has a `glab` parity table; the script
  is GitHub-only).
- GitLab self-hosted.
