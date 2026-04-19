# Enkira Harness Orchestration: Architecture Research

**Date:** 2026-03-19
**Purpose:** Compare approaches for building a Symphony-style orchestration layer for OpenClaw — dispatch coding agents to Linear issues autonomously, with isolated workspaces and retry logic.

---

## 1. OpenClaw Plugin Architecture — What Plugins Can and Cannot Do

### 1.1 Extension Points Available to Plugins

OpenClaw exposes five meaningful extension surfaces:

#### A. ContextEngine (primary plugin slot)

The deepest hook into session lifecycle. A plugin registers a factory and OpenClaw instantiates it per-session:

```typescript
// dist/plugin-sdk/context-engine/registry.d.ts
export declare function registerContextEngine(
  id: string,
  factory: ContextEngineFactory  // () => ContextEngine | Promise<ContextEngine>
): void;
```

A `ContextEngine` plugin gets called at every critical moment:

```typescript
// dist/plugin-sdk/context-engine/types.d.ts
export interface ContextEngine {
  readonly info: ContextEngineInfo;
  bootstrap?(params: { sessionId, sessionFile }): Promise<BootstrapResult>;
  ingest(params: { sessionId, message, isHeartbeat? }): Promise<IngestResult>;
  ingestBatch?(params: { sessionId, messages, isHeartbeat? }): Promise<IngestBatchResult>;
  afterTurn?(params: {
    sessionId, sessionFile, messages,
    prePromptMessageCount, autoCompactionSummary?,
    isHeartbeat?, tokenBudget?, runtimeContext?
  }): Promise<void>;
  assemble(params: { sessionId, messages, tokenBudget? }): Promise<AssembleResult>;
  compact(params: { sessionId, sessionFile, tokenBudget?, force?, ... }): Promise<CompactResult>;
  // Subagent lifecycle hooks:
  prepareSubagentSpawn?(params: {
    parentSessionKey, childSessionKey, ttlMs?
  }): Promise<SubagentSpawnPreparation | undefined>;
  onSubagentEnded?(params: {
    childSessionKey, reason: 'deleted'|'completed'|'swept'|'released'
  }): Promise<void>;
  dispose?(): Promise<void>;
}
```

**What `assemble()` controls:** The plugin decides what messages the model sees. This is where memory systems like `agent-memory` park/swap topics. The returned `systemPromptAddition` is prepended to the runtime system prompt.

**What `afterTurn()` triggers:** Called after every agent turn completes, receives the full transcript. Ideal for background work (graph updates, disk flushes, consolidation). The existing `MemoryHarnessEngine` uses this for WAL commits.

**The subagent hooks** (`prepareSubagentSpawn`, `onSubagentEnded`) are called when the parent agent spawns a child via `sessions_spawn`. A ContextEngine plugin can track the spawned child's `childSessionKey` and react when it finishes.

**Registered in `openclaw.plugin.json`:**
```json
{
  "id": "memory-harness",
  "kind": "context-engine",
  "configSchema": { ... }
}
```

#### B. ACP Runtime Backend (custom agent execution backend)

A plugin can register a fully custom AI runtime:

```typescript
// dist/plugin-sdk/acp/runtime/registry.d.ts
export type AcpRuntimeBackend = {
  id: string;
  runtime: AcpRuntime;
  healthy?: () => boolean;
};

export declare function registerAcpRuntimeBackend(backend: AcpRuntimeBackend): void;
```

The `AcpRuntime` interface defines how sessions are managed:

```typescript
// dist/plugin-sdk/acp/runtime/types.d.ts
export interface AcpRuntime {
  ensureSession(input: AcpRuntimeEnsureInput): Promise<AcpRuntimeHandle>;
  runTurn(input: AcpRuntimeTurnInput): AsyncIterable<AcpRuntimeEvent>;
  getCapabilities?(input: { handle? }): Promise<AcpRuntimeCapabilities> | AcpRuntimeCapabilities;
  getStatus?(input: { handle, signal? }): Promise<AcpRuntimeStatus>;
  setMode?(input: { handle, mode }): Promise<void>;
  setConfigOption?(input: { handle, key, value }): Promise<void>;
  close?(input: { handle, reason }): Promise<void>;
  doctor?(): Promise<AcpRuntimeDoctorReport>;
}

export type AcpRuntimeEnsureInput = {
  sessionKey: string;
  agent: string;
  mode: 'persistent' | 'oneshot';
  cwd?: string;
  env?: Record<string, string>;
};
```

