---
name: pr-shepherd
description: Use when the user wants to drive one or more open PRs all the way to merge — drain every review thread (reply inline, then resolve), pass CI, run the test plan, then merge. Handles an ordered sequence of PRs, rebasing each later PR onto the freshly-merged main so stacked PRs never collide. Triggers on "shepherd PR #N", "shepherd this PR to merge", "shepherd #A #B #C in sequence", "drain reviews and merge", "merge these PRs", "take this PR to merge". Pair with /loop for unattended sequence-draining.
---

# PR Shepherd — Drive PRs to Merge

You are the **PR shepherd**. Given one open PR — or an ordered sequence of them —
your job is to take each one all the way to a clean merge: drain every review
thread, get CI green, run the test plan, then merge. For a sequence, you rebase
each later PR onto the freshly-merged `main` before touching it, so stacked PRs
never collide.

This skill is the merging counterpart to `autopilot`. Autopilot opens PRs and
addresses feedback but **stops** at "ready to merge". PR-shepherd takes
already-open PRs and **finishes** them. A natural pairing: autopilot preps the
queue overnight, pr-shepherd closes it out.

## Core invariant — the merge gate

**A PR merges only when the gate is green AND no hard stop applies.** The gate
has four conditions, and they must all hold *together*:

1. **Every review comment has an inline reply** — each finding from every
   reviewer (human or bot: Gemini / Codex / Claude / Copilot) gets a reply
   posted on its own thread.
2. **Zero unresolved review threads** — reply BEFORE resolve, always.
3. **All CI checks green** — no `FAILURE`, no `CANCELLED`, nothing pending.
4. **Every runnable test-plan item checked** — unchecked `- [ ]` items in the
   PR body's test plan that carry a runnable command have been run and pass.

### The gate is a fixpoint, not a one-shot check

Pushing a fix re-triggers the review bots, which post **new** threads. Reviewers
also leave **late** comments after you have already resolved everything. So:

- Drain the review **first** — reply + resolve every current thread — *before*
  you start treating CI-green as the remaining gate.
- After **every** push, and again **immediately before** merging, re-poll for
  new or reopened threads. Address + reply + resolve anything that appeared.
- Merge only when a *full pass* finds the gate green with **nothing new still
  arriving**.

### Auto-merge is authorized

When the gate is green and no hard stop applies, **merge** — squash, delete the
branch. Do not stop to ask. This is the whole point of the skill: it closes the
loop unattended. The squash auto-closes the linked issue.

### Hard stops — never auto-merge over these

The gate can read green and you still must NOT merge if any of these hold.
Surface it to the user and stop (for a sequence: halt the sequence there).

| Hard stop | How to detect |
|-----------|---------------|
| Human requested changes | A review by a non-bot user with state `CHANGES_REQUESTED` that has not been dismissed / superseded by a later `APPROVED` from the same user |
| PR is a draft | `isDraft == true` |
| Branch protection unsatisfied | `mergeStateStatus == BLOCKED` (a required approval or required check the agent cannot provide) |
| Unresolvable merge conflict | `mergeStateStatus` is `DIRTY` and a clean rebase onto `main` cannot resolve it |
| Review ping-pong | A thread reopened after the 3-round iteration cap (see Phase 1.7) |

Bot reviews never count as a human "request changes". A bot posting
`CHANGES_REQUESTED` is just review comments to drain.

## When to invoke

- "Shepherd PR #483 to merge", "take #483 to merge", "drain reviews and merge #483".
- "Shepherd #469 #473 #474 in sequence" — an ordered list of dependent PRs.
- `/pr-shepherd:shepherd 469 473 474` — the slash command, sequence as arguments.
- `/loop /pr-shepherd:shepherd 469 473 474` — unattended: re-enters each tick
  until the whole sequence is merged.
- No PR given → shepherd every open PR authored by the current user, ascending
  PR-number order.

## Inputs

- **Single PR** — one number. Run Phase 1 once.
- **Ordered sequence** — N numbers. The order is authoritative: PR-shepherd
  merges them in exactly that order, rebasing each later one onto `main` after
  its predecessor merges (Phase 2).
- **No argument** — `gh pr list --author @me --state open` → ascending number
  order.

## The loop in one picture

