---
name: list-sessions
description: This skill should be used when the user asks to "list sessions", "show sessions", "view past sessions", "session history", "list chats", "show my conversations", or wants to see their Claude Code chat session history.
---

# List Claude Code Sessions

Display a summary table of all Claude Code chat sessions on the current machine.

## Usage

Run the session listing script via the plugin's shared venv runner:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh ${CLAUDE_SKILL_DIR}/scripts/list-sessions.py
```

Present the output as-is — it produces a formatted markdown table with:
- **Last Access** — when the session was last active
- **Session ID** — short and full ID for resuming
- **Project** — the working directory
- **Name** — session name (set via `/rename`)
- **Last Message** — most recent user message

After displaying the table, remind the user they can resume any session with `claude --resume <session-id>`.
