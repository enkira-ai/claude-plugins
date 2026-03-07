---
allowed-tools: ["Bash"]
description: List all Claude Code chat sessions with last access date, ID, and name
---

Run the session listing script via the plugin's shared venv runner:

```bash
PLUGIN_DIR=$(find ~/.claude/plugins/cache -path "*/session-manager/scripts/run-python.sh" -print -quit 2>/dev/null | xargs dirname)
bash "$PLUGIN_DIR/run-python.sh" "$PLUGIN_DIR/../skills/list-sessions/scripts/list-sessions.py"
```

Display the output as a formatted table. Do not add commentary — just show the results.