**This is the most powerful extension point**: an orchestrator could register itself as an ACP backend, routing `ensureSession`+`runTurn` calls to issue-specific worker processes with isolated workspaces.

#### C. `sessions_spawn` Tool (agent-level, not plugin-level)

When an agent (Claude) calls `sessions_spawn`, OpenClaw calls:

```typescript
// dist/plugin-sdk/agents/subagent-spawn.d.ts
export declare function spawnSubagentDirect(
  params: SpawnSubagentParams,
  ctx: SpawnSubagentContext
): Promise<SpawnSubagentResult>;

export type SpawnSubagentParams = {
  task: string;
  label?: string;
  agentId?: string;
  model?: string;
  thinking?: string;
  runTimeoutSeconds?: number;
  thread?: boolean;
  mode?: 'run' | 'session';
  cleanup?: 'delete' | 'keep';
  sandbox?: 'inherit' | 'require';
  expectsCompletionMessage?: boolean;
  attachments?: Array<{ name, content, encoding?, mimeType? }>;
  attachMountPath?: string;
};
```

**Depth limits:** `config.agents.subagents.maxDepth` — default 1 (no nested spawns). This is a hard limit on orchestration depth.

**Auto-announce model:** Children push completion events back to the parent as messages. The parent must NOT poll — just wait.

```typescript
// The canonical note injected when spawn succeeds:
export declare const SUBAGENT_SPAWN_ACCEPTED_NOTE =
  "Auto-announce is push-based. After spawning children, do NOT call sessions_list, " +
  "sessions_history, exec sleep, or any polling tool. Wait for completion events to arrive...";
```

#### D. ACP Spawn (for `acpx` backends)

A parallel spawn mechanism for ACP-mode sessions:

```typescript
// dist/plugin-sdk/agents/acp-spawn.d.ts
export type SpawnAcpParams = {
  task: string;
  label?: string;
  agentId?: string;
  cwd?: string;
  mode?: 'run' | 'session';
  thread?: boolean;
  sandbox?: 'inherit' | 'require';
  streamTo?: 'parent';
};

export declare function spawnAcpDirect(
  params: SpawnAcpParams,
  ctx: SpawnAcpContext
): Promise<SpawnAcpResult>;
```

Supports `cwd` override — a spawned ACP session can be rooted in a different directory. This is the closest OpenClaw equivalent to Symphony's workspace isolation.

#### E. Cron System

The `CronService` (in `plugin-sdk/cron/`) supports scheduled jobs that fire agent sessions on a timer. It handles delivery routing, failure notifications, and stagger. However:

- It is user-facing config (`openclaw cron create ...`) not a plugin API
- It triggers message delivery to a session, not subprocess creation
- No workspace isolation or per-issue state management

### 1.2 What Plugins CANNOT Do

| Capability | Plugin Support | Reason |
|---|---|---|
| Long-running daemon/background process | ❌ None | Plugins are loaded at session init, live for session lifetime only |
| Poll an external API on a cron | ⚠️ Via cron, limited | Cron triggers agent runs but has no orchestrator state |
| Persistent state between sessions | ⚠️ Via files/SQLite only | No in-process state across session restarts |
| Create isolated git worktrees | ❌ None | No first-class filesystem isolation primitive |
| Multi-issue dispatch with concurrency control | ❌ None | No orchestration state machine |
| Retry/backoff queue | ❌ None | Would need external state |
| Reconciliation (stall detection, tracker refresh) | ❌ None | No background ticker |
| Inject `cwd` into spawned agents (native) | ⚠️ ACP only | `sessions_spawn` (native) has no `cwd` param; `spawnAcpDirect` does |

**Critical gap**: There is no "plugin runs as daemon" model in OpenClaw. A ContextEngine plugin's code runs synchronously within the session's event loop. If the session ends, the plugin is gone. This fundamentally limits what a plugin alone can orchestrate.

---

## 2. OpenAI Symphony Architecture

Symphony is a language-agnostic specification for a standalone orchestration service. The Elixir reference implementation is in `/tmp/symphony/elixir/`.

### 2.1 Core Components

