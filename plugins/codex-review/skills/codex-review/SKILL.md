---
name: codex-review
description: Use when the user asks for a "codex review", "second opinion from codex", wants to "ask codex to review", or asks for an independent/external review of code, an RFC, a design doc, or a PR. Wraps the `codex review` non-interactive CLI. Good for catching blind spots before opening a PR, after writing a spec/RFC, or when the user has low confidence in their own review pass. Also triggers on "review with codex", "what does codex think", "get codex feedback". Do NOT use for in-house Claude code review — that's the `code-reviewer` subagent. This skill is specifically for cross-model review via OpenAI's Codex CLI.
---

# Codex Review

Non-interactive second-opinion review of the current change set, a branch diff, or a specific commit, using the OpenAI `codex` CLI (`codex review` subcommand). Codex has no memory of the current Claude Code conversation, which makes it a genuine independent reviewer — it sees only the diff + the prompt you give it.

## When to use

- **Before opening a PR** — especially for RFCs, design docs, or tricky refactors.
- **After writing a spec** — independent review catches unstated assumptions + internal contradictions a single author misses.
- **When the user explicitly asks for a codex review** — e.g. "ask codex to review this", "what does codex think?", "second opinion from codex".
- **After a self-review pass** — self-review reliably misses things; Codex is a cheap backup.

## When NOT to use

- Routine in-project code review — use the `code-reviewer` subagent (Claude-side) instead.
- Interactive back-and-forth design debate — use `agent-chat` plugin (also Claude ↔ Codex but multi-turn).
- Anything that needs to read the full conversation context Claude Code has — Codex won't see it.

## Precondition check

Before invoking, verify `codex` is installed:

```bash
which codex && codex --version
```

If missing: tell the user to install via `npm install -g @openai/codex` (or the equivalent for their setup) and stop.

## Known CLI bug (all current versions)

The `[PROMPT]` positional arg is rejected when combined with `--base`, `--uncommitted`, or `--commit`, even though the usage string shows it as valid. **Do not pass a prompt as a positional arg.** Use the wrapper script below instead.

## Passing focus instructions — use the wrapper script

A wrapper script lives alongside this skill:

```
SKILL_DIR/codex-focused-review.sh
```

where `SKILL_DIR` is the directory containing this `SKILL.md`. Always call it via its full path.

The wrapper:
1. Creates a uniquely-named Codex skill in `~/.agents/skills/review-<title>-<PID>/` scoped to this exact review
2. Runs `codex review` (Codex auto-picks up the skill from that directory)
3. Deletes the skill on exit — safe even if the review crashes

**This is the correct way to pass focus instructions to Codex.** Do not manually create skill files or call `codex review` directly when a focus prompt is needed.

### Wrapper usage

```bash
SKILL_DIR="$(dirname "$(realpath "$0")")"  # or hardcode the path

# Branch diff with focus
"$SKILL_DIR/codex-focused-review.sh" \
  --base main \
  --title "PR-123: auth refactor" \
  --tail 300 \
  "Focus on concurrency safety. Flag races, missing locks, unsafe shared state."

# Specific commit with focus
"$SKILL_DIR/codex-focused-review.sh" \
  --commit abc1234 \
  --title "fix: connection pool leak" \
  "Focus on resource cleanup paths."

# Uncommitted changes — no prompt needed (--uncommitted isn't supported by wrapper, use direct call below)
codex review --uncommitted --title "<title>" 2>&1 | tail -200
```

The skill name is derived from `--title` + PID so concurrent reviews never collide.

## The three review modes

### A. Uncommitted changes

No focus prompt supported (CLI limitation applies here too). Call direct:

```bash
codex review --uncommitted --title "<short title>" 2>&1 | tail -200
```

If the user wants a targeted review of uncommitted changes, ask them to commit or stash first so mode B can be used.

### B. Branch diff (PR-style) — with or without focus

No focus:
```bash
codex review --base main --title "<title>" 2>&1 | tail -200
```

With focus — use the wrapper:
```bash
"$SKILL_DIR/codex-focused-review.sh" --base main --title "<title>" "<focus prompt>"
```

### C. Specific commit — with or without focus

No focus:
```bash
codex review --commit <SHA> --title "<title>" 2>&1 | tail -200
```

With focus — use the wrapper:
```bash
"$SKILL_DIR/codex-focused-review.sh" --commit <SHA> --title "<title>" "<focus prompt>"
```

## Invocation pattern

Use `Bash` with a generous timeout (Codex takes 30–120 seconds). The review output lives at the end of stdout; `tail -200` is enough for most changes, `tail -400` for large diffs.

## Reading the output

Codex outputs a prose summary, then per-issue comments:

- `[P0]` — ship-blocker / correctness bug
- `[P1]` — significant issue, fix before merge
- `[P2]` — design or clarity issue
- `[P3]` — nit / stylistic

