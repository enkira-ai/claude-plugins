---
name: harness-init
description: Use when setting up a new or existing repo for autonomous agent work. Triggers on "harness init", "set up harness", "make this repo agent-ready", "initialize for autonomous coding", "harness engineer this repo". Creates the full scaffolding (CLAUDE.md, features.json, progress.txt, init.sh, docs/) so coding agents can work independently across sessions.
---

# Harness Init — Make a Repo Agent-Ready

You are the **initializer agent**. Your job is to analyze this repository and create the scaffolding that enables coding agents to work autonomously across many sessions without human supervision.

## Why This Matters

Coding agents fail in predictable ways without proper scaffolding:
1. **One-shotting** — trying to build everything at once, running out of context mid-feature
2. **Premature completion** — declaring victory without proper testing
3. **Context loss** — next session can't figure out what happened in previous sessions
4. **Architectural drift** — no enforced boundaries, code quality degrades over time

The harness solves all four by creating a **legible environment** — structured artifacts that let each agent session quickly understand the project state, pick up the next task, verify its work, and leave things clean for the next session.

## Step-by-Step Process

### Phase 1: Analyze the Repository

Before creating anything, understand what exists:

```bash
pwd
ls -la
```

Check for existing project files:
```bash
# Check what already exists
cat README.md 2>/dev/null || echo "No README"
cat CLAUDE.md 2>/dev/null || echo "No CLAUDE.md"
cat AGENTS.md 2>/dev/null || echo "No AGENTS.md"
cat package.json 2>/dev/null || cat Cargo.toml 2>/dev/null || cat go.mod 2>/dev/null || cat pyproject.toml 2>/dev/null || cat Gemfile 2>/dev/null || echo "No package manager found"
ls docs/ 2>/dev/null || echo "No docs/"
ls src/ 2>/dev/null || ls lib/ 2>/dev/null || ls app/ 2>/dev/null || echo "No source dir found"
git log --oneline -10 2>/dev/null || echo "Not a git repo"
```

Determine:
- **Language/framework** (Node/Python/Rust/Go/Ruby/etc.)
- **Build system** (npm/cargo/make/etc.)
- **Test framework** (jest/pytest/cargo test/go test/etc.)
- **Dev server** (if web app)
- **Existing structure** (monorepo? packages? domains?)
- **Current state** (empty repo? existing code? tests passing?)

### Phase 2: Create the Harness Scaffolding

Create these files, adapting to what the repo already has. **Never overwrite existing files without asking.** If a file exists, propose merging your additions.

#### 2.1 — `CLAUDE.md` (or `AGENTS.md`) — The Table of Contents

This is the agent's entry point. Keep it **under 150 lines**. It's a map, not an encyclopedia.

```markdown
# CLAUDE.md — [Project Name]

## Quick Start (Every Session)

1. Run `cat progress.txt | tail -40` to see what happened last session
2. Run `cat features.json | head -60` to see the current feature backlog
3. Run `git log --oneline -10` to see recent commits
4. Run `bash init.sh` to start the dev environment
5. Run the test suite: `[TEST_COMMAND]`
6. Pick the highest-priority incomplete feature and work on it

## Project Overview
[1-3 sentences about what this project is]

## Architecture
[Brief description of the codebase structure — key directories, main entry points]
For details: `docs/ARCHITECTURE.md`

## Coding Rules
- `[TEST_COMMAND]` must pass before every commit
- `[BUILD_COMMAND]` must be clean before every commit
- Conventional commits: `feat:`, `fix:`, `test:`, `refactor:`, `chore:`, `docs:`
- Never delete a test to make it pass — fix the source
- Never commit with `--no-verify`. The pre-commit hook encodes hard constraints; bypassing it is a bug, not a shortcut.
- Never leave `TODO`/`FIXME`/`.skip`/`.only` in committed code. The hook will reject it.
- Work on ONE feature at a time. Commit after each feature.
- After each commit, update `progress.txt` with what was done

## Verification Policy
Before flipping `"passes": true` on a feature, invoke `harness-engineer:harness-verify <feature_id>`. The verify skill delegates to codex or gemini (external CLI, different model family) so the verdict is independent of this session's context. Self-verification is allowed only for features explicitly flagged `"trivial": true`.

## Testing
- Run tests: `[TEST_COMMAND]`
- [How to run specific tests, e2e tests, etc.]
- Only mark a feature as passing AFTER verifying it works end-to-end
- It is unacceptable to remove or edit feature specs — only change the `passes` field

## Key Files
| File | Purpose |
|------|---------|
| `features.json` | Feature backlog with pass/fail status |
| `progress.txt` | Session progress log — UPDATE AFTER EVERY COMMIT |
| `init.sh` | Dev environment setup script |
| `docs/ARCHITECTURE.md` | Detailed architecture guide |
| `docs/DESIGN.md` | Design decisions and rationale |

## When Tests Fail
1. Read the failure carefully — fix source, not test
2. If test is genuinely wrong (spec changed), update test AND add a comment explaining why
3. Never `.skip` a test without a comment
```