```
Symphony
├── WorkflowLoader        — reads WORKFLOW.md (YAML frontmatter + Liquid prompt template)
├── ConfigLayer           — typed getters, env-var indirection, defaults
├── IssueTrackerClient    — Linear GraphQL, normalizes to stable Issue model
├── Orchestrator          — poll loop, state machine, concurrency, retry queue, reconciliation
├── WorkspaceManager      — per-issue directory lifecycle + 4 shell hooks
├── AgentRunner           — stdio JSON-RPC with codex app-server subprocess
└── StatusSurface         — optional observability endpoint
```

### 2.2 WORKFLOW.md Contract

Repository-owned file versioned with the code. Front matter configures the service; body is the Liquid prompt template:

```markdown
---
tracker:
  kind: linear
  api_key: $LINEAR_API_KEY
  project_slug: enkira-backend
  active_states: [Todo, In Progress]
  terminal_states: [Done, Cancelled, Duplicate]

polling:
  interval_ms: 30000

workspace:
  root: /tmp/enkira_workspaces

hooks:
  after_create: |
    git clone git@github.com:enkira/backend.git .
    npm install
  before_run: |
    git pull origin main

agent:
  max_concurrent_agents: 5
  max_turns: 20

codex:
  command: codex app-server
  approval_policy: auto
  turn_timeout_ms: 3600000
---

You are working on {{ issue.identifier }}: {{ issue.title }}

## Context
{{ issue.description }}

{% if attempt %}
Retry attempt {{ attempt }}. Previous attempt may have failed or stalled.
{% endif %}

Complete the issue, update the Linear ticket to "Human Review" when done.
```

### 2.3 Orchestrator State Machine

Each issue transitions through:
```
Unclaimed → Claimed → Running → (success) → Released / short-retry continuation
                   → RetryQueued → (timer fires) → Running or Released
```

The orchestrator owns all state mutations. Retry backoff:
```
normal continuation: fixed 1000ms
failure retry: min(10000 * 2^(attempt-1), max_retry_backoff_ms)
```

Concurrency: `available_slots = max(max_concurrent_agents - running_count, 0)`

### 2.4 Agent Runner Protocol (stdio JSON-RPC)

```json
// Startup handshake (order matters):
{"id":1,"method":"initialize","params":{"clientInfo":{"name":"symphony","version":"1.0"},"capabilities":{}}}
{"method":"initialized","params":{}}
{"id":2,"method":"thread/start","params":{"approvalPolicy":"auto","sandbox":"none","cwd":"/abs/workspace/ABC-123"}}
{"id":3,"method":"turn/start","params":{"threadId":"<thread-id>","input":[{"type":"text","text":"<rendered prompt>"}],"cwd":"/abs/workspace/ABC-123","title":"ABC-123: Fix the bug","approvalPolicy":"auto","sandboxPolicy":{"type":"none"}}}
```

The client reads line-delimited JSON events until `turn/completed` or `turn/failed`.

Multi-turn continuation on the same thread:
```json
// Subsequent turns — reuse threadId, don't resend full prompt
{"id":4,"method":"turn/start","params":{"threadId":"<same-thread-id>","input":[{"type":"text","text":"The issue is still active. Continue working on it."}],...}}
```

### 2.5 Workspace Safety Invariants

```
workspace_root = /tmp/enkira_workspaces
workspace_path = /tmp/enkira_workspaces/ABC-123   (sanitized: [A-Za-z0-9._-] only)

Invariant 1: agent cwd == workspace_path (validate before launch)
Invariant 2: workspace_path must be inside workspace_root (prefix check)
Invariant 3: workspace_key sanitized ([A-Za-z0-9._-], rest → '_')
```

---

## 3. Approach Comparison

### Approach A: Pure OpenClaw Plugin

**Mechanism:** A ContextEngine plugin that, in its `afterTurn()` callback, reads Linear and decides whether to spawn subagents via `spawnSubagentDirect()`.

