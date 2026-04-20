---
name: autopilot
description: Use when the user wants to run the overnight PR grind — open PRs from ready issues, poll existing PRs, address reviewer feedback (from humans and bots like Copilot/Claude/Gemini), and stop each PR at "ready to merge" without actually merging. Triggers on "autopilot", "run autopilot", "grind PRs", "handle review comments", "address PR feedback", "overnight PRs", "prep PRs for merge". Recommended to invoke via `/loop /autopilot:autopilot` for continuous operation.
---

# Autopilot — Stripped-Down PR Grind

You are the **autopilot agent**. Your job is to move the user's open PRs toward a "ready to merge" state and open fresh PRs from ready issues — so the user wakes up to a queue of green PRs awaiting their one-click merge.

## Core invariant — read this first

**You NEVER merge a PR.** The stop condition for every PR is "ready to merge" (all review comments resolved + CI green). Surface it in the report and move on. Merging is the user's decision, always.

If you catch yourself about to run `gh pr merge` or `glab mr merge`, stop. That is a bug in your reasoning.

## When to invoke

- User says "run autopilot", "grind PRs", "handle the review comments on my PRs", or similar.
- User wraps you in `/loop` (e.g. `/loop /autopilot:autopilot` or `/loop 15m /autopilot:autopilot`). This is the recommended mode — one pass per `/loop` tick.
- User asks you to "clear my PR queue overnight" or similar.

## Pass protocol

Each invocation performs exactly **one pass**: Phase 0 (orient) → Phase A (manage existing PRs) → Phase B (create new PRs from ready issues) → Phase C (report + self-pace). Then exit.

---

### Phase 0: Orient

Run these to establish context:

```bash
git remote get-url origin
```

Detect platform from the URL:
- Contains `github.com` → use `gh` CLI
- Contains `gitlab.com` → use `glab` CLI
- Anything else → abort with: `"Autopilot requires github.com or gitlab.com remote. Got: <url>"`

Verify authentication:

```bash
# GitHub
gh auth status

# GitLab
glab auth status
```

If unauthenticated, abort and tell the user to run `gh auth login` / `glab auth login`.

Record the current user:

```bash
# GitHub
gh api user -q .login

# GitLab
glab api user | jq -r .username
```

Fetch latest refs so you're not working from stale state:

```bash
git fetch --all --prune
```

---

### Phase A: Manage existing PRs (priority — this is the core loop)

Enumerate your open PRs:

```bash
# GitHub
gh pr list --author @me --state open \
  --json number,title,headRefName,baseRefName,body,url,isDraft

# GitLab
glab mr list --author=@me --state=opened \
  -F json
```

For each PR, run the per-PR cycle below. Process PRs in PR-number order (stable, predictable).

#### A.1 — Load PR context

Read the PR body. Extract the linked issue number from patterns:
- `Closes #N`, `closes #N`, `Fixes #N`, `Resolves #N`
- Full URLs like `github.com/<owner>/<repo>/issues/N`

Fetch the issue:

```bash
# GitHub
gh issue view <N> --json title,body,url,labels
```

From the issue body, find the **RFC link** — typically a path like `docs/rfcs/<slug>.md` in the repo, or a URL. Load the RFC:
- Repo path → use the `Read` tool on the absolute path.
- External URL → use `WebFetch`.

If no RFC is linked, proceed with just the issue body as context and log `"no RFC linked for #<N>, using issue body only"` in the report for that PR.

#### A.2 — List unresolved review threads

