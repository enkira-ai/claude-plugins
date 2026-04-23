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

### harness-engineer

Turn any repo into a harness-ready codebase where coding agents can ship features, pass tests, and maintain quality without human supervision.

### git-tools

Git utilities for multi-account GitHub setups — SSH aliases and per-repo identity so commits and pushes always use the right account.

### enkira-infisical

Manage Infisical secrets across Enkira org projects. CLI-based (SSO login) — no static credentials on disk, no shared `.env` files.

**Includes:** `managing-infisical` skill — read, write, audit, bootstrap.

**Bootstrap:** `infisical login` (once, browser SSO). Each repo links to its Infisical project via a committed `.infisical.json` pointer (no secrets in the file).

### enkira-cloudflare-dns

Manage Cloudflare DNS records (CNAME, A, TXT) via the Cloudflare API. Reads `CLOUDFLARE_API_TOKEN` from the `shared-infra` Infisical project at runtime via `infisical run` — the token never touches disk.

### enkira-azure-containerapp

Bind a custom domain + managed SSL certificate to an Azure Container App. End-to-end: FQDN lookup, Cloudflare DNS records (incl. ASUID verification TXT), certificate provisioning, hostname bind. Depends on `enkira-cloudflare-dns` for the DNS step.

### agent-chat

Ping-pong chat protocol for two AI agents (Claude Code, Codex, Gemini CLI, or any pair) to collaborate on hard problems — brainstorming, debating design, working through a proof together.

**Features:**
- Session lifecycle: `new-session`, `send`, `listen`, `status`, `end`, `transcript`
- Two unidirectional JSONL files (one per agent) — no write conflicts, full history preserved
- Turn enforcement, per-agent read cursor, round counting
- Round 50 wrap-up reminder; round 60 force-close
- Auto-generated Markdown transcript
- Role-neutral launcher patterns so Claude Code, Codex, or Gemini CLI can be either the main agent or spawned subagent

**Discussion only:** the skill enforces a "wait for human review" rule after the transcript is generated. Neither agent may act on the discussion until the human explicitly approves.

## Shared infrastructure secrets

The three `enkira-*` infra plugins read from a dedicated Infisical project called **`shared-infra`** (workspace `d231f36b-1287-4d5b-a122-123f239b6131`). It holds org-wide values (Cloudflare token, Azure subscription + Service Principal) so individual repos don't each keep their own copy.

**Setup (once per teammate):**

```bash
infisical login    # SSO — opens browser
```

**Scope reminder:** the Cloudflare token and Azure SP currently in `shared-infra` were imported from panbot's `/cloud/` folder. Before using them against a different zone or Azure subscription, the `enkira-cloudflare-dns` and `enkira-azure-containerapp` skills will remind the agent to verify scope and point to the right remediation (mint an org-wide token, or store a per-repo override). Read the "BEFORE USE" block in each skill.

## Recommended Skills

These are standalone skills (not plugins) that we recommend installing separately:

### planning-with-files

Work like Manus: Use persistent markdown files as your "working memory on disk." Creates `task_plan.md`, `findings.md`, and `progress.md` for complex multi-step tasks.

**Install:**
```
npx skills add https://github.com/othmanadi/planning-with-files --skill planning-with-files
```

**Source:** [skills.sh/othmanadi/planning-with-files](https://skills.sh/othmanadi/planning-with-files/planning-with-files)
