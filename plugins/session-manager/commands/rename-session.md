---
allowed-tools: ["Bash"]
description: Rename a Claude Code session by ID without resuming it
argument-hint: <session-id> <new-name>
---

Rename a session using the rename script. The user's arguments are: $ARGUMENTS

Find and run the script:

```bash
SCRIPT=$(find ~/.claude/plugins/cache -path "*/session-manager/skills/rename-session/scripts/rename-session.py" -print -quit 2>/dev/null)
python3 "$SCRIPT" $ARGUMENTS
```

After renaming, show a confirmation message. Do not add extra commentary.
