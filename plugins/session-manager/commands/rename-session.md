---
allowed-tools: ["Bash"]
description: Rename a Claude Code session by ID without resuming it
argument-hint: <session-id> <new-name>
---

Rename a session. The user's arguments are: $ARGUMENTS

```bash
PLUGIN_DIR=$(find ~/.claude/plugins/cache -path "*/session-manager/scripts/run-python.sh" -print -quit 2>/dev/null | xargs dirname)
bash "$PLUGIN_DIR/run-python.sh" "$PLUGIN_DIR/../skills/rename-session/scripts/rename-session.py" $ARGUMENTS
```

After renaming, show a confirmation message. Do not add extra commentary.
