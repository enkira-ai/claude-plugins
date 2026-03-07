---
allowed-tools: ["Bash"]
description: List all Claude Code chat sessions with last access date, ID, and name
---

Run the session listing script. The script is located relative to this plugin's installation directory. Find the script path dynamically:

```bash
find ~/.claude/plugins/cache -path "*/session-manager/skills/list-sessions/scripts/list-sessions.py" -print -quit 2>/dev/null
```

Then execute it with `python3` and display the output as a formatted table. Do not add commentary — just show the results.