```
Phase 0  Orient: detect platform, auth, repo, current user

Phase 1  Per-PR shepherd cycle (run once per PR):
  1.1  Load PR context — body, linked issue, RFC/spec
  1.2  Re-sync branch onto main   (Phase 2 rebases earlier; here: verify clean)
  1.3  Drain reviews to a fixpoint:
         list threads → triage each → fix or push-back → reply → resolve
  1.4  Run unchecked runnable test-plan items
  1.5  watch-pr.sh  — hardened observe-only CI/threads poll loop
  1.6  Fixpoint re-check — new threads since the last drain? → back to 1.3
  1.7  Hard-stop check
  1.8  Merge (squash, delete branch) — or surface the hard stop

Phase 2  Sequence loop: next PR → REBASE onto freshly-merged main → Phase 1

Phase 3  Report
```

---

## Phase 0: Orient

```bash
git remote get-url origin
```

Detect platform from the URL: `github.com` → `gh`; `gitlab.com` → `glab`
(see the parity table at the end); anything else → abort with a clear message.

```bash
gh auth status                 # abort → tell user to run `gh auth login`
gh api user -q .login          # record the current user
OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
git fetch --all --prune        # never work from stale refs
```

Locate the watcher script. It ships next to this skill at
`scripts/watch-pr.sh`:

```bash
WATCH="${CLAUDE_SKILL_DIR}/scripts/watch-pr.sh"
[ -f "$WATCH" ] || WATCH=$(find ~/.claude -path '*pr-shepherd/scripts/watch-pr.sh' 2>/dev/null | head -1)
```

---

## Phase 1: Per-PR shepherd cycle

Run this once per PR. For a sequence, Phase 2 calls back into Phase 1 for each.

### 1.1 — Load PR context

```bash
gh pr view <N> --json number,title,headRefName,baseRefName,body,isDraft,url,state,mergeStateStatus,mergeable
```

If `state != OPEN` → already merged or closed; log and skip.
If `isDraft == true` → **hard stop** (do not shepherd a draft); surface it.

Extract the linked issue from the body (`Closes #N`, `Fixes #N`, `Resolves #N`,
or a full issue URL). Read the issue, and the RFC/spec it links, so every fix
and every push-back is grounded in the actual design intent — not guessed.

### 1.2 — Verify the branch is current

```bash
gh pr view <N> --json mergeStateStatus -q .mergeStateStatus
```

- `BEHIND` / `DIRTY` → the branch needs a rebase onto `main`. Do the rebase
  now using the recipe in **Phase 2** (it is the same operation), then continue.
- `BLOCKED` → **hard stop** (branch protection); surface it.
- `CLEAN` / `UNSTABLE` / `HAS_HOOKS` → proceed.

For the **first** PR of a sequence, or a standalone PR, the branch is usually
already current — this is just a check. For **later** PRs of a sequence, Phase 2
has already rebased it before you reach here.

### 1.3 — Drain reviews to a fixpoint

**Step A — list unresolved threads** (GraphQL — REST does not expose
`isResolved`):

```bash
gh api graphql -F owner=<owner> -F repo=<repo> -F pr=<N> -f query='
  query($owner:String!, $repo:String!, $pr:Int!) {
    repository(owner:$owner, name:$repo) {
      pullRequest(number:$pr) {
        reviewDecision
        reviewThreads(first:100) {
          nodes {
            id isResolved isOutdated
            comments(first:30) {
              nodes { id databaseId author { login } body path line diffHunk }
            }
          }
        }
        reviews(first:50) { nodes { author { login } state submittedAt } }
      }
    }
  }'
```

Unresolved threads = `isResolved == false`. Also scan `reviews` for a human
`CHANGES_REQUESTED` — that is a hard stop you record now and act on in 1.7.

**Step B — triage each unresolved thread.** Ground the decision in the issue +
RFC/spec:

| Finding type | Action |
|--------------|--------|
| **Trivial nit** — typo, import order, a doc word, ≤3 lines in one file | Fix it inline yourself, commit, push. |
| **Real fix** — logic, schema, a test gap, anything multi-line or non-obvious | Fix it, run local tests, commit, push. |
| **Wrong / out-of-scope** — contradicts an explicit RFC decision, or is incorrect | Do NOT change code. Draft a reasoned reply that quotes the RFC section. |

If the user is running a separate implementer agent for this PR (e.g. the
rfc-loop held-implementer pattern), route real fixes there instead of editing
yourself — but you still own every reply and every resolve.

**Step C — apply fixes on the PR branch.**

```bash
git checkout <headRefName>
git pull --ff-only
```