**Adapt this template to the actual project.** Fill in real commands, real directories, real architecture.

#### 2.2 — `features.json` — The Feature Backlog

Break the project goal into granular, testable features. Use JSON so the agent is less likely to improperly edit it.

```json
[
  {
    "id": 1,
    "category": "setup",
    "description": "Project builds and all existing tests pass",
    "verification": [
      "Run the build command",
      "Run the test suite",
      "Verify zero failures"
    ],
    "passes": false,
    "priority": "critical"
  },
  {
    "id": 2,
    "category": "functional",
    "description": "[Specific feature description]",
    "verification": [
      "[Step 1 to verify]",
      "[Step 2 to verify]",
      "[Step 3 to verify]"
    ],
    "passes": false,
    "priority": "high"
  }
]
```

**Rules for feature decomposition:**
- Each feature should be completable in a single agent session
- Features should be ordered by dependency (foundations first)
- Include verification steps that the agent can actually execute
- Categories: `setup`, `functional`, `ui`, `api`, `testing`, `quality`, `docs`
- Priorities: `critical` (blocks everything), `high`, `medium`, `low`
- Start with 10-30 features for small projects, 50-200 for large ones
- **All features start as `"passes": false`**

If the user provided a spec or description, decompose THAT into features. If not, analyze the existing codebase and create features for incomplete or missing functionality.

#### 2.3 — `progress.txt` — Session Progress Log

```text
# Progress Log
# Each session appends an entry after every commit.
# Format: [DATE SESSION N] STATUS — Brief title

---

[YYYY-MM-DD SESSION 1] INITIALIZED — Harness scaffolding created

## What was done
- Created CLAUDE.md with project map
- Created features.json with N features
- Created init.sh for dev environment
- Created docs/ structure

## Final state
- Build: [clean/errors]
- Tests: [N pass / M fail]
- What's next: [first feature to work on]

---
```

#### 2.4 — `init.sh` — Dev Environment Setup

Create a script that gets the dev environment running. The agent runs this at the start of every session.

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== Setting up dev environment ==="

# Install dependencies
[INSTALL_COMMAND]  # npm install / pip install -r requirements.txt / cargo build / etc.

# Start dev server (if applicable, in background)
# [DEV_SERVER_COMMAND] &
# echo "Dev server PID: $!"

# Run a quick smoke test
echo "=== Running smoke test ==="
[TEST_COMMAND] || echo "WARNING: Some tests are failing"

echo "=== Environment ready ==="
```

**Adapt to the actual project.** If it's a web app, start the dev server. If it's a library, just install deps and run tests. If it's a CLI tool, build it.

#### 2.5 — `docs/` — Progressive Disclosure

Create the docs structure. Agents read these on demand, not all at once.

```
docs/
├── ARCHITECTURE.md    — Detailed codebase map (domains, layers, dependencies)
├── DESIGN.md          — Design decisions and rationale
├── QUALITY.md         — Quality grades per domain/area (optional, for larger projects)
├── plans/             — Execution plans for complex features
│   ├── active/        — Currently in progress
│   └── completed/     — Done (for reference)
└── references/        — External docs, API references, llms.txt files
```

Write `docs/ARCHITECTURE.md` with:
- Directory structure explanation
- Key modules/classes and their responsibilities
- Data flow (how a request/action flows through the system)
- Dependency graph (what depends on what)

Write `docs/DESIGN.md` with:
- Tech stack choices and why
- Patterns used (and which to avoid)
- Naming conventions
- Error handling approach

### Phase 3: Set Up Hard Constraints

Harness research is unanimous: **hard constraints beat natural-language instructions by 100×.** Telling an agent "don't leave TODOs" is negotiable; a pre-commit hook that rejects the commit is not. This phase wires the non-negotiables.

#### 3.1 — Install the Pre-Commit Hook

Create `.githooks/pre-commit` and activate it via `core.hooksPath`. This persists across clones without requiring husky/lefthook.

```bash
mkdir -p .githooks
cat > .githooks/pre-commit <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail

# --- Hard constraint 1: no TODO/FIXME/XXX in staged source ---
STAGED=$(git diff --cached --name-only --diff-filter=ACM)
if [ -n "$STAGED" ]; then
  BAD=$(echo "$STAGED" | xargs -r grep -lE '(TODO|FIXME|XXX)' 2>/dev/null || true)
  if [ -n "$BAD" ]; then
    echo "REJECTED: staged files contain TODO/FIXME/XXX:"
    echo "$BAD" | sed 's/^/  /'
    echo "Complete the work or remove the marker. Do not commit half-done code."
    exit 1
  fi
