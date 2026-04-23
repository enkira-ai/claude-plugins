---
allowed-tools: ["Bash"]
description: Non-interactive second-opinion review of the current change via the Codex CLI
---

Run `codex review` against the current uncommitted change set and summarize findings for the user.

1. **Precondition** — verify codex is available:

   ```bash
   which codex && codex --version
   ```

   If missing, tell the user to install it (`npm install -g @openai/codex` or equivalent) and stop.

2. **Confirm scope** — run `git status --short` and list the files that will be included in the review. Flag any obviously out-of-scope untracked files (lock files, IDE caches) so the user knows codex will see them but the findings on those can be ignored.

3. **Run the review** — use a title that names the change concisely:

   ```bash
   codex review --uncommitted --title "$ARGUMENTS" 2>&1 | tail -300
   ```

   If `$ARGUMENTS` is empty, derive a title from the most recent commit message + current diff (e.g. the RFC filename, feature slug, or issue number the user has been working on).

   **Note:** `--uncommitted` cannot be combined with a custom prompt. If the user wants a focused review ("just check X"), switch to `codex review --base main --title "..." "<focus>"` instead.

4. **Parse + present** — codex outputs priority-tagged findings (`[P0]`/`[P1]`/`[P2]`/`[P3]`). Report to the user:
   - One-sentence verdict (clean / issues found).
   - Numbered list of actionable findings with file:line refs.
   - Dropped findings (pre-existing untracked files, out-of-scope flags) — brief mention so the user can override.
   - Offer to apply fixes, don't apply silently.

Full usage patterns (branch-based review with custom prompt, per-commit review, etc.) live in the `codex-review` skill — invoke that skill when this command isn't a clean fit.
