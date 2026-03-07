---
allowed-tools: ["Bash"]
description: List all Claude Code chat sessions with last access date, ID, and name
---

Run the session listing script via the plugin's venv runner. Find and execute it:

```bash
bash "$(find ~/.claude/plugins/cache -path "*/session-manager/skills/list-sessions/scripts/run.sh" -print -quit 2>/dev/null)"
```

Display the output as a formatted table. Do not add commentary — just show the results.