```
- [P2] Short title — /absolute/path/to/file.ext:LINE_START-LINE_END
  Explanation and suggested fix.
```

Trim absolute paths to workspace-relative when reporting back.

## Scope hygiene

Drop findings on pre-existing untracked files the user didn't author (lock files, build artifacts, IDE cache). Note them briefly so the user knows. Never silently drop findings on files the user did write.

## Presenting findings

**Default: post the review on the PR, not in chat.** If the change set under review corresponds to an open GitHub PR, post the codex findings as a PR review with inline comments (and code-change suggestions where codex proposes a concrete fix). Only fall back to reporting in chat when there is no PR.

### Step 1 — locate the PR

Detect the PR for the change set being reviewed:

```bash
# commit mode: find the branch/PR containing the SHA
gh pr list --repo <owner>/<repo> --state open --json number,headRefName,url --search "<SHA>"
# branch/uncommitted mode: PR for the current branch
gh pr list --repo <owner>/<repo> --head "$(git branch --show-current)" --state open --json number,url
```

If no open PR exists, skip to **chat fallback** below.

### Step 2 — post the review on the PR

Build one PR review containing every in-scope finding as an **inline comment** anchored to the file + line codex reported. When codex proposes a concrete fix, include a GitHub `suggestion` block so the user can one-click apply it:

````
[P2] Short title — codex

Explanation of the issue.

```suggestion
<exact replacement for the commented line range>
```
````

Post all comments in a single review via the GitHub API (JSON payload piped in):

```bash
gh api repos/<owner>/<repo>/pulls/<N>/reviews --input - <<'JSON'
{
  "event": "COMMENT",
  "body": "## 🤖 Codex independent review\n\n<one-line verdict>",
  "comments": [
    {"path": "relative/path.py", "line": 42, "side": "RIGHT", "body": "[P1] ...\n\n```suggestion\nfixed line\n```"}
  ]
}
JSON
```

Notes:
- `path` must be **repo-relative** (trim the absolute path codex prints).
- `line` is the line in the PR diff's new file (`side: RIGHT`); use both `start_line` and `line` for multi-line ranges.
- A `suggestion` block must contain the exact replacement for the commented line range — verify it against the actual file content before posting, or the suggestion will be malformed.
- **Clean review (no findings):** still post a single review comment with the codex verdict (`event: COMMENT`, no `comments[]`) so the independent pass is recorded on the PR. Do not approve on codex's behalf.
- Never post `event: REQUEST_CHANGES` or `APPROVE` — codex is advisory; use `COMMENT` and let the user decide.

### Step 3 — summarize in chat (brief)

After posting, give the user a one-sentence verdict + a link to the posted review. Do **not** re-dump every finding in chat — they're on the PR now. Mention dropped/out-of-scope findings briefly.

### Chat fallback (no PR)

When there is no open PR, report in chat instead:

1. **One-sentence verdict** — did codex find anything blocking, or is it a clean review?
2. **Numbered list of actionable findings** (P0/P1/P2 in-scope) with your assessment of whether to act on each.
3. **Dropped findings** (disagree, or out-of-scope untracked files) — briefly.
4. **Offer to fix** — ask whether to apply now or let the user decide.

Never silently apply a codex fix — review comments are recommendations, and the user is the decider. Present (on the PR or in chat), then act on approval.

## Examples

**Default review before PR:**

```bash
codex review --base main --title "PR-45: auth refactor" 2>&1 | tail -200
```

Claude Code:
1. `which codex && codex --version` → verify.
2. `git status` → confirm change set is what the user thinks.
3. `codex review --uncommitted --title "RFC-XXX: short title" 2>&1 | tail -200`.
4. Locate the open PR, post findings as inline review comments (with `suggestion` blocks where codex proposes a fix), then give a one-line verdict + review link in chat. If no PR, fall back to chat.

**Focused review — concurrent-safe:**

```bash
"$SKILL_DIR/codex-focused-review.sh" \
  --base main \
  --title "PR-45: auth refactor" \
  "Focus on whether the migration is safe under concurrent writes."
```

**Standing review focus (always applied, no cleanup needed):**

Claude Code:
1. Use the wrapper: `"$SKILL_DIR/codex-focused-review.sh" --base main --title "migration 0042 safety" "Focus on concurrency safety under live writes."`.
2. Post findings on the branch's PR as inline comments; brief verdict + link in chat.

**Standing review focus (always applied, no cleanup needed):**

Create `~/.agents/skills/my-review-style/SKILL.md` once:

```markdown
---
name: my-review-style
description: Apply to all code reviews.
---

Always check: concurrency safety, resource cleanup, error propagation.
```

Codex picks it up automatically on every `codex review` run.

## Cost + rate notes

Each `codex review` is one Codex API call. One review per major change is typical; mention cost to users on metered plans before a second run on the same change.