**GitHub** (threads are a GraphQL concept; REST doesn't expose `isResolved`):

```bash
gh api graphql -F owner=<owner> -F repo=<repo> -F pr=<N> -f query='
  query($owner:String!, $repo:String!, $pr:Int!) {
    repository(owner:$owner, name:$repo) {
      pullRequest(number:$pr) {
        reviewThreads(first:100) {
          nodes {
            id
            isResolved
            isOutdated
            comments(first:20) {
              nodes {
                id
                author { login }
                body
                path
                line
                diffHunk
              }
            }
          }
        }
      }
    }
  }'
```

Filter to `isResolved == false` and `isOutdated == false`.

**GitLab** (uses "discussions"):

```bash
glab api "projects/:id/merge_requests/<iid>/discussions" | \
  jq '[.[] | select(.notes[0].resolvable == true and .notes[0].resolved == false)]'
```

#### A.3 — Check CI

```bash
# GitHub
gh pr checks <N> --json name,state,conclusion

# GitLab
glab mr view <iid> -F json | jq '.pipeline'
```

Categorize CI into one of:
- `green` — all required checks passed
- `red` — at least one required check failed
- `pending` — any required check is still running or queued

#### A.4 — Decide PR state

| Unresolved threads | CI     | Action                                                 |
|--------------------|--------|--------------------------------------------------------|
| 0                  | green  | **READY TO MERGE** — log + skip (do NOT merge)          |
| 0                  | red    | **BLOCKED** — log CI failure summary, skip this pass   |
| 0                  | pending| **IN PROGRESS** — log "waiting on CI", skip this pass  |
| ≥1                 | any    | Proceed to A.5 to address comments                     |

#### A.5 — Address each unresolved comment

For each unresolved thread, in order:

1. **Build context.** You already have the RFC and issue body. Also read the comment's `diffHunk` and the file at `path:line` for local context.

2. **Decide: fix or reply?** Ground the decision in the RFC and issue.
   - **Apply fix** if: the comment identifies a real bug, aligns with the RFC, or is a reasonable improvement within scope.
   - **Reply with rationale** if: the comment is out of scope for the RFC, contradicts an explicit RFC decision, or is incorrect. Quote the relevant RFC section in your reply.

3. **If applying a fix:**

   ```bash
   git checkout <head-ref>
   git pull --ff-only
   ```

   If `git pull --ff-only` fails, **stop** working on this PR. Do NOT force-push. Log in the report: `"#<N>: branch diverged, skipping — manual resolution needed"`.

   Make the code change using `Edit`. Run local tests if a command is obvious from the repo:
   - `CLAUDE.md` or `AGENTS.md` specifies a test command → run it
   - `package.json` has a `test` script → `npm test` or equivalent
   - `Makefile` has a `test` target → `make test`
   - `pytest.ini` / `pyproject.toml` with pytest → `pytest`

   If tests fail, revert your change (`git checkout -- <files>`) and fall back to reply-with-rationale explaining the failure.

   Commit and push:

   ```bash
   git add <changed-files>
   git commit -m "fix(review): address @<reviewer> comment on <file>

   <one-line summary of what changed>"
   git push
   ```

   Reply on the thread referencing the commit:

   ```bash
   # GitHub — reply to a review comment
   gh api -X POST repos/<owner>/<repo>/pulls/<N>/comments/<comment-id>/replies \
     -f body="Addressed in <short-sha>: <one-liner>."
   ```

4. **If replying with rationale:**

   ```bash
   # GitHub
   gh api -X POST repos/<owner>/<repo>/pulls/<N>/comments/<comment-id>/replies \
     -f body="RFC §<section>: <quoted decision>. This change would conflict because <reason>. Leaving as-is."
   ```

5. **Mark the thread resolved.**

   ```bash
   # GitHub
   gh api graphql -f query='
     mutation($id:ID!) {
       resolveReviewThread(input:{threadId:$id}) { thread { isResolved } }
     }' -f id=<thread-id>
   ```

   ```bash
   # GitLab
   glab api -X PUT \
     "projects/:id/merge_requests/<iid>/discussions/<discussion-id>?resolved=true"
   ```

#### A.6 — Iteration cap

At most **3 rounds** of address-and-resolve per PR per pass. A "round" = address all currently-unresolved threads, then re-fetch to see if new ones appeared (e.g. a bot re-reviewed).

If a thread keeps reopening after 3 rounds, log `"#<N>: ping-pong with <reviewer> on <file>:<line> — capped"` and move on. Surface it in the Phase C report.

---

### Phase B: Create new PRs from ready issues

Find opt-in issues. Only issues labeled `autopilot` are eligible — this is the user's explicit opt-in so we don't create PRs for every open issue.

```bash
# GitHub
gh issue list --author @me --state open --label autopilot \
  --json number,title,body,url

# GitLab
glab issue list --author=@me --state=opened --label=autopilot -F json
```

For each issue:

1. **Skip if a PR already exists** linking to it:

   ```bash
   gh pr list --state open --search "Closes #<N> in:body" --json number
   ```

   Non-empty → skip.

2. **Check unblocked.** Parse the issue body for blocker patterns:
   - `Depends on #M` / `Blocked by #M` / `Waiting on #M`

   For each referenced issue/PR number, check its state. If any blocker is still open, log `"issue #<N>: blocked by #<M>, skipping"` and move on.

3. **Read the RFC** linked from the issue body (same lookup as A.1). If no RFC is linked, skip and log — don't implement blind.

4. **Create the branch:**

   ```bash
   slug=$(echo "<issue-title>" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-' | head -c 40)
   git checkout -b "autopilot/issue-<N>-${slug}" origin/<default-branch>
   ```

   Default branch is usually `main` — confirm with `gh repo view --json defaultBranchRef`.

5. **Implement per the RFC.** Follow the RFC's specification. Use existing code conventions in the repo (read `CLAUDE.md` / `AGENTS.md` if present).

6. **Run tests.** Same inference as A.5. If tests fail, commit the WIP work on the branch but do **not** open the PR; log `"issue #<N>: implementation failed tests, left WIP on branch <branch>"` in the report.

7. **Commit + push:**

   ```bash
   git add -A
   git commit -m "feat: <short title>

   Closes #<N>.
   Implements RFC: <rfc-path>."
   git push -u origin <branch>
   ```

8. **Open as draft PR:**

   ```bash
   gh pr create --draft \
     --title "<title>" \
     --body "Closes #<N>

   ## Summary
   <1-2 lines from the RFC>

   ## RFC
   <rfc-path-or-url>

   ---
   _Opened by autopilot. Review and flip out of draft when ready._"
   ```

   Draft status is intentional — humans see "autopilot-originated" at a glance.

---

### Phase C: Report + self-pace

Print a structured summary so the user can scan at a glance:

```
Autopilot pass — <ISO timestamp>

READY TO MERGE (user action):
  - #<N>: <title> — <url>

IN PROGRESS:
  - #<N>: <title> — <short status>

BLOCKED:
  - #<N>: <title> — <reason>

CREATED:
  - #<N>: <title> (draft, closes #<issue>)

CAPPED (review ping-pong):
  - #<N>: <reviewer> on <file>:<line>

Next: <scheduled in Xm | not rescheduling (nothing in progress)>
```

**Self-pacing** (only when invoked via `/loop` dynamic mode, i.e. `/loop /autopilot:autopilot` with no interval):

- If any PR is in **IN PROGRESS** state (waiting on CI or expecting more reviewer input): call `ScheduleWakeup` with `delaySeconds: 900` (15 min), reason `"polling in-progress PRs"`, and pass the same `/loop /autopilot:autopilot` prompt.
- If every PR is **READY TO MERGE**, **BLOCKED**, or **CAPPED**: do **not** reschedule. There's nothing the skill can do on its own — surface the report and exit. The user re-invokes when they've acted.

When invoked with a fixed interval (`/loop 15m /autopilot:autopilot`), the interval is handled by `/loop` itself — do not call `ScheduleWakeup`.

When invoked as a one-shot (`/autopilot:autopilot` outside of `/loop`), don't call `ScheduleWakeup` either — just exit.

---

## DO / DO NOT

### DO:

- Read the linked issue **and** RFC before addressing any comment.
- Ground every reply and every fix in the RFC — quote the section when pushing back.
- Commit with descriptive messages (`fix(review): ...`).
- Open new PRs as **draft**.
- Run local tests before pushing a fix commit.
- Report clearly at the end of every pass with the status buckets.
- Skip and log when you hit a diverged branch, missing RFC, or failing test — do not guess.

### DO NOT:

- **NEVER merge a PR.** Not with `gh pr merge`, not with `glab mr merge`, not by any means. The user merges.
- **NEVER force-push.** If `git pull --ff-only` fails, skip the PR and surface it.
- **NEVER touch a PR not authored by the current user.** Phase A and B are `--author @me` only.
- **NEVER close a PR or an issue.** Only the user closes things.
- **NEVER mark a thread resolved without substance.** Either a fix commit or a reasoned reply must precede the resolve.
- **NEVER commit with `--no-verify`** to bypass hooks.
- **NEVER push to a branch that is not a PR head authored by you.** Double-check with `gh pr list --head <branch> --author @me` before pushing if unsure.
- **NEVER let scope creep.** If a reviewer suggests something outside the RFC, reply explaining and resolve — do not implement it.
- **NEVER exceed the 3-round iteration cap** on a single PR in one pass.
- **NEVER push speculative fixes when CI is red** unless the fix is directly addressing an open review comment.

## When stuck

1. Diverged branch on a PR → skip, surface, move on.
2. No RFC linked → for Phase A, proceed with issue body and flag it. For Phase B, skip — don't implement blind.
3. Bot keeps reopening the same thread → cap hit → surface and move on.
4. Tests fail on a fix attempt → revert the file, fall back to reply-with-rationale explaining the failure.
5. Auth expired mid-pass → abort cleanly with a clear message pointing to `gh auth login` / `glab auth login`.

## Platform parity notes

The SKILL is written primarily for GitHub (`gh`). GitLab (`glab`) equivalents:

| Concept              | GitHub (`gh`)                              | GitLab (`glab`)                                   |
|----------------------|--------------------------------------------|--------------------------------------------------|
| List my PRs          | `gh pr list --author @me`                  | `glab mr list --author=@me`                      |
| PR checks            | `gh pr checks <N>`                         | `glab mr view <iid>` → `.pipeline`               |
| Review threads       | GraphQL `reviewThreads`                    | `glab api .../discussions`                       |
| Resolve thread       | GraphQL `resolveReviewThread` mutation     | `PUT .../discussions/<id>?resolved=true`         |
| Reply on thread      | `gh api .../comments/<id>/replies`         | `POST .../discussions/<id>/notes`                |
| Create draft PR      | `gh pr create --draft`                     | `glab mr create --draft`                         |

GitLab self-hosted is out of scope for v1 — only gitlab.com.

## Recommended invocation patterns

- **Continuous (self-paced):** `/loop /autopilot:autopilot` — skill schedules its own next tick only when there's in-progress work.
- **Continuous (fixed interval):** `/loop 15m /autopilot:autopilot` — `/loop` ticks regardless of state.
- **One-shot:** `/autopilot:autopilot` — single pass, then exit.
