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
| **Correct but beyond the issue** — true, but hardens behaviour the issue does not ask for, usually on a code path this PR does not wire up | Do NOT change code. Reply acknowledging it and say where it belongs; file a follow-up issue if it has standalone value. |

That fourth row is the one that gets skipped, because the finding is *right*.
Correctness is not the test — scope is. See §1.3.1.

If the user is running a separate implementer agent for this PR (e.g. the
rfc-loop held-implementer pattern), route real fixes there instead of editing
yourself — but you still own every reply and every resolve.

### 1.3.1 — Scope discipline and the stopping rule

An LLM reviewer reads the diff in isolation, with no knowledge of the issue's
scope, what the module is for, or whether anything calls it. It will therefore
generate correct, plausible, unbounded hardening suggestions for as long as you
keep asking. **Left unchecked this is the single biggest way a shepherd run
turns a small PR into a large one.** Apply these before writing any code.

**The merge bar is the issue's acceptance criteria — not the absence of bot
findings.** Re-read them at the top of every round. Once they are met, CI is
green and threads are drained, that is a complete PR; further findings are
input to triage, not a gate.

**A finding must name a failure reachable from code this PR actually wires up.**
Check it, cheaply:

```bash
# does any NON-TEST code outside the new package import it yet?
grep -rn --include='*.py' --exclude-dir='<pkg-dir-name>' \
     -e 'from <pkg>' -e 'import <pkg>' <source-root>/
```

Two details that decide whether this answers the right question. Search the
**source root** (`src/`, the package dir), not `.` — a test importing a module
is not the same as production code wiring it up, and including `tests/` turns
every new package into a false "it has consumers". And exclude the package by
**directory**, not by filtering the output on a path prefix: GNU grep prefixes
recursive matches with `./`, so a `grep -v "^<pkg>/"` filter silently keeps the
package's own internal imports and reports a consumer that does not exist.

**That grep is necessary, not sufficient — an absent in-repo import does not
prove unreachable.** Before concluding anything, check the ways a caller
reaches code without importing it from this repository:

- packaging entry points — `[project.scripts]`, `[project.entry-points]`,
  `console_scripts`, a plugin manifest a framework discovers at runtime
- a public library API the package exists to expose, where the consumers are
  downstream users and there is nothing local to find
- the linked issue naming an external consumer explicitly

If any of those apply the path is reachable — which settles only that the
finding is **not** speculation. It does not make it in scope. Reachability is
a prerequisite for the triage, not a substitute for it: go on and compare the
claimed failure against the issue's acceptance criteria, and a correct finding
about a reachable path that no criterion asks for is still the "Correct but
beyond the issue" row. Otherwise every public API, console script and entry
point becomes unboundedly hardenable — the outcome this section exists to
prevent.

Only when the module is internal *and* nothing consumes it is it a seam
for a later item — and there, defensive hardening is speculation: the first
real consumer, running against the real service, is a stronger test than any
reviewer's imagination. Reply, name the consuming issue, resolve.

**Never widen an interface to satisfy a review comment — unless the issue's
acceptance criteria require it.** Adding a config field, an allowlist entry, a
supported format or a new code path *to close a thread* creates surface that
produces the next finding. But an acceptance criterion can only be satisfiable
by new API: "swapping the provider is a config change with no call-site edits"
is not met while the endpoint is a hard-coded constant, and adding that field
is a **real fix**, not scope creep.

The test is whose requirement it is. Trace the addition back to a clause in the
issue or RFC: if it lands on one, implement it. If the only justification is
the review comment itself, that is the signal the finding is out of scope, not
that the API was missing.

**Never add a value you have not verified** against a spec, the vendor's docs,
or a run. A plausible-looking constant is a defect waiting to be found, and a
test that asserts your own assumption proves nothing — it only makes the
assumption look checked.

**Track the regression rate, and say it out loud.** Keep a count of rounds
whose findings were defects *introduced by a previous round's fix*. When that
approaches half, stop: you are adding surface faster than review removes it.