fi

# --- Hard constraint 2: no skipped tests ---
SKIP_PATTERNS='\.skip\(|\.only\(|xit\(|xdescribe\(|@pytest\.mark\.skip|t\.Skip\(|#\[ignore\]'
if [ -n "$STAGED" ]; then
  SKIPPED=$(echo "$STAGED" | grep -E '(test|spec)' | xargs -r grep -lE "$SKIP_PATTERNS" 2>/dev/null || true)
  if [ -n "$SKIPPED" ]; then
    echo "REJECTED: staged test files contain .skip/.only/ignore:"
    echo "$SKIPPED" | sed 's/^/  /'
    echo "Fix the test or delete it. Do not skip."
    exit 1
  fi
fi

# --- Hard constraint 3: lint passes ---
if [ -n "${LINT_COMMAND:-}" ]; then
  eval "$LINT_COMMAND" || { echo "REJECTED: lint failed"; exit 1; }
fi

# --- Hard constraint 4: build passes (skip for docs-only commits) ---
if [ -n "${BUILD_COMMAND:-}" ]; then
  if echo "$STAGED" | grep -qvE '\.(md|txt|json)$'; then
    eval "$BUILD_COMMAND" || { echo "REJECTED: build failed"; exit 1; }
  fi
fi

exit 0
HOOK
chmod +x .githooks/pre-commit
git config core.hooksPath .githooks
```

**Adapt the LINT_COMMAND and BUILD_COMMAND** to the detected stack — hard-code them into the hook or document them in CLAUDE.md so the hook picks them up via env.

**The hook must be unbypassable in principle.** Document in CLAUDE.md that `--no-verify` is a firing-offense-level escape hatch.

#### 3.2 — Lint Configuration

If the project has no linter, install one (`eslint`, `ruff`, `clippy`, `golangci-lint`, `rubocop`). Configure lint rules with clear, actionable error messages — these become remediation instructions injected into the agent's context on failure. Vague lint messages train the agent to suppress them.

#### 3.3 — Independent Verification (Evaluator Role)

Single-agent workflows self-validate and drift. Pair this harness with an external evaluator CLI so verification is **not** done by the generator.

Check what's available on the machine:

```bash
command -v codex >/dev/null 2>&1 && echo "codex: available"
command -v gemini >/dev/null 2>&1 && echo "gemini: available"
```

If either is present, add this line to `CLAUDE.md`:

```markdown
## Verification Policy
Before setting `"passes": true` on any feature, invoke the `harness-engineer:harness-verify` skill. It delegates verification to codex or gemini (whichever is installed) so the verdict is free of this session's context and priors. Never self-verify except on trivial features explicitly flagged `"trivial": true`.
```

If neither CLI is installed, still add the skill reference and note that verification falls back to a fresh Claude subagent — weaker isolation, but better than self-validation.

### Phase 4: Initial Commit

After creating all scaffolding:

```bash
git add CLAUDE.md features.json progress.txt init.sh docs/ .githooks/
git commit -m "feat: initialize harness engineering scaffolding

Set up the environment for autonomous agent coding sessions:
- CLAUDE.md: agent entry point and project map
- features.json: feature backlog with pass/fail tracking
- progress.txt: session progress log
- init.sh: dev environment setup script
- docs/: architecture and design documentation
- .githooks/pre-commit: hard constraints (no TODO, no skipped tests, lint+build gate)"
```

After commit, remind the user to run `git config core.hooksPath .githooks` once on any fresh clone — this cannot be committed.

### Phase 5: Verify

Run the full verification:
1. `bash init.sh` — does the environment set up correctly?
2. `[TEST_COMMAND]` — do existing tests pass?
3. `cat features.json | python3 -c "import json,sys; f=json.load(sys.stdin); print(f'{len(f)} features, {sum(1 for x in f if x[\"passes\"])} passing')"` — feature count check
4. Update `progress.txt` with the results

## Adaptation Rules

- **Empty repo:** Create minimal project scaffold first (package.json/Cargo.toml/etc.), then harness files
- **Existing repo with tests:** Analyze existing tests to auto-populate features.json with current pass/fail state
- **Monorepo:** Create per-package features.json or a single one with package prefixes
- **Non-code project:** Adapt features.json to track deliverables instead of code features
- **Already has CLAUDE.md:** Merge harness additions into existing file, don't overwrite

## What NOT to Do

- Don't create a giant CLAUDE.md/AGENTS.md — keep it under 150 lines
- Don't put architecture details in CLAUDE.md — put them in docs/ARCHITECTURE.md
- Don't create features that can't be verified by the agent
- Don't set up tools the project doesn't need
- Don't over-engineer — start minimal, the coding agent can add more docs as needed
