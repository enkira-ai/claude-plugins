# Enkira AI Claude Code Plugins

Claude Code plugin marketplace by [Enkira AI](https://github.com/enkira-ai).

## Installation

Add this marketplace to Claude Code:

```
/plugin marketplace add enkira-ai/claude-plugins
```

Then install individual plugins:

```
/plugin install session-manager@enkira-plugins
```

## Available Plugins

### session-manager

List and browse all Claude Code chat sessions on your machine.

**Command:** `/session-manager:list-sessions`

Displays a table with:
- Last access date
- Session ID (short + full)
- Project directory
- Session name / first message

Resume any session with `claude --resume <session-id>`.
