# Harness Engineering Research Report

> Synthesized from 5 sources to inform the `harness-engineer` plugin design.
> Created: 2026-03-19

---

## 1. The Problem

Coding agents fail in predictable ways when working on long-running tasks across multiple context windows:

1. **One-shotting** — agent tries to build everything at once, runs out of context mid-feature, leaves broken half-implemented code
2. **Premature completion** — agent declares victory without proper end-to-end testing
3. **Context loss** — next session can't figure out what happened, wastes tokens re-discovering state
4. **Architectural drift** — without enforced boundaries, code quality degrades as agents replicate bad patterns

**Harness engineering** is the discipline of designing environments, scaffolding, and feedback loops that solve these problems — enabling agents to do reliable work without human supervision.

---

## 2. Sources Analyzed

### 2.1 Anthropic — "Effective harnesses for long-running agents" (Nov 2025)

**URL:** https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
**Companion code:** https://github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding

**Core pattern: Initializer + Coding Agent**

Two-part solution using Claude Agent SDK:
- **Initializer agent** (first session only): Creates `init.sh`, `claude-progress.txt`, feature list, initial git commit
- **Coding agent** (every subsequent session): Makes incremental progress, leaves structured updates

**Key artifacts:**
- `features.json` — 200+ granular features with pass/fail status, JSON format (less likely to be improperly edited vs markdown)
- `claude-progress.txt` — session progress log, read at start of every session
- `init.sh` — dev environment setup, run at start of every session
- Git commits with descriptive messages after each feature

**Session protocol:**
1. `pwd` → see working directory
2. Read progress file + git log → understand current state
3. Read feature list → pick highest-priority incomplete feature
4. Run `init.sh` → start dev server
5. Basic e2e test → verify clean state before new work
6. Implement one feature → test → commit → update progress

**Critical finding on testing:** Agents consistently marked features complete without proper verification. Only when given browser automation tools (Puppeteer MCP) could they identify bugs not obvious from code alone. End-to-end testing tools were "dramatic" improvement.

**Failure modes and solutions table:**

| Problem | Initializer Solution | Coding Agent Solution |
|---------|---------------------|----------------------|
| Declares victory too early | Feature list file | Read feature list, pick one task |
| Leaves broken state | Git repo + progress file | Read progress + git log, run basic test first |
| Marks features done prematurely | Feature list file | Self-verify, only mark passing after testing |
| Wastes time figuring out how to run app | Write `init.sh` | Read and run `init.sh` |

---

### 2.2 OpenAI — "Harness engineering: leveraging Codex in an agent-first world" (2026)

**URL:** https://openai.com/index/harness-engineering/

**Context:** Team built a product with **0 lines of manually-written code** over 5 months. ~1M lines of code, ~1,500 PRs, 3.5 PRs/engineer/day. "Humans steer. Agents execute."

**Key insight: AGENTS.md as table of contents, not encyclopedia**

They tried the "one big AGENTS.md" approach and it failed:
- Context is scarce — giant instruction file crowds out the actual task
- Too much guidance becomes non-guidance — when everything is important, nothing is
- It rots instantly — stale rules, no one maintains it
- Hard to verify — no mechanical freshness checks

**Solution: Progressive disclosure**

```
AGENTS.md          ← ~100 lines, map/table of contents
ARCHITECTURE.md    ← top-level codebase map
docs/
├── design-docs/   ← indexed, with verification status + core beliefs
├── exec-plans/    ← active/ + completed/ + tech-debt-tracker.md
├── generated/     ← db-schema.md, etc.
├── product-specs/ ← indexed feature specs
├── references/    ← external docs, llms.txt files
├── DESIGN.md
├── FRONTEND.md
├── PLANS.md
├── QUALITY_SCORE.md
├── RELIABILITY.md
└── SECURITY.md
```

Agents start with small stable entry point, taught where to look next.

**Enforced mechanically:** Linters and CI validate docs are up-to-date, cross-linked, structured correctly. "Doc-gardening" agent scans for stale docs and opens fix-up PRs.

**Architectural enforcement:**

Rigid layered domain architecture: Types → Config → Repo → Service → Runtime → UI. Cross-cutting concerns enter through single explicit interface (Providers). Enforced with custom linters + structural tests.

> "This is the kind of architecture you usually postpone until you have hundreds of engineers. With coding agents, it's an early prerequisite."

Custom lint error messages serve as **remediation instructions injected into agent context** when something fails.

**Application legibility:**
- App bootable per git worktree — each agent gets isolated instance
- Chrome DevTools Protocol wired into agent runtime — DOM snapshots, screenshots, navigation
- Full observability stack per worktree — logs (LogQL), metrics (PromQL), traces (TraceQL)
- Agents regularly work 6+ hours on single tasks