```typescript
// Conceptual — harness-orchestrator as ContextEngine
class HarnessOrchestratorEngine implements ContextEngine {
  async afterTurn(params: AfterTurnParams) {
    const issues = await linearClient.fetchCandidateIssues();
    for (const issue of issues.slice(0, availableSlots)) {
      await spawnSubagentDirect({
        task: renderPrompt(workflowTemplate, issue),
        label: issue.identifier,
        agentId: 'developer',
        mode: 'run',
        cleanup: 'keep',
      }, { agentSessionKey: params.sessionId });
    }
  }

  async onSubagentEnded(params: { childSessionKey, reason }) {
    // Update orchestrator state — issue X completed
    await this.orchestratorState.markCompleted(params.childSessionKey);
  }
}
```

**Pros:**
- Zero infrastructure, lives inside OpenClaw
- Subagents get full OpenClaw context (memory, skills, tools)
- No separate process to manage

**Cons:**
- **No persistent daemon.** The parent agent session must stay alive for orchestration to continue. If the parent session ends (user closes conversation), all orchestration stops.
- **No workspace isolation.** `spawnSubagentDirect` has no `cwd` param — children inherit parent's workspace or use their configured agent workspace.
- **Depth limit.** `maxDepth` defaults to 1. Nested spawning is blocked.
- **No reconciliation loop.** No background ticker to check stalled agents or refresh tracker state.
- **No retry queue.** Must implement in-memory state that dies with the session.
- **Race conditions.** `afterTurn` fires after each turn — if the parent is a heartbeat agent that runs frequently, dispatch logic must be idempotent.

**Verdict:** Viable for simple task dispatch in a single session. Unsuitable for a robust production orchestrator. Works if you accept "orchestration only runs while a human is watching".

---

### Approach B: Standalone Service (Symphony-style)

**Mechanism:** A standalone Node.js or Elixir daemon that polls Linear and launches `openclaw` subprocesses per issue.

The key question: does OpenClaw have a `codex app-server`-equivalent headless mode?

Looking at the dist structure, OpenClaw has:
- `daemon-cli` / `daemon-runtime` — OpenClaw's own background daemon
- `acp-cli` — ACP session management CLI
- `pi-embedded-runner.d.ts` — embedded runner (the Claude API client loop)

The ACP session manager (`getAcpSessionManager()`) exposes `initializeSession` and `runTurn` programmatically. But this is an internal API, not a stable CLI protocol.

**Realistic approach**: Run OpenClaw in a headless message-loop mode (if available), or use `openclaw` CLI with stdin injection. The standalone service would:

```typescript
// Standalone orchestrator (Node.js)
class EnkiraOrchestrator {
  private running = new Map<string, ChildProcess>();

  async tick() {
    await this.reconcile();
    const issues = await this.linear.fetchCandidates();
    for (const issue of this.selectEligible(issues)) {
      await this.dispatch(issue);
    }
  }

  async dispatch(issue: Issue) {
    const workspacePath = path.join(this.workspaceRoot, sanitize(issue.identifier));
    await fs.mkdir(workspacePath, { recursive: true });
    await this.runHook('before_run', workspacePath);

    // Launch openclaw headless (or via ACP)
    const child = spawn('bash', ['-lc', this.config.agentCommand], {
      cwd: workspacePath,
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    // Stream JSON-RPC protocol (same as Symphony does with codex app-server)
    await this.initializeAcpSession(child, issue);
    this.running.set(issue.id, child);
  }
}
```

**Pros:**
- Full Symphony parity: polling loop, workspace isolation, retry/backoff, reconciliation, WORKFLOW.md
- Persistent daemon — works 24/7 without human interaction
- Can manage concurrency precisely
- Clean separation: orchestrator owns scheduling, agent owns execution

**Cons:**
- Requires OpenClaw to expose a stable headless stdio protocol (unclear if `openclaw` has a `app-server`-mode equivalent to `codex app-server`)
- If OpenClaw doesn't have a stdio JSON-RPC mode, must use a less stable approach (CLI automation, ACP socket connection)
- Must be deployed/managed separately from OpenClaw
- Loses OpenClaw plugin features (memory, skills) unless explicitly configured in each agent's workspace

**Key research needed:** Does OpenClaw expose a `--headless` or `app-server` equivalent?

---

### Approach C: Hybrid — Standalone Engine as an OpenClaw Plugin

**The core insight:** A plugin can `registerAcpRuntimeBackend()` with a custom `AcpRuntime`. This custom runtime IS the orchestrator. When OpenClaw wants to run a session via this backend, the orchestrator creates a workspace, launches a worker, and manages its lifecycle.

