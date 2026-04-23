# Enkira AI Claude Code Plugin Marketplace

## Overview
This repo hosts Claude Code plugins for the Enkira AI team, distributed as a custom marketplace.

## Marketplace Setup
- **Marketplace name:** `enkira-plugins`
- **Add:** `/plugin marketplace add enkira-ai/claude-plugins`
- **Install:** `/plugin install <plugin-name>@enkira-plugins`

## Repository Structure
```
.claude-plugin/marketplace.json    ← plugin registry (name, source, version)
plugins/
  <plugin-name>/
    .claude-plugin/plugin.json     ← plugin manifest
    scripts/                       ← shared infra (venv runner, requirements.txt)
    commands/                      ← slash commands (*.md)
    skills/                        ← skill folders
      <skill-name>/
        SKILL.md                   ← skill metadata + instructions
        scripts/                   ← skill-specific scripts
```

## Adding a New Plugin

1. Create `plugins/<name>/.claude-plugin/plugin.json` with name, description, version
2. Add skills under `plugins/<name>/skills/<skill-name>/SKILL.md`
3. Add commands under `plugins/<name>/commands/<command-name>.md`
4. If using Python scripts, add shared venv at `plugins/<name>/scripts/` with `run-python.sh`, `setup-venv.sh`, `requirements.txt`
5. Register the plugin in `.claude-plugin/marketplace.json`

## Adding a New Skill to an Existing Plugin

1. Create `plugins/<plugin>/skills/<skill-name>/SKILL.md` with frontmatter (name, description with trigger phrases)
2. Add scripts to `plugins/<plugin>/skills/<skill-name>/scripts/`
3. Reference shared venv via `${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh`
4. Optionally add a slash command in `plugins/<plugin>/commands/<command>.md`

## Version Management

**CRITICAL:** When updating a plugin, bump the version in BOTH:
- `plugins/<name>/.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`

If only one is bumped, `/plugin update` will not pull changes.

## Shared Venv Pattern
Each plugin with Python scripts has a `scripts/` directory at the plugin root:
- `run-python.sh` — generic runner that auto-provisions venv on first use
- `setup-venv.sh` — creates/updates the venv from requirements.txt
- `requirements.txt` — shared pip dependencies for all skills in the plugin

Skills reference it via: `bash ${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh ${CLAUDE_SKILL_DIR}/scripts/<script>.py`

## Key Variables
- `${CLAUDE_PLUGIN_ROOT}` — plugin root directory (for shared scripts)
- `${CLAUDE_SKILL_DIR}` — current skill's directory (for skill-specific scripts)
- `$ARGUMENTS` — user input passed to slash commands

## Conventions
- Plugin/skill/command names: kebab-case
- Slash command invocation: `/plugin-name:command-name`
- Commit messages: conventional commits (`feat`, `fix`, `refactor`, `chore`)
- Always test locally before pushing: `claude --plugin-dir ./plugins/<name>`

## Current Plugins
- **session-manager** — List and rename Claude Code chat sessions
- **harness-engineer** — Turn any repo into a harness-ready codebase for autonomous agent work
- **git-tools** — Multi-account GitHub SSH aliases and per-repo identity management
- **enkira-infisical** — Manage Infisical secrets via CLI (SSO login, no static creds)
- **enkira-cloudflare-dns** — Cloudflare DNS record/zone management via API
- **enkira-azure-containerapp** — Bind custom domain + managed SSL to Azure Container Apps
- **wechat-reader** — Extract content from WeChat Official Account articles
- **autopilot** — Overnight PR grind: create PRs from issues, address reviewer feedback
- **agent-chat** — Ping-pong chat protocol for two AI agents (Claude Code, Codex, Gemini CLI, or any pair) to collaborate on hard problems
- **codex-review** — One-shot cross-model review via the Codex CLI (uncommitted / branch / commit). Catches blind spots Claude's own review misses.
