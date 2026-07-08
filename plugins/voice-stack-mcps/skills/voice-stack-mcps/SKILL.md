---
name: voice-stack-mcps
description: Set up the docs & API MCP servers our voice/telephony stack needs, for both Claude Code and Codex CLI. Covers Telnyx docs MCP, Telnyx API-actions MCP (write access — ask the user before adding), LiveKit docs MCP, and Pipecat docs (Context Hub MCP + llms.txt). Use when onboarding a coding agent, "set up telnyx/livekit/pipecat mcp", "install docs mcp", "let claude/codex search Telnyx docs", "configure MCP for codex or claude code", or a teammate is wiring their coding agent for panbot.
---

# Voice-Stack MCP Setup

Wire our coding agents (Claude Code + Codex CLI) to the vendor docs and APIs we use daily:
Telnyx (telephony), LiveKit (agents/rooms), Pipecat (voice pipelines). These give the agent
first-party search over each vendor's docs so it stops guessing at APIs.

**All servers below are remote HTTP MCPs except Pipecat (local `uvx`).** Everything is
per-user (global) so it works in every project. New MCP tools only load at agent startup —
**restart the CLI (or `/mcp` reconnect in Claude Code) after adding.**

## The servers

| Server | Endpoint / command | Auth | Add by default? |
|---|---|---|---|
| `telnyx-docs` | `https://developers.telnyx.com/mcp` | none | yes |
| `telnyx-api` | `https://api.telnyx.com/v2/mcp` | Bearer `TELNYX_API_KEY` | **ask first** — write access |
| `livekit-docs` | `https://docs.livekit.io/mcp` | none | yes |
| `pipecat-context-hub` | `uvx pipecat-ai-context-hub serve` (local) | none | yes |

**`telnyx-api` is not read-only.** It exposes `invoke_api_endpoint`, buy/port numbers, send
SMS, place calls, cost explorer — real actions that spend money and touch prod. Only add it
when the user wants the agent to *drive* Telnyx, not just read docs. **Always ask before
adding it.** The docs MCP (`telnyx-docs`) is the safe default for "search/read Telnyx docs".

## Claude Code

```bash
# docs servers (safe, no auth)
claude mcp add --scope user --transport http telnyx-docs  https://developers.telnyx.com/mcp
claude mcp add --scope user --transport http livekit-docs https://docs.livekit.io/mcp

# Pipecat Context Hub (local; build the index once, then register)
uvx pipecat-ai-context-hub@latest refresh        # ~2 min first run
claude mcp add --scope user pipecat-context-hub -- uvx pipecat-ai-context-hub serve

# API-actions server — ONLY after confirming with the user (see Telnyx API key below)
claude mcp add --scope user --transport http telnyx-api https://api.telnyx.com/v2/mcp \
  --header 'Authorization: Bearer ${TELNYX_API_KEY}'
```

Use **single quotes** around the header so the literal `${TELNYX_API_KEY}` is stored — Claude
Code expands it from the environment at connect time. Double quotes would bake the resolved
value (or empty) into `~/.claude.json`.

Verify / remove:
```bash
claude mcp list                     # health of all servers
claude mcp get  telnyx-api          # scope, status, url
claude mcp remove telnyx-api -s user
```

## Codex CLI

```bash
codex mcp add telnyx-docs  --url https://developers.telnyx.com/mcp
codex mcp add livekit-docs --url https://docs.livekit.io/mcp
codex mcp add pipecat-context-hub -- uvx pipecat-ai-context-hub serve

# API-actions server — ONLY after confirming with the user
codex mcp add telnyx-api --url https://api.telnyx.com/v2/mcp --bearer-token-env-var TELNYX_API_KEY
```

Codex reads the bearer token from the named env var — no secret in `~/.codex/config.toml`.
(`codex mcp add` rewrites/reformats `config.toml`; that's expected.)

Verify / remove:
```bash
codex mcp list
codex mcp remove telnyx-api
```

## Telnyx API key (only for `telnyx-api`)

Both CLIs read the key from the `TELNYX_API_KEY` **environment variable** — never bake the
secret into the MCP config files. The key lives in Infisical (and in panbot's `.env` after
`make sync-env`). Export it in the shell profile so both tools see it in every session:

```bash
# ~/.bashrc or ~/.zshrc
export TELNYX_API_KEY=KEY0...        # from Infisical / panbot .env
```

The env var must be present in the environment where you launch `claude` / `codex`. Confirm
`telnyx-api` shows **Connected** (Claude) / **Bearer token** auth (Codex) after a restart — a
missing or bad key fails the handshake.

## Pipecat: no-MCP fallback

If `uvx`/Context Hub isn't available, point the agent at Pipecat's bulk docs instead:
`https://docs.pipecat.ai/llms.txt` (index) and `https://docs.pipecat.ai/llms-full.txt` (full).

## Notes

- **Scope:** `--scope user` (Claude) and Codex's global config make these available in every
  project. Use `--scope project` + a committed `.mcp.json` only if a repo should ship its own.
- **Already configured?** `claude mcp get <name>` / `codex mcp list` first — re-adding errors
  or duplicates. Skip servers that are already present and connected.
- **Restart to load tools.** Tools appear as `mcp__telnyx-docs__search_telnyx`,
  `mcp__telnyx-api__invoke_api_endpoint`, etc. only after the CLI restarts.
