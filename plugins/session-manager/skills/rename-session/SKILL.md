---
name: rename-session
description: This skill should be used when the user asks to "rename a session", "rename session", "change session name", "name a session", or wants to set or update the name of a Claude Code chat session without resuming it.
---

# Rename Claude Code Session

Rename any Claude Code session by ID without resuming it. Accepts full or short (8-char) session IDs.

## Usage

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rename-session.py <session-id> <new-name>
```

Display the confirmation message from the script. If the user hasn't provided a session ID or name, ask for them.

To find session IDs, use the list-sessions skill first.