```typescript
// harness-orchestrator/src/plugin.ts
import { registerAcpRuntimeBackend } from '@openclaw/plugin-sdk/acp/runtime/registry';
import { EnkiraOrchestratorRuntime } from './orchestrator-runtime';

// Called once at plugin init
export function activate() {
  const orchestrator = new EnkiraOrchestratorRuntime({
    workspaceRoot: process.env.ENKIRA_WORKSPACE_ROOT ?? '/tmp/enkira',
    linearApiKey: process.env.LINEAR_API_KEY,
    maxConcurrent: 5,
  });

  registerAcpRuntimeBackend({
    id: 'enkira-orchestrator',
    runtime: orchestrator,
    healthy: () => orchestrator.isHealthy(),
  });

  // Start the polling loop as a background Promise
  orchestrator.startPolling().catch(console.error);
}

// The orchestrator implements AcpRuntime
class EnkiraOrchestratorRuntime implements AcpRuntime {
  async ensureSession(input: AcpRuntimeEnsureInput): Promise<AcpRuntimeHandle> {
    // Create workspace for this session
    const workspacePath = path.join(this.workspaceRoot, sanitize(input.sessionKey));
    await fs.mkdir(workspacePath, { recursive: true });
    return {
      sessionKey: input.sessionKey,
      backend: 'enkira-orchestrator',
      runtimeSessionName: input.sessionKey,
      cwd: workspacePath,
    };
  }

  async *runTurn(input: AcpRuntimeTurnInput): AsyncIterable<AcpRuntimeEvent> {
    // Launch actual agent in workspace
    const workspace = await this.getWorkspace(input.handle.sessionKey);
    yield* this.runAgentInWorkspace(workspace, input.text, input.signal);
  }
}
```

**The polling loop runs as a background Promise in the plugin's process:**

```typescript
class EnkiraOrchestratorRuntime {
  async startPolling() {
    while (!this.stopped) {
      try {
        await this.reconcile();
        const issues = await this.linear.fetchCandidates();
        for (const issue of this.selectEligible(issues)) {
          // This calls ensureSession + runTurn on ourselves
          void this.dispatch(issue);
        }
      } catch (err) {
        this.logger.error('poll tick failed', err);
      }
      await sleep(this.pollIntervalMs);
    }
  }
}
```

**For the standalone process variant** (most robust):

