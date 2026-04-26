---
name: rfc-loop
description: Use when implementing a merged RFC that needs to land as code — breaks the RFC into a single Epic + N sub-issues, runs the branch→PR→Gemini+Codex review→merge loop one chunk at a time, finishes with a report and closes the Epic. Triggers "implement RFC-00X", "let's build out RFC-00X", "start the implementation of <RFC>", and whenever an RFC-authoring session ends with "now land this". Not for one-off bug fixes or single-PR changes.
---

# RFC Implementation Loop

Playbook for turning a merged design doc (an RFC in `docs/rfc/`) into shipped code across a coherent sequence of PRs, each with its own GitHub record, each reviewed before moving to the next. Use this when "implement the RFC" is the task; don't use it for single-file changes or bug fixes.

Developed on RFC-008 (PR #113 Epic, #118 / #119 / #120 / #121 implementation PRs — see `docs/reports/2026-04-21-rfc-008-conversation-pipeline.md` for the run that shaped this skill). Assumes the existing repo workflow: `docs/plans/` for plans, `docs/reports/` for proofs-of-work, `epic` + `pipeline` + `autopilot` labels on GitHub, Gemini + (sometimes) Copilot as auto-assigned reviewers.

## When to use — and not

**Use:**
- An RFC is merged; we're about to land the code it describes.
- The work is big enough to warrant >1 PR (typically 3–6 PRs of related files).
- Reviewers should see each chunk separately; we want a linear GitHub trail.

**Do not use:**
- Fixing a single bug, tweaking a config, updating docs. Just open one PR.
- Work that crosses multiple unrelated concerns. Split it into multiple RFCs first.
- Work that's so small an Epic adds more ceremony than it saves.

## The loop in one picture

```
0. Pull main → understand RFC scope
1. superpowers:writing-plans — single master plan, N PR-sized chunks
2. Epic issue + N sub-issues (one per chunk), blocks/blocked-by linked
3. For each chunk in dependency order:
   a. git checkout main && git pull; git checkout -b feat/<rfc>-<chunk>
   b. Spawn HELD implementer subagent (Agent + name) — TDD loop, commits locally, returns when green
   b.5. Spec-reviewer subagent (fresh ctx) — verify diff matches plan + RFC; loop fixes via SendMessage if drift
   c. (Commit format spec — implementer follows, kept here for reference)
   d. Main pushes branch + opens PR
   e. Main runs codex review (Skill); polls Gemini bot ~270s
   f. Main triages findings:
        trivial nit       → main edits inline + pushes + replies
        real fix          → SendMessage held implementer → fix+commit → main pushes + replies
        push-back         → main drafts citing RFC §rejected-alternatives
        codex-only OOS    → drop silently
   g. Main merges (--squash --delete-branch); SendMessage releases implementer
   h. Next chunk → fresh implementer
4. Report under docs/reports/ + flip plan frontmatter to `status: completed`
5. Close Epic with the report link
```

Each step below is a checklist, not a narrative — follow it in order.

### Platform primitives

This skill runs in **Claude Code**. Subagent dispatch uses the `Agent` tool (with `name` for held subagents) + `SendMessage` to resume. The upstream `superpowers` skill references `sessions_spawn` — that's an OpenClaw-edition primitive and does NOT exist in Claude Code. Translate `sessions_spawn` → `Agent` mentally when reading any sub-skill called from here.

**Division of labor (the whole point of going subagent-driven):**

| Owner | Holds | Does |
|---|---|---|
| Main agent | RFC, plan, Epic + sub-issue numbers, PR numbers, review-triage state | All `gh` calls, `git push`, codex Skill invocation, push-back drafting, report + Epic close, trivial inline fixes |
| Held implementer subagent (per PR, named `rfc-00X-pr-K-impl`) | The chunk's working memory: file reads, test runs, intermediate edits | TDD loop, local commits, fix-on-review-feedback via SendMessage, hands SHA back to main |
| Spec-reviewer subagent (per PR, fresh, no name) | Just the plan + RFC + diff | Pre-PR drift check; one-shot, terminates on return |

Main never edits files in 3b–3f except for trivial nits (≤3 lines, single file). All real implementation lives in the implementer subagent so main's context survives 4–6 chunks.

---

## Step 0: Read the RFC end-to-end

Open `docs/rfc/RFC-00X-*.md`. The sections that matter for the plan:

- **§ Goals / Non-goals** — your PR scope boundary.
- **§ Proposed Design** — the file list your plan must cover.
- **§ Migration & Rollout** — often a separate PR's content.
- **§ Alternatives Considered** — the rejected-alternatives you'll cite when a reviewer (Gemini especially) suggests one.
- **§ Success Criteria** — what "done" means. Every criterion must map to a test or an operational check.

If the RFC has a PR-author placeholder like "implementation PR(s)" → you're the author.

## Step 1: Write the master plan

**Required sub-skill:** `superpowers:writing-plans`.

Output path: `docs/plans/YYYY-MM-DD-<rfc-slug>.md`. Format follows the existing convention in the repo — YAML frontmatter with `status: active`, `epic: TBD`, `sub_issues: [...]`, `rfc:`, plus the Goal / Architecture / Tech-stack header.

Key constraint: **one plan, N PR chunks** (not one plan per PR). Each chunk section has:

1. A one-line summary of what ships in that PR.
2. Files created / modified (exact paths).
3. Acceptance criteria mapping to the RFC's §Success-Criteria.
4. Checkbox task list with concrete steps — code + exact commands + expected output. No placeholders.

Chunk the work by **file-touch locality + serial dependency**, not by phase:

- If PR-B imports from PR-A's new module, PR-A must merge first. Mark `Blocked by #A` on PR-B's issue.
- If two chunks touch disjoint files, they could parallelize — but the loop runs them sequentially anyway for review cadence, so just linearize by write-side dependency.
- 3–6 chunks is the sweet spot. Fewer → PRs get too big for Gemini. More → Epic feels like a grocery list.

## Step 2: File the Epic + sub-issues

Order of operations matters — sub-issues reference the Epic, so create the Epic first, note its number, then the sub-issues, then edit the Epic to link them back.

```bash
# 1. Create Epic (label: epic).
GIT_CONFIG_SYSTEM=/dev/null gh issue create \
    --title "Epic N: RFC-00X <short name>" \
    --label epic \
    --body "$(cat epic-body.md)"
# → note the issue number (e.g. 113)

# 2. Create sub-issues (label: pipeline + autopilot typically).
#    Body MUST include "Parent: Epic #N" + dependency line.
GIT_CONFIG_SYSTEM=/dev/null gh issue create \
    --title "RFC-00X PR-1: <chunk>" \
    --label pipeline --label autopilot \
    --body "...\n## Parent\nEpic #N\n## Dependencies\nNone — unblocker for PR-2/3/4."

# ... N sub-issues total ...

# 3. Edit the Epic body to list the sub-issue numbers.
GIT_CONFIG_SYSTEM=/dev/null gh issue edit N --body "$(updated body with #A/#B/#C/#D)"

# 4. Update plan frontmatter: epic: N, sub_issues: [A, B, C, D].
```

Note the `GIT_CONFIG_SYSTEM=/dev/null` prefix — a quirk of some machines where `gh` can't read /etc/gitconfig. Drop it where not needed.

Sub-issue body template (per `Issues #114–#117` for RFC-008):

```markdown
<one-paragraph summary>

## Scope
- File A — what changes
- File B — what changes
- Tests — what's covered

## Acceptance criteria
1. <Testable>
2. <Testable>
...

## Design reference
- RFC-00X §4.1, §4.3.2
- RFC-00X §8 success criteria N

## Parent
Epic #<epic>

## Dependencies
Blocked by #<prev> / None — unblocker for the rest.
```

## Step 3: Run the loop

For each sub-issue in order:

### 3a. Branch hygiene

```bash
git checkout main && git pull origin main
git checkout -b feat/<rfc-slug>-<chunk-slug>
```

Branch naming: `feat/rfc-00X-<chunk>` (e.g. `feat/rfc-008-schema`, `feat/rfc-008-blob-db`). Matches the repo's `feat/<issue-slug>` convention.

### 3b. Spawn held implementer subagent

Main agent does NOT edit files directly here. Dispatch an implementer subagent via the `Agent` tool with a `name` so it stays addressable across review cycles in 3f:

```
Agent({
  name: "rfc-00X-pr-K-impl",
  subagent_type: "general-purpose",
  description: "Implementer for RFC-00X PR-K",
  prompt: "<full prompt — see template below>"
})
```

**Why subagent.** A typical PR's edits + test runs + intermediate file reads will burn main's context budget in one chunk. With 4–6 chunks per RFC, main has to stay clean — its job is to remember the RFC, plan, Epic, sub-issue numbers, and review verdicts across the whole loop, not the per-line state of any single PR.

**Why held (named).** The same subagent handles review-feedback cycles in 3f via `SendMessage`. Spawning fresh per fix-round loses the chunk's working memory (where things are, why they were done that way, what tests cover what). Keep it alive until 3g.

**Implementer prompt template:**

```
You are the implementer for RFC-00X PR-K (sub-issue #<sub-issue>, Epic #<epic>).

Inputs:
- Plan: docs/plans/YYYY-MM-DD-rfc-00x-*.md, chunk K
- RFC: docs/rfc/RFC-00X-*.md (esp. §<relevant sections>)
- Branch: feat/rfc-00x-<chunk-slug> (already created off main; you start on it)

Your job:
1. Read plan chunk K end-to-end before touching any file. Read the RFC sections it points to.
2. Follow TDD: for each acceptance criterion, write the failing test FIRST, run pytest to watch
   it fail, THEN implement, THEN run pytest to watch it pass. Commit after each green test.
3. Conventional-commit format. The LAST commit on the branch must include this trailer:
       Resolves #<sub-issue>
       Part of #<epic>
       Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
4. Run `source .venv/bin/activate && python -m pytest tests/ -m "not e2e" -q` before declaring done.
   If a stray test flakes, re-run once; if it still flakes, investigate — do not ignore.
5. Do NOT push and do NOT open a PR. Main agent handles all `git push` and `gh` calls so PR
   activity is attributed to a single identity.
6. Stay alive after returning — main will SendMessage you with review findings to address.

Constraints:
- Stay inside chunk K's file scope (the plan lists exact paths). No drive-by refactors.
- No new dependencies without checking pyproject.toml + requirements.txt convention.
- If the plan is ambiguous, return with a question rather than guessing — main has the RFC context.

Return when local tests are green: one paragraph — what you wrote, what tests you added, any
deviations from the plan and why. List the commit SHAs created.
```

When the subagent returns, sanity-check before moving on:

```bash
git status                          # should be clean
git log --oneline main..HEAD        # should show test-then-impl commit ordering
python -m pytest tests/ -m "not e2e" -q   # main re-runs to confirm
```

Then proceed to 3b.5.

### 3b.5. Spec-reviewer subagent (pre-PR gate)

One-shot fresh-context subagent dispatched after the implementer returns, before main opens the PR. Catches RFC drift and plan-misalignment locally — saves a Gemini round-trip.

```
Agent({
  subagent_type: "general-purpose",
  description: "Spec-review for RFC-00X PR-K",
  prompt: "<spec-reviewer prompt — see template below>"
})
```

No `name` — single-shot, terminates on return.

**Spec-reviewer prompt template:**

```
You are a spec-reviewer for RFC-00X PR-K. You did NOT write this code. You verify the diff
matches the plan and the RFC.

Inputs:
- Plan: docs/plans/YYYY-MM-DD-rfc-00x-*.md, chunk K
- RFC: docs/rfc/RFC-00X-*.md (esp. §<relevant sections>)
- Diff: run `git diff main...HEAD` to see what changed
- Commit ordering: run `git log --oneline main..HEAD`

Verify:
1. Every acceptance criterion in chunk K is covered by code or tests in the diff.
2. No scope creep — files outside chunk K's listed paths are flagged.
3. No drift from RFC §<relevant> design.
4. TDD evidence: for each non-trivial feature, a test commit precedes its implementation commit.
5. The last commit has the `Resolves #<sub-issue>` + `Part of #<epic>` trailer.

Return: pass/fail verdict, then bulleted findings with file:line refs. Skip prose nits and style
quibbles — those are Gemini's job. Focus on plan/RFC alignment.
```

Disposition:
- **Pass** → proceed to 3d (open PR). 3c is just reference; the implementer already committed.
- **Fail** → main `SendMessage`s the held implementer with the findings:
  ```
  SendMessage({
    to: "rfc-00X-pr-K-impl",
    body: "Spec-reviewer found drift before PR open. Findings:\n\n<paste findings>\n\nFix locally, commit, return SHAs. Do NOT push."
  })
  ```
  Re-run spec-reviewer if findings were substantive; spot-check if not. Loop until pass.

### 3c. Commit message format (implementer reference)

The implementer subagent follows this format. Kept here so users tweaking the implementer prompt know what to require.

Must include the `Resolves #<sub-issue>` trailer so GitHub auto-closes the sub-issue on merge, plus `Part of #<epic>` so the Epic's timeline picks up the cross-reference. Also the `Co-Authored-By` trailer if Claude Code generated the commit.

```
<type>(<scope>): <subject>

<body: WHY the change, not WHAT>

Resolves #<sub-issue>
Part of #<epic>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### 3d. Open the PR

```bash
git push -u origin feat/<branch>
GIT_CONFIG_SYSTEM=/dev/null gh pr create \
    --title "feat(<scope>): <subject>" \
    --body "$(cat pr-body.md)"
```

PR body structure: Summary bullets (what changed + why), Test plan checklist, `Resolves #<sub-issue>` + `Part of #<epic>` trailer.

### 3e. Wait for review — this is the load-bearing part

Two reviewers run in parallel: **Gemini** (auto-posts on the PR via `gemini-code-assist[bot]`) and **Codex** (independent local CLI run via the `codex-review:codex-review` skill).

**Expected latency:** Gemini posts its review 3–5 min after push. Codex review runs locally in ~30–120s. Poll Gemini via `ScheduleWakeup delaySeconds=270` — stays inside the 5-min Anthropic prompt-cache TTL, doesn't waste cache cycles. Run codex review during that wait, not after, so both review streams come in around the same time.

**Codex review** — invoke via the `Skill` tool:

```
Skill(skill="codex-review:codex-review",
      args="Review PR #<PR> commit <SHA>. Focus narrowly on: <chunk-specific concerns — "
            "schema correctness for migrations / algorithmic correctness for new logic / "
            "internal consistency vs RFC §X / anything load-bearing the chunk introduces>. "
            "Skip docs style/grammar. One bullet per finding with file:line refs.")
```

The skill wraps `codex review --commit <SHA>` (or `--base main` for branch-diff mode). It returns prose verdict + `[P0]`/`[P1]`/`[P2]`/`[P3]` findings. **Codex has caught issues Gemini missed in past PRs** — e.g. on PR #144 Codex found 3 schema-correctness bugs Gemini didn't (`conversation_fk NOT NULL` contradicting the documented real-call NULL allowance, `speaker` repurposing breaking the §13 train gate, false turn-timestamp reconstruction claim) on top of the weighted-sample SQL bug Gemini did catch. Treat its findings as authoritative for SQL/algorithm/cross-section consistency, less so for prose nits.

**Setup reminder** — if `codex` CLI is missing or the `codex-review` skill is not loaded:
- **Skill missing** (`Skill tool errors with "skill not found: codex-review:codex-review"`): tell the user to install via `/plugin` and select **codex-review** from the Enkira marketplace. Do not try to run codex without the skill — the bare CLI has parser quirks (rejects `--base` + prompt or `--commit` + prompt simultaneously) that the skill works around.
- **CLI missing** (`which codex` returns empty): the skill itself flags this and tells the user to install via `npm install -g @openai/codex` (or the equivalent for their setup). Stop and wait for them.

**Who reviews in practice:** In the cong repo, Gemini (`gemini-code-assist[bot]`) consistently reviews Python changes. Copilot auto-assignment was assumed but did NOT run during RFC-008 — don't block waiting for Copilot. YAML-only PRs often get zero review comments (saw this on PR #121 of RFC-008). Codex always runs because it's a local CLI invocation we control — no "did the bot run?" uncertainty.

**What to check each poll:**
```bash
GIT_CONFIG_SYSTEM=/dev/null gh pr checks <PR>
GIT_CONFIG_SYSTEM=/dev/null gh pr view <PR> --json reviews,reviewDecision,mergeable
GIT_CONFIG_SYSTEM=/dev/null gh api repos/<owner>/<repo>/pulls/<PR>/comments \
    --jq '.[] | {id, user: .user.login, body: .body[0:300], path, line}'
```

If CI is still pending, schedule another 180s poll. If CI green but no Gemini review yet, give it 2–3 more minutes — Gemini sometimes lags CI by a minute. Codex output is in your local skill-tool result, not on the PR.

### 3f. Address review comments

Main agent triages. Held implementer subagent (from 3b) handles the actual fixes for non-trivial findings via `SendMessage`. Trivial nits stay in main to avoid dispatch overhead. Push-backs stay in main because they need RFC context.

Merge findings from Gemini (PR comments) + Codex (skill output) + spec-reviewer leftover (rare). Dedupe — sometimes multiple reviewers flag the same bug.

**Triage routing** for each unique finding:

1. **Trivial nit** (typo, import order, doc word, single-line cleanup, ≤3 lines, single file) → main agent edits inline + commits + pushes + replies to Gemini. Faster than a subagent round-trip. Bound: if you find yourself thinking more than ~30 seconds about the fix, it's not trivial — route to the implementer.
2. **Real fix** (logic, schema, test gap, multi-file, anything non-obvious) → `SendMessage` to held implementer:

   ```
   SendMessage({
     to: "rfc-00X-pr-K-impl",
     body: "Review feedback to address:\n\n<paste Gemini comment(s) and/or Codex finding(s) with file:line refs>\n\nFor each finding:\n1. Make the fix. Keep it minimal — no drive-by edits.\n2. Run pytest -m \"not e2e\" -q to confirm green.\n3. Commit with fix(<scope>): <subject> or refactor(...). Do NOT amend.\n4. Do NOT push — return the commit SHA + one-line rationale per finding. I'll push and post the Gemini reply (keeps PR identity consistent).\n\nIf a finding seems wrong or conflicts with RFC §X, do NOT silently push back — return your concern and I'll handle the PR comment myself (RFC context is in my window, not yours)."
   })
   ```

   Implementer returns SHA(s). Main runs `git push` and posts the Gemini reply with the SHA.
3. **Push back.** Main agent drafts. Push-backs need RFC rejected-alternatives context, which lives in main. RFC-008 PR-2's "extract the Allen mapping into a config file" is the template:
   > Pushing back on this one. The 4-row hardcoding is intentional and mirrors the VALUES literal in alembic 0004's Path-B backfill (RFC-008 §4.1.2). A config file would introduce a separate moving part that must stay in sync with the migration — the rejected-alternative in §4.1.2. Expanded the docstring in `<sha>` to make the design choice explicit.

   If the push-back also requires a small docstring expansion or comment, route the docstring change to the implementer via SendMessage (route 2), then post the Gemini reply citing both the rationale and the SHA.
4. **Drop (codex only).** Sometimes codex flags pre-existing untracked files or out-of-scope concerns — drop those silently per the codex-review skill's "scope hygiene" rules. Do not echo them on the PR.

Reply to Gemini comments via the pull-request-comment reply API, not a new top-level comment:

```bash
GIT_CONFIG_SYSTEM=/dev/null gh api \
    repos/<owner>/<repo>/pulls/<PR>/comments/<comment-id>/replies \
    -f body="Fixed in <sha>. <reason>."
```

Codex findings have no PR thread to reply to. Bundle the codex-derived fixes into the same fix commit(s), then post a single PR-level comment summarizing the codex findings + how they were addressed (use `gh pr comment <PR> --body`). This makes the codex contribution visible to human reviewers without forcing a per-finding thread. Template (PR #144 set the precedent):

```
Addressed in <sha>. Combined gemini-code-assist + codex independent review (`codex review --commit <SHA>`); N findings, all fixed:

1. **[P1] <short title>** (gemini + codex). <what was wrong>. <how fixed>.
2. **[P2] <short title>** (codex). <what was wrong>. <how fixed>.
…
```

Do not squash the fix commit into the original. Keep the review trail visible in the PR history; the squash-merge collapses it at merge time.

### 3g. Merge

After the last fix pushes, wait ~180s for CI re-run on the new commit. When pytest + to-review + (unblock skipping) are all green and every review comment has a reply:

```bash
GIT_CONFIG_SYSTEM=/dev/null gh pr merge <PR> --squash --delete-branch
git checkout main && git pull origin main
```

`--squash` is the repo's convention — matches the `feat: ... (#PR)` commit style in main's log. `--delete-branch` cleans up the remote branch.

**LFS warning caveat.** `gh pr merge` sometimes emits `This repository is configured for Git LFS but 'git-lfs' was not found on your path`. This is a harness warning, NOT a merge failure. Confirm by `gh pr view <PR> --json state,mergedAt` — `state: MERGED` means the remote merge went through; the local checkout is just unhappy.

**Release the held implementer.** Once merge is confirmed, terminate it:

```
SendMessage({
  to: "rfc-00X-pr-K-impl",
  body: "PR #<PR> merged. You're done — thanks. Terminate."
})
```

Do NOT reuse this implementer for the next chunk. Each chunk gets a fresh implementer in 3b so its context starts clean. The next chunk's code likely depends on this PR's code now sitting on main — fresh context picks that up via file reads, no stale assumptions from PR-K's working memory.

### 3h. Next chunk

Back to 3a with the next sub-issue. Pull main first — your previous PR's changes are now on main. Fresh implementer subagent (new `name`, e.g. `rfc-00X-pr-K+1-impl`) for 3b.

## Step 4: Report + plan frontmatter

After the last PR merges:

```bash
# Write the report. Template: see docs/reports/2026-04-21-rfc-008-conversation-pipeline.md.
# Required sections:
#   - Header: Epic, RFC, plan, date, outcome
#   - "What shipped" table linking every PR → sub-issue
#   - Per-chunk paragraph: what landed, what tests were added
#   - Test-suite delta (before → after count, must be green)
#   - Code-review observations — anything that would update THIS skill
#   - Out-of-scope follow-ups (cite the RFC §)
```

Then flip the plan frontmatter:

```yaml
---
status: completed
epic: <N>
sub_issues: [A, B, C, D]
prs: [PA, PB, PC, PD]
rfc: docs/rfc/RFC-00X-*.md
report: docs/reports/YYYY-MM-DD-rfc-00x-*.md
---
```

Commit both in a single `docs(rfc-00X): completion report + flip plan to completed` commit to main.

## Step 5: Close the Epic

```bash
GIT_CONFIG_SYSTEM=/dev/null gh issue close <epic> --comment "$(cat <<'EOF'
All N implementation PRs merged. Report: [docs/reports/...](...).

- #<sub-A> / #<PR-A> — <chunk A>
- #<sub-B> / #<PR-B> — <chunk B>
- ...

Test suite: X → Y tests, all green. Out-of-scope follow-ups tracked separately per RFC-00X §9.
EOF
)"
```

Any "supersedes" PR (e.g. RFC-008 supersedes PR #46) gets closed with a pointer comment citing the merged-implementation PR + the RFC. Do this after the last PR merges, not before. `gh pr close` on an already-closed PR returns an error — treat that as a benign no-op.

---

## Common failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `gh` returns "unknown error occurred while reading the configuration files" | /etc/gitconfig unreadable by the harness | Prefix every `gh` call with `GIT_CONFIG_SYSTEM=/dev/null` |
| `gh pr merge` emits "git-lfs not found" but never returns | LFS post-merge hook can't run | Harmless. Verify with `gh pr view --json state,mergedAt` — MERGED means the remote merge succeeded |
| Gemini never reviews | Repo has only YAML / docs / CI in the PR, or rate-limit | Wait 5 min total; if still nothing, proceed to merge as long as Codex review came back clean. Note in the report |
| Codex skill not loaded (`Skill tool errors with "skill not found"`) | `codex-review` plugin not installed | Tell user to install via `/plugin` from the Enkira marketplace; do not bypass with raw `codex review` (CLI flag/prompt parser is buggy — skill works around it). Stop until installed |
| Codex CLI missing (`which codex` empty) | `@openai/codex` not installed locally | The codex-review skill itself surfaces this with install instructions (`npm install -g @openai/codex`). Stop until installed |
| Codex flags pre-existing untracked file | `.claude/scheduled_tasks.lock`, `.env.local`, IDE cache, etc. surfaced from working tree | Drop silently per the codex-review skill's "scope hygiene" rules. Mention in summary so the user can override but do not echo on the PR |
| New test flakes but only after my PR-N tests ran | monkeypatch env leak into a later test that relies on DEFAULT_DATABASE_URL | Re-run the flake in isolation. If still fails, fix the leak. If passes, likely a transient — note it |
| Reviewer suggests what RFC §X already rejected | Normal — reviewers don't read the RFC | Push back with the rejected-alternative citation (see 3f template). Expand the docstring so the next reviewer sees it too |
| Image rebuild didn't pick up a new `requirements.txt` package | `build-pipeline-image.yml` didn't trigger — PR path didn't match | Check the workflow's `on.push.paths` filter; add `requirements.txt` to it if missing |
| Alembic migration fails in Path-B test but passes Path-A | Legacy DB state from a previous test run still in the testcontainer | Drop conversation tables + stamp `alembic_version` back to parent revision manually; don't rely on `alembic downgrade` if the migration refuses Path-B downgrade |
| Held implementer subagent context bloats after 5+ review rounds | Each SendMessage round adds context | Spawn fresh implementer with `git diff main...HEAD` + remaining unaddressed findings in prompt; release the bloated one with a "you're done" SendMessage |
| Implementer skipped TDD (impl commit before test commit) | Subagent didn't follow the prompt, or chunk had non-test-coverable change | Spec-reviewer in 3b.5 catches this via `git log --oneline main..HEAD` ordering check. If it slips through, SendMessage the implementer to back-fill the test before opening the PR — do not paper over by adding the test in main |
| `Agent` tool name collision (subagent already running with that name) | Previous chunk's implementer was not released in 3g | Use a unique suffix per chunk: `rfc-00X-pr-K-impl-v2`, OR send the prior name a "terminate" SendMessage first. Preferred: always release in 3g so the slot is free |
| `sessions_spawn` referenced anywhere | Cargo-culted from upstream `superpowers` SKILL | Claude Code uses `Agent` + `SendMessage`; `sessions_spawn` is OpenClaw-edition only. Translate mentally when reading sub-skills called from here |
| Implementer pushed branch / opened PR / posted Gemini reply | Subagent ignored the "main owns gh + git push" rule | Reset PR identity if needed (rare). Re-prompt implementer to return SHAs only. The rule exists so PR comment authorship stays consistent and main has the success signal directly |
| Main agent finds itself reading source files during 3f to "understand the fix" | Drifting into implementer's job — main's context is meant to stay clean | Stop reading. SendMessage the implementer with the finding text verbatim; let it fix. If main is reading files, it's no longer just a project manager |

## What this skill is NOT

- It is not "how to write an RFC." That's the prior step — use a brainstorming/design session, not this skill.
- It is not "run all PRs in parallel." Serial is the point; linear GitHub trail is the deliverable.
- It is not "skip reviews to ship faster." Every PR waits for Gemini (or 5 min, whichever comes first). The minute spent waiting is the minute the reviewer is looking.
- It is not a replacement for `superpowers:writing-plans`. This skill calls that sub-skill in Step 1.
