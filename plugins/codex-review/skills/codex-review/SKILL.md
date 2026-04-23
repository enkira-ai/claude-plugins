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

## The three review modes

Pick one based on what the user is reviewing:

### A. Uncommitted changes (most common)

Reviews staged + unstaged + untracked files. Use for "review what I just did before I commit / open a PR".

```bash
codex review --uncommitted --title "<short title describing the change>"
```

**Known limitation:** `--uncommitted` **cannot be combined with a custom [PROMPT]** — the CLI rejects it (`error: the argument '--uncommitted' cannot be used with [PROMPT]`). Use the default review prompt. If the user wants a targeted review ("focus on X"), switch to mode B (branch-based) which does accept a prompt.

### B. Branch diff (PR-style)

Reviews the diff between the current branch and a base branch. Accepts a custom prompt — use this when the user wants Codex to focus on something specific.

```bash
codex review --base main --title "<title>" "Focus on: (1) schema correctness, (2) API design smells, (3) unstated assumptions. Keep it concise, actionable, top issues not nitpicks."
```

### C. Specific commit

Reviews the diff introduced by a single commit SHA.

```bash
codex review --commit <SHA> --title "<title>" "Optional focus prompt."
```

## Invocation pattern

Use `Bash` with a generous timeout (Codex takes 30–120 seconds to think). Pipe through `tail -N` if the repo has many large files — Codex prints each file it reads before the verdict, and the review output itself lives at the end.

```bash
codex review --uncommitted --title "RFC-XXX: ..." 2>&1 | tail -200
```

For a big change set, `tail -300` or `tail -500` is safer. The actual review verdict + comments are the *last* block of output.

## Reading the output

Codex outputs a prose summary first, then per-issue comments with a priority tag:

- `[P0]` — ship-blocker / correctness bug
- `[P1]` — significant issue, should fix before merge
- `[P2]` — design or clarity issue, worth addressing
- `[P3]` — nit / stylistic

Comments have the shape:

```
- [P2] Short title — /absolute/path/to/file.ext:LINE_START-LINE_END
  Explanation of the issue and suggested fix.
```

Parse these and present them to the user as actionable items. Apply the user's judgment — Codex is a reviewer, not an authority. The file paths are absolute; trim to workspace-relative when reporting back.

## Scope hygiene

Codex will flag files it sees in the change set even if they're incidental (e.g. untracked lock files, stale build artifacts, session state). Before reporting findings:

1. Check each flagged file against what the user actually authored in this change.
2. Drop findings on **pre-existing untracked files** the user wasn't going to commit (e.g. `.claude/scheduled_tasks.lock`, `.env.local`, IDE cache dirs). Note them briefly in the summary ("codex also flagged X — ignored, pre-existing local state") so the user knows but isn't asked to act.
3. Do not silently drop findings on files the user *did* author — those are legitimate even if out-of-scope for the current task.

## Presenting findings

After `codex review` completes, give the user:

1. **One-sentence verdict** — did codex find anything blocking, or is it a clean review?
2. **Numbered list of actionable findings** (P0/P1/P2 that apply to files in-scope) with your assessment of whether to act on each.
3. **Dropped findings** (in-scope but you disagree, or out-of-scope untracked files) — briefly, so the user can override if needed.
4. **Offer to fix** — for findings the user should act on, ask whether to apply the fix now or let them decide.

Never silently apply a codex fix — review comments are recommendations, and the user is the decider. Present, then act on approval.

## Examples

**Example — pre-PR RFC review:**

User: "Can you ask codex to review this RFC before I open the PR?"

Claude Code:
1. `which codex && codex --version` → verify.
2. `git status` → confirm change set is what the user thinks.
3. `codex review --uncommitted --title "RFC-XXX: short title" 2>&1 | tail -200`.
4. Parse output, report verdict + findings, ask whether to apply fixes.

**Example — targeted review:**

User: "Codex, focus on whether the migration is safe under concurrent writes."

Claude Code:
1. Switch to branch mode: `codex review --base main --title "migration 0042 safety" "Focus exclusively on concurrency safety of the schema migration under live writes. Report: is this safe, and if not, what specifically breaks?" 2>&1 | tail -200`.
2. Report back.

## Cost + rate notes

Each `codex review` invocation is one Codex API call — free on the `codex` CLI's bundled plan, metered otherwise. Users with metered plans: mention this before invoking a second time on the same change. One review per major change is typical; spamming Codex on trivial diffs is wasteful.
