---
name: list-sessions
description: This skill should be used when the user asks to "list sessions", "show sessions", "view past sessions", "session history", "list chats", "show my conversations", "rename session", "rename a session", or wants to see or manage their Claude Code chat session history.
---

# List Claude Code Sessions

Display a summary table of all Claude Code chat sessions on the current machine.

## Usage

Run the session listing script via the venv runner. The runner auto-creates a virtual environment on first use:

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/run.sh
```

Present the output as-is — it produces a formatted markdown table with:
- **Last Access** — when the session was last active
- **Session ID** — short and full ID for resuming
- **Project** — the working directory
- **Name** — session name (set via `/rename`)
- **Last Message** — most recent user message

After displaying the table, remind the user they can resume any session with `claude --resume <session-id>`.

## Setup

To manually set up or update the virtual environment:

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/setup.sh
```

Add any future pip dependencies to `${CLAUDE_SKILL_DIR}/scripts/requirements.txt` and re-run setup.

## Renaming Sessions

Rename any session by ID without resuming it:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rename-session.py <session-id> <new-name>
```

Accepts full or short (8-char) session IDs.