**Entropy and garbage collection:**
- "Golden principles" encoded in repo
- Recurring cleanup process — background Codex tasks scan for deviations, update quality grades, open refactoring PRs
- "Technical debt is like a high-interest loan" — pay it down continuously

**Key quote:**
> "From the agent's point of view, anything it can't access in-context while running effectively doesn't exist. Knowledge that lives in Google Docs, chat threads, or people's heads are not accessible to the system."

---

### 2.3 Mario Zechner — pi-agent blog (Nov 2025)

**URL:** https://mariozechner.at/posts/2025-11-30-pi/
**Code:** https://github.com/badlogic/pi-mono

**Philosophy: Minimalism works**

Built a complete coding agent (pi) with:
- **System prompt: ~1000 tokens** (vs Claude Code's ~10,000+)
- **4 tools:** read, write, edit, bash
- **No built-in todos, plan mode, MCP, background bash, or sub-agents**

Scored competitively on Terminal-Bench 2.0 against Claude Code, Codex, Cursor, Windsurf.

**Key argument: File-based state over built-in features**

| Built-in Feature | pi's Alternative |
|-----------------|-----------------|
| Plan mode | Write a `PLAN.md` file |
| Todo tracking | Write a `TODO.md` with checkboxes |
| Sub-agents | Run `pi --print` via bash |
| MCP servers | CLI tools with README files |
| Background bash | tmux |

**Rationale:** Built-in features add hidden state the model must track, reducing reliability. File-based artifacts are visible, versionable, and persistent across sessions.

**On sub-agents:** "Using a sub-agent mid-session for context gathering is a sign you didn't plan ahead. If you need to gather context, do that first in its own session."

**On context engineering:** "Exactly controlling what goes into the model's context yields better outputs. Existing harnesses make this extremely hard or impossible by injecting stuff behind your back."

**On MCP:** Token overhead is massive — Playwright MCP dumps 13.7k tokens into every session. Alternative: CLI tools with README files, agent reads README on demand (progressive disclosure), invokes tool via bash.

---

### 2.4 "WTF is Harness Engineering" (YouTube transcript)

**URL:** https://www.youtube.com/watch?v=kJPvfoLtFFY

**Three pillars of harness engineering:**

1. **Legible environment** — each session/sub-agent can quickly understand where things are at. Documentation system + structured artifacts that encode project state.

2. **Verification is critical** — faster feedback loops dramatically improve output quality. Give models tools to verify their own work (browser automation, test runners, observability).

3. **Trust the model with generic tools** — Vercel case study: deleted specialized text-to-SQL tools, replaced with single bash tool. Result: 3.5x faster, 37% fewer tokens, success rate 80% → 100%. Models are trained on billions of tokens of bash/grep/npm — they understand these natively. Bespoke tool-calling JSON is unfamiliar.

**On OpenClaw:** "Real difference is that OpenClaw represents this type of always-on long-running fully autonomous agent... created by a fairly simple architecture where it has memory context layer with a trigger and cron job to autonomously take actions."

**Paradigm shift:** Moving from co-pilot (human drives) to autonomous agent (agent drives, human steers). The model is more powerful than you think — the bottleneck is the system design around it.

---

### 2.5 OpenAI Symphony (SPEC + reference implementation)

**URL:** https://github.com/openai/symphony
**SPEC:** 2,175-line language-agnostic specification

**What Symphony is:** A long-running orchestration service that polls an issue tracker, dispatches coding agents to isolated workspaces, and manages their lifecycle.

**Architecture (8 components):**

1. **Workflow Loader** — reads `WORKFLOW.md` (frontmatter config + Liquid-templated prompt)
2. **Config Layer** — YAML config for polling, concurrency, agent settings
3. **Issue Tracker Client** — Linear integration (adapter pattern for other trackers)
4. **Orchestrator** — polling loop, concurrency management, retry with exponential backoff
5. **Workspace Manager** — creates isolated git worktrees per issue, before/after hooks
6. **Agent Runner** — executes Codex turns, handles multi-turn continuation
7. **Status Dashboard** — real-time terminal UI showing agent status
8. **Logging** — structured logging with token accounting

**Key design patterns:**

- **Workspace isolation:** Each issue gets its own git worktree clone. Agents work in parallel without conflicts. Workspaces are cleaned up after completion.
- **Multi-turn continuation:** After a Codex turn completes, checks if issue is still active. If yes, sends continuation prompt and starts another turn (up to `max_turns`).
- **Before/after hooks:** Shell scripts run before and after each agent run. Used for environment setup/teardown.
- **WORKFLOW.md:** Liquid template with access to issue fields (`{{ issue.title }}`, `{{ issue.description }}`). Separates orchestration config from prompt content.

**Critical limitation:** Hardwired to Codex's JSON-RPC protocol (`initialize`, `thread/start`, `turn/start`, approval requests). Cannot manage Claude Code without a new protocol adapter.

**Relationship to harness engineering:**
> "Symphony works best in codebases that have adopted harness engineering. Symphony is the next step — moving from managing coding agents to managing work that needs to get done."

Symphony assumes the harness exists. It doesn't create scaffolding — it dispatches agents to repos that already have it.

---

## 3. Converged Best Practices

All five sources agree on these patterns:

### 3.1 File-based state over ephemeral state
Every source uses files as the primary state mechanism: features.json, progress.txt, PLAN.md, WORKFLOW.md, AGENTS.md. Files survive context window boundaries, are version-controlled, and are inspectable by humans and agents alike.

### 3.2 Incremental progress with clean commits
Never try to do everything at once. One feature → test → commit → progress update. Each commit should be merge-ready.

### 3.3 Progressive disclosure
Don't dump everything into context. Provide a map (CLAUDE.md / AGENTS.md) and let agents read deeper docs on demand. Token budget is precious.

### 3.4 Verification before completion
Agents will claim things work when they don't. Give them tools to actually verify (test runners, browser automation, observability) and instruct them to only mark features complete after verification.

### 3.5 Generic tools over specialized tools
bash, read, write, edit — models understand these natively. Specialized tools add overhead and fragility. When possible, wrap functionality as CLI tools with README files rather than MCP servers or custom tool schemas.

### 3.6 Enforced boundaries, not micromanaged implementations
Set architectural rules (dependency directions, naming conventions, lint rules) and enforce them mechanically. Within those boundaries, give agents freedom.

### 3.7 Workspace isolation for parallelism
When running multiple agents, each gets its own git worktree. No shared mutable state between concurrent agents.

---

## 4. Architecture Decision: Symphony vs Direct Dispatch

### Symphony's value
- Orchestration primitives (polling, concurrency, retry, multi-turn)
- Issue tracker integration
- Status dashboard

### Why not use Symphony directly
- Hardwired to Codex JSON-RPC protocol
- Requires Elixir runtime
- Linear-specific (though adapter pattern exists)
- Overkill if OpenClaw already has trigger/cron/dispatch capabilities

### Recommended: Extract patterns, don't adopt the service

For an OpenClaw agent managing Claude Code:

```
OpenClaw (always-on orchestrator)
  ├── Trigger: new task arrives (webhook, cron, user request)
  ├── git worktree add .worktrees/<task-id> -b task/<task-id>
  ├── claude --print --output-format stream-json \
  │     -p "Follow harness-work protocol for feature #N" \
  │     --cwd .worktrees/<task-id>
  ├── Monitor output, retry on failure (max 3 attempts, exponential backoff)
  ├── On success: merge worktree, cleanup
  └── Report results
```

This gives Symphony's orchestration benefits without the Codex/Elixir/Linear dependencies.

---

## 5. What We Built

The `harness-engineer` plugin implements the **harness layer** (making repos agent-ready), not the orchestration layer (dispatching agents). It has three skills:

| Skill | Maps to | Source inspiration |
|-------|---------|-------------------|
| `harness-init` | Anthropic's initializer agent | Anthropic blog, OpenAI blog |
| `harness-work` | Anthropic's coding agent | Anthropic blog, pi-agent, video |
| `harness-audit` | OpenAI's doc-gardening agent | OpenAI blog |

The orchestration layer (dispatching agents to harness-ready repos) remains the responsibility of the caller — whether that's OpenClaw, Symphony, cron, CI, or a human running `/harness-work`.

---

## 6. Open Questions

1. **Multi-agent coordination:** How do two agents working in parallel worktrees merge without conflicts? Symphony isolates but doesn't address merge strategy.
2. **Feature decomposition quality:** The initializer agent's feature decomposition determines everything downstream. Bad decomposition → bad results. How to validate/improve this?
3. **Cross-session learning:** Currently each session starts fresh. Could agents learn from patterns in progress.txt across many sessions? (This is what agent-memory v2 addresses.)
4. **Verification tooling gap:** For non-web projects (CLIs, libraries, infrastructure), what's the equivalent of Puppeteer MCP? Test suites help but don't catch integration issues.
5. **Entropy management at scale:** OpenAI's "garbage collection" pattern (recurring cleanup agents) is under-specified. How do you detect drift before it compounds?