**Round budget — the cap is Phase 1.7's, not a second one.** Phase 1.7 already
stops at **3 drain rounds** and treats further ping-pong as a hard stop. This
section adds *what to say* when that fires, not a different number: report the
round count, the regression count, acceptance-criteria status, and a
merge/continue recommendation. An explicit user instruction to continue
overrides the cap — that is the only thing that does — and when it is
overridden you keep counting and keep reporting at every third round, because
the tally is what makes the runaway visible. "The bot found something" is not a
reason to continue; "the acceptance criteria are not met" is.

**When you do stop,** say so in the approval or merge message — which criteria
are met, what you deliberately left, and where it belongs. A future reader
should not have to re-derive why the loop ended.

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
| `0` | **Gate green** — all CI green, 0 unresolved threads, check count stable across two consecutive polls | Phase 1.6 fixpoint re-check, then merge |
| `2` | **Needs resync** — `mergeStateStatus` is `BEHIND`/`DIRTY` | Rebase onto `main` (Phase 2), push, re-run |
| `3` | **CI no-show** — no CI checks on the head SHA after the grace window | Investigate: workflow not triggered / path-filtered |
| `4` | **CI failed** — a check on the head SHA is failing/cancelled | Read logs, fix, commit, push, re-run |
| `5` | **Hard stop** — draft, human `CHANGES_REQUESTED`, or `BLOCKED` | Phase 1.7 — surface, do not merge |
| `6` | **Timeout** — wall-clock cap hit (CI still pending or gate unstable) | Report state; re-run if you want to keep waiting |
| `7` | **Threads open** — unresolved review threads exist (fires regardless of CI state — drain mid-CI bot re-reviews immediately, not just on CI completion) | Phase 1.3 — drain them, then re-run |
| `64`| **Bad usage / env** — bad arguments, or `gh`/`jq` not installed | Fix the invocation; install the missing CLI |

**v1.1.0 contract changes** — three correctness fixes derived from real shepherding experience on the RFC-020 PRs:

- CI enumeration uses `gh api repos/.../commits/<head_sha>/check-runs` (per-commit) rather than `gh pr checks` (PR-level). The PR-level API leaks cancelled checks from superseded prior commits across a push, producing false-alarm exit `4` right after a fix-push (observed on #495's CI re-run after a force-push superseded the prior pytest job).
- Exit `7` is generalized to fire whenever `unresolved_threads > 0`, regardless of CI state. This catches mid-CI bot re-reviews (Gemini/Codex/Copilot re-running on a new push) so the agent drains them immediately instead of waiting another hour for CI. **Implication:** drain reviews to 0 BEFORE arming the watcher, or the very first poll will exit `7` and tell you to drain.
- Stabilization-wait before exit `0`: gate-green is deferred until the check count is unchanged from the previous poll. Kills the "pytest registered between watcher exit and merge" race (the #495 near-miss where the watcher said `2/2 green` and would have merged before pytest's 3rd check registered for the new head).

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
- Re-read the issue's acceptance criteria at the top of every review round, and
  treat them — not the bot's silence — as the merge bar.
- Run the **CI interpreter version** locally before pushing a fix, not just your
  default one. Async and timing behaviour differs between versions, and a green
  local run on the wrong interpreter is how a red CI arrives as a surprise.
- Count rounds, and count how many of them fixed a defect a previous round
  introduced. Report both when you check in.

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
  with the reasoning and resolve; do not implement scope creep. This applies to
  findings that are entirely **correct**: in-scope is a separate test from
  right, and a true finding about an unreachable path is still scope creep.
- **NEVER treat "the reviewer has no more findings" as the merge condition.**
  An LLM reviewer can always find another P2 in non-trivial concurrent code.
  The acceptance criteria terminate the loop; the bot does not.
- **NEVER add a code path, config field or allowlist entry that no caller
  exercises** in order to close a review thread.
- **NEVER guess a value** — a MIME type, a timeout, a protocol constant —
  without checking the spec or the vendor's docs in the same turn.

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