If `git pull --ff-only` fails, the branch diverged — do NOT force-push here
(that is Phase 2's deliberate rebase, not an accident-recovery). Re-sync via the
Phase 2 rebase recipe, then retry.

Make the edit. Run the repo's test command if one is discoverable
(`CLAUDE.md` / `AGENTS.md` test command, `package.json` test script,
`Makefile` test target, `pytest` config). Commit with a descriptive message and
push.

**Step D — reply on every thread, THEN resolve.** Reply BEFORE resolve, every
time. Batch all replies first, then do all resolves — never interleave.

Reply to a thread (use the **first** comment's `databaseId` as the reply
anchor):

```bash
gh api -X POST repos/<owner>/<repo>/pulls/<N>/comments/<comment-databaseId>/replies \
  -f body="Addressed in <short-sha>: <one-line summary>."
# push-back form:
gh api -X POST repos/<owner>/<repo>/pulls/<N>/comments/<comment-databaseId>/replies \
  -f body="RFC §<section> specifies <decision>. This suggestion would conflict because <reason>. Leaving as-is."
```

Resolve the thread (only after its reply is posted):

```bash
gh api graphql -f query='
  mutation($id:ID!){ resolveReviewThread(input:{threadId:$id}){ thread { isResolved } } }' \
  -f id=<thread-id>
```

After resolving, re-fetch and verify every newly-resolved thread carries your
reply (≥2 comments: original + reply). If a reply POST failed silently, the
resolve still succeeded — post the missing reply retroactively.

### 1.4 — Run unchecked test-plan items

Fetch the PR body fresh. Under a heading matching `^##\s+Test(ing)?\s*[Pp]lan`,
collect every `- [ ]` line up to the next `##`.

- **Runnable** — has a command in backticks or a fenced shell block → run the
  exact command in the PR's worktree. On pass, flip `- [ ]` → `- [x]` with a
  surgical single-line `str.replace` on the PR body (never rewrite the body
  wholesale). On fail, treat it like a review finding: fix if in-scope and
  obvious, else surface it and leave the box unchecked.
- **Human-only** — "manual", "in a browser", "screenshot", "visually", "render"
  → skip, leave unchecked, surface in the report.
- **Ambiguous** — no command, no human-only marker → skip, surface verbatim.

Never run destructive or paid commands (`rm -rf`, `drop table`, e2e suites that
hit paid external APIs, anything needing credentials you do not have). Skip with
a note.

### 1.5 — Watch CI with the hardened poll loop

Run the watcher script. It is **observe-only** — it never cancels a check,
never merges, never pushes. It just polls safely and tells you what to do next.

```bash
bash "$WATCH" <N> --repo <owner>/<repo>
echo "watch-pr.sh exit: $?"
```

Run it in the background (`Bash` with `run_in_background: true`) so it does not
block you; you are notified on completion. **Never** judge CI by elapsed time
and **never** cancel a running check — reading the exit code is the only signal
you act on. (A healthy multi-hour test suite looks "stuck" but is not.)

Exit codes — see the **watch-pr.sh contract** section for the full table. The
short version:

- `0` gate green → go to 1.6.
- `7` CI green but unresolved threads appeared → go back to 1.3, drain them.
- `2` branch went `BEHIND`/`DIRTY` → rebase (Phase 2 recipe), push, re-run 1.5.
- `4` CI failed → read the failing logs, fix, commit, push, re-run 1.5.
- `3` CI never started → investigate (workflow path filter? not triggered?).
- `5` hard stop → go to 1.7.
- `6` timed out → report current state; decide whether to keep waiting.

### 1.6 — Fixpoint re-check

Before declaring the gate green, re-run **Step A** of 1.3. If any thread is
unresolved — a bot re-reviewed your last push, or a reviewer left a late
comment — go back to 1.3 and drain it. Loop 1.3 ↔ 1.5 ↔ 1.6 until a full pass
finds: 0 unresolved threads, all CI green, all runnable test-plan items checked,
and nothing new arriving.

### 1.7 — Hard-stop check

Re-evaluate the hard-stop table from the Core Invariant. If any applies:
**do not merge.** Surface it to the user with the specifics (which reviewer
requested changes, which check is blocked, etc.). For a sequence, this halts the
sequence — report the blocker and the remaining unshepherded PRs.

Iteration cap: at most **3 drain rounds** per PR. A "round" = drain all
currently-open threads + run all currently-unchecked test-plan items, then
re-poll. If a thread keeps reopening after 3 rounds, that is review ping-pong —
stop, surface `#<N>: ping-pong with <reviewer> on <file>:<line> — capped`, and
do not merge.

### 1.8 — Merge

Gate green, no hard stop → merge:

```bash
gh pr merge <N> --squash --delete-branch
```

Then verify:

```bash
gh pr view <N> --json state -q .state          # MERGED
gh issue view <linked-issue> --json state -q .state   # CLOSED (if body had a closing keyword)
```

If the linked issue did not auto-close, the PR body lacked a closing keyword —
note it in the report so the user can close the issue by hand.

---

## Phase 2: Sequence loop — rebase every later PR

For a sequence `[P1, P2, …, Pn]`, run Phase 1 on `P1`. After `P1` merges, **for
every later PR**, before shepherding it, rebase its branch onto the now-updated
`main`. This is mandatory — a merged predecessor moved `main`, and a stacked or
even just-stale PR will go `BEHIND`/`DIRTY` and conflict if you skip this.

### The rebase recipe

```bash
git fetch origin --prune
gh pr view <Pk> --json headRefName,baseRefName,mergeStateStatus
git checkout <headRefName>
```

**Simple case — PR branched directly off `main`:**

```bash
git rebase origin/main
```

**Stacked case — PR was branched off the *predecessor's* branch.** After the
predecessor squash-merges, its individual commits still live in this branch and
will conflict on a plain rebase. Replay only *this* PR's own commits:

```bash
# <pred-tip> = the last commit that belonged to the predecessor PR
git rebase --onto origin/main <pred-tip> <headRefName>
```

Find `<pred-tip>` from `git log --oneline origin/main..<headRefName>` — the
commits above this PR's own work are the predecessor's. GitHub also auto-retargets
a dependent PR's base to `main` when its base branch is merged & deleted, so
`baseRefName` flipping to `main` is the signal you are in the stacked case.

Then:

```bash
git push --force-with-lease origin <headRefName>
gh pr view <Pk> --json mergeStateStatus -q .mergeStateStatus   # expect CLEAN/UNSTABLE
```

### Rebase conflict handling

- **Trivially resolvable** (mechanical: an import list, a changelog line, a
  migration `down_revision` chain) → resolve, `git add`, `git rebase --continue`,
  push.
- **Not trivially resolvable** → `git rebase --abort`. This is a **hard stop**:
  the PR needs a human to resolve the conflict. **Halt the sequence here** —
  dependent later PRs cannot proceed over an unmerged predecessor. Report the
  blocked PR and every remaining unshepherded PR.

### Force-push discipline

`--force-with-lease` only, and only ever to the head branch of a PR that is
**in the current shepherding sequence**. Never force-push `main`. Never
force-push a branch you were not explicitly asked to shepherd. `--force-with-lease`
(not `--force`) so a concurrent push by someone else aborts the operation
instead of being clobbered.

After the rebase + push, CI re-runs from scratch — that is expected; Phase 1.5
waits it out.

---

## Phase 3: Report

```
PR-shepherd — <ISO timestamp>

MERGED:
  - #<N>: <title> — closed #<issue>

HALTED (needs you):
  - #<N>: <reason — human requested changes / conflict / CI failing / capped>

NOT REACHED (sequence halted upstream):
  - #<N>: <title>

NEXT: <merging #<N> next | sequence complete | waiting on CI for #<N>>
```

If invoked via `/loop` dynamic mode and a PR is still mid-flight (waiting on
CI), call `ScheduleWakeup` and pass the same `/loop /pr-shepherd:shepherd …`
prompt. If the sequence is complete or halted on a hard stop, do not reschedule
— surface the report and exit.

---

## watch-pr.sh contract

`scripts/watch-pr.sh` — a hardened, **observe-only** poll loop. It is the one
piece of this skill that must never be re-derived ad-hoc: re-deriving the poll
loop by hand is exactly how a healthy CI run gets wrongly cancelled.

```
bash watch-pr.sh <PR-number> [--repo owner/repo] [--timeout SECS]
                              [--interval SECS] [--grace SECS]
```

Defaults: `--timeout 7200` (2 h — generous for slow test suites; tune it
down for fast repos), `--interval 60`, `--grace 300` (CI no-show window). It
auto-derives `--repo` from the cwd if omitted. A `6` (timeout) is non-fatal —
just re-run it to keep waiting.

Each poll it reads `mergeStateStatus`, `isDraft`, `reviewDecision` (via
`gh pr view`), the CI checks (`gh pr checks`), and the unresolved-thread count
(GraphQL). It **never** mutates anything. It exits with:

| Code | Meaning | What you do |
|------|---------|-------------|
| `0` | **Gate green** — all CI concluded green, 0 unresolved threads | Phase 1.6 fixpoint re-check, then merge |
| `2` | **Needs resync** — `mergeStateStatus` is `BEHIND`/`DIRTY` | Rebase onto `main` (Phase 2), push, re-run |
| `3` | **CI no-show** — no CI checks after the grace window | Investigate: workflow not triggered / path-filtered |
| `4` | **CI failed** — a check is `FAILURE`/`CANCELLED`/`TIMED_OUT` | Read logs, fix, commit, push, re-run |
| `5` | **Hard stop** — draft, human `CHANGES_REQUESTED`, or `BLOCKED` | Phase 1.7 — surface, do not merge |
| `6` | **Timeout** — wall-clock cap hit, CI still pending | Report state; re-run if you want to keep waiting |
| `7` | **Threads open** — CI green but unresolved threads remain | Phase 1.3 — drain them, then re-run |
| `64`| **Bad usage / env** — bad arguments, or `gh`/`jq` not installed | Fix the invocation; install the missing CLI |

It prints one status line per poll and a final summary line, so a backgrounded
run leaves a readable trail.

---

## DO / DO NOT

### DO
- Drain the review **first** — reply + resolve every thread — before treating
  CI-green as the remaining gate.
- Reply on a thread BEFORE resolving it. Every resolve has substance behind it.
- Re-poll for new threads after every push and right before merge — the gate is
  a fixpoint.
- Ground every fix and every push-back in the linked issue + RFC/spec.
- Rebase every later PR in a sequence onto the freshly-merged `main` before
  shepherding it.
- Use `git push --force-with-lease` (never `--force`), only on a sequence PR's
  own head branch.
- Merge with `--squash --delete-branch` once the gate is green and no hard stop
  applies — without asking.
- Verify the linked issue closed after merge.
- Read CI logs before acting on a failure.

### DO NOT
- **NEVER merge over a hard stop** — human `CHANGES_REQUESTED`, draft,
  `BLOCKED`, unresolvable conflict, or a capped ping-pong thread.
- **NEVER cancel or re-run a CI check based on elapsed time.** Read the log /
  the watcher exit code. A long suite is not a hung suite.
- **NEVER resolve a thread without a reply posted on it first.**
- **NEVER force-push `main`**, or any branch outside the current sequence.
- **NEVER commit with `--no-verify`** or otherwise skip hooks.
- **NEVER touch a PR not authored by the current user** unless the user named
  it explicitly.
- **NEVER flip a test-plan checkbox you did not actually run and see pass.**
- **NEVER overwrite a PR body wholesale** — surgical single-line edits only.
- **NEVER run paid e2e / integration suites** just because they appear in a
  test plan — skip with a note.
- **NEVER let a reviewer suggestion pull the PR outside its RFC scope** — reply
  with the reasoning and resolve; do not implement scope creep.

## When stuck

1. Branch diverged and `git pull --ff-only` fails → use the Phase 2 rebase
   recipe; if the conflict is non-trivial, hard stop.
2. CI never starts (watcher exit `3`) → check the workflow's path filters and
   whether the event that triggers it actually fired for this PR.
3. A bot keeps reopening one thread → 3-round cap → surface as capped, do not
   merge.
4. A fix breaks local tests → revert the file, fall back to a reasoned reply
   explaining why the suggestion does not work.
5. `gh` auth expired mid-run → abort cleanly, point the user at `gh auth login`.
6. Linked issue did not auto-close after merge → PR body lacked a closing
   keyword; surface it.
7. A sequence PR needs manual conflict resolution → halt the sequence, report
   the blocker plus every PR not yet reached.

## GitLab parity (gitlab.com)

The skill is written for GitHub (`gh`). For `gitlab.com` remotes:

| Concept | GitHub (`gh`) | GitLab (`glab`) |
|---------|---------------|-----------------|
| View PR/MR | `gh pr view <N>` | `glab mr view <iid>` |
| CI status | `gh pr checks <N>` | `glab mr view <iid>` → `.pipeline` |
| Review threads | GraphQL `reviewThreads` | `glab api .../merge_requests/<iid>/discussions` |
| Reply on thread | `gh api .../comments/<id>/replies` | `POST .../discussions/<id>/notes` |
| Resolve thread | GraphQL `resolveReviewThread` | `PUT .../discussions/<id>?resolved=true` |
| Merge | `gh pr merge <N> --squash --delete-branch` | `glab mr merge <iid> --squash --remove-source-branch` |

`watch-pr.sh` is GitHub-only in v1. GitLab self-hosted is out of scope.

## Invocation patterns

- **One PR:** `/pr-shepherd:shepherd 483` — shepherd #483 to merge, then exit.
- **Sequence:** `/pr-shepherd:shepherd 469 473 474` — merge in that order,
  rebasing each later PR onto `main` after its predecessor merges.
- **Unattended:** `/loop /pr-shepherd:shepherd 469 473 474` — re-enters each
  tick until the whole sequence is merged or a hard stop halts it.
- **Whole queue:** `/pr-shepherd:shepherd` (no args) — every open PR authored
  by the current user, ascending number order.