```
┌─────────────────────────────────────────────────────┐
│                   OpenClaw Process                  │
│                                                     │
│  ContextEngine Plugin (harness-orchestrator)        │
│    - Registers as ACP backend                       │
│    - Manages IPC socket to orchestrator daemon      │
└───────────────────────┬─────────────────────────────┘
                        │ Unix socket / HTTP
                        ▼
┌─────────────────────────────────────────────────────┐
│           Enkira Orchestrator Daemon                │
│                                                     │
│   ┌─────────────┐   ┌──────────────┐               │
│   │   Poller    │   │  Workspace   │               │
│   │  (Linear)   │──▶│   Manager   │               │
│   └─────────────┘   └──────┬───────┘               │
│                             │                       │
│   ┌─────────────────────────▼──────────────────┐   │
│   │           Agent Worker Pool               │   │
│   │  worker-ABC-123: openclaw session (cwd)   │   │
│   │  worker-DEF-456: openclaw session (cwd)   │   │
│   └───────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

**Pros:**
- Plugin-native: users install it with `openclaw plugins install enkira-orchestrator`
- Can access OpenClaw internals (cfg, session state) from within the plugin
- Persistent daemon survives individual agent sessions
- Workspace isolation via `cwd` in `AcpRuntimeEnsureInput`
- Full retry/concurrency control
- Can expose orchestrator status via plugin CLI commands

**Cons:**
- Most complex architecture
- Plugin process lifecycle = OpenClaw process lifecycle (if OpenClaw restarts, daemon restarts)
- ACP backend registration is an internal API (may not be stable)
- Worker agents still need a way to launch (need OpenClaw headless mode OR use the ACP session manager directly)

---

## 4. Recommended Approach

**Short term (proof of concept):** Approach A — pure plugin, using `afterTurn` + `sessions_spawn`.

Scope it to: a heartbeat agent that polls Linear every N minutes, spawns one subagent per eligible issue using existing `developer` agent identity, and writes status to a shared markdown file. No workspace isolation. Accept the "orchestration stops when the heartbeat session ends" limitation.

**Medium term (production-grade):** Approach C hybrid — standalone orchestrator daemon with a thin OpenClaw plugin wrapper.

The standalone daemon:
1. Polls Linear using WORKFLOW.md config
2. Creates workspace directories per issue
3. Launches workers using `spawnAcpDirect` (which has `cwd` support) or via the OpenClaw daemon socket
4. Tracks in-memory state with file-system persistence for restart recovery

The plugin wrapper:
1. Installs the daemon binary on `openclaw plugins install`
2. Starts the daemon via a plugin init hook
3. Exposes `/harness-status`, `/harness-dispatch`, `/harness-pause` slash commands
4. Optionally registers an ACP backend to route sessions through the orchestrator

---

## 5. Critical Implementation Questions

1. **Does OpenClaw have a headless/app-server mode?** The `daemon-runtime` module exists — does it expose a stdio JSON-RPC protocol? If yes, standalone service is trivially doable (just substitute `codex app-server` with `openclaw daemon-start`).

2. **Is `registerAcpRuntimeBackend` stable for external plugins?** It's exported from `plugin-sdk/` which suggests yes, but the ACP backend pattern is complex and may break across versions.

3. **What is the `cwd` behavior for `spawnSubagentDirect`?** The type has no `cwd` param. `spawnAcpDirect` does have `cwd`. If worker agents run via ACP, workspace isolation is achievable. If via native `sessions_spawn`, it's not.

4. **Is there a plugin activation/lifecycle hook?** The `ContextEngine.bootstrap()` and `dispose()` hooks are per-session. Is there a global plugin init hook that fires once when OpenClaw starts (not per-session)?

5. **What is the daemon socket protocol?** Can an external process connect to the OpenClaw daemon socket to call `spawnSubagentDirect` programmatically without being a Claude session?

---

## 6. File References

| Path | Purpose |
|---|---|
| `/home/bwen/.nvm/versions/node/v24.11.1/lib/node_modules/openclaw/dist/plugin-sdk/context-engine/types.d.ts` | ContextEngine interface (full) |
| `/home/bwen/.nvm/versions/node/v24.11.1/lib/node_modules/openclaw/dist/plugin-sdk/agents/subagent-spawn.d.ts` | `spawnSubagentDirect` + `SpawnSubagentParams` |
| `/home/bwen/.nvm/versions/node/v24.11.1/lib/node_modules/openclaw/dist/plugin-sdk/agents/acp-spawn.d.ts` | `spawnAcpDirect` + `cwd` support |
| `/home/bwen/.nvm/versions/node/v24.11.1/lib/node_modules/openclaw/dist/plugin-sdk/acp/runtime/types.d.ts` | `AcpRuntime` interface |
| `/home/bwen/.nvm/versions/node/v24.11.1/lib/node_modules/openclaw/dist/plugin-sdk/acp/runtime/registry.d.ts` | `registerAcpRuntimeBackend` |
| `/home/bwen/.nvm/versions/node/v24.11.1/lib/node_modules/openclaw/dist/plugin-sdk/acp/control-plane/manager.core.d.ts` | `AcpSessionManager` class |
| `/home/bwen/.nvm/versions/node/v24.11.1/lib/node_modules/openclaw/dist/plugin-sdk/agents/sandbox/constants.d.ts` | `DEFAULT_TOOL_ALLOW` includes `sessions_spawn` |
| `/home/bwen/projects/agent-memory/src/engine.ts` | Reference ContextEngine implementation (MemoryHarnessEngine) |
| `/home/bwen/projects/agent-memory/src/types.ts` | ContextEngine TypeScript types (agent-memory's view) |
| `/home/bwen/projects/agent-memory/openclaw.plugin.json` | Plugin manifest — `"kind": "context-engine"` |
| `/tmp/symphony/SPEC.md` | Full Symphony specification (80KB) |
| `/tmp/symphony/elixir/` | Reference Elixir implementation |
| `/home/bwen/projects/claude-plugins/plugins/harness-engineer/` | Existing harness plugin (commands, skills) |
| `/home/bwen/projects/claude-plugins/plugins/session-manager/` | Existing session manager plugin |
