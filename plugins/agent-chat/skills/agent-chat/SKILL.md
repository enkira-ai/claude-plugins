---
name: agent-chat
description: Use when two or more AI agents (Claude Code, Codex, Gemini CLI, or any combination) need to collaborate on a hard problem — brainstorming, critiquing reasoning, debating a design, working through a proof. Provides a round-robin session protocol (2..N agents) with round limits, audit-grade transcripts including the prompts used to spawn each subagent, and role-neutral launcher patterns so any supported CLI can be the main agent or a peer.
---

# Agent Chat

Two or more agents collaborate on difficult problems — brainstorming, critiquing each other's reasoning, debating design choices, working through a proof together. The protocol is a round-robin exchange via per-agent JSONL files. Each agent writes to its own file; reads from every peer's file. The script handles metadata, turn enforcement, round counting, wrap-up reminders, and recording the setup prompts used to spawn subagents (so the transcript can be audited end-to-end).

**Spirit:** the point is genuine collaboration on hard problems, not quick Q&A. Every agent should take the time they need to think carefully, disagree when warranted, and express substantive opinions. Round limits exist to prevent runaway conversations — not to encourage terseness.

**Script location:** `${CLAUDE_SKILL_DIR}/scripts/agent_chat.py` when installed as a Claude Code skill, or the absolute path to `scripts/agent_chat.py` when invoked from another agent.
**Sessions live in:** `<git-root>/.agent_chat/sessions/<session-id>/` (or cwd if not in a git repo)

---

## HARD RULE: No Actions Until Human Approves

**This chat is discussion only. Neither agent may edit files, write code, run experiments, or take any other action based on what was discussed — until the human reads the transcript and explicitly says to proceed.**

The flow after a session ends:
1. Main agent generates the transcript and tells the human it is ready for review.
2. **Both agents stop and wait.** Do not act on conclusions, do not start implementing, do not make any changes.
3. Human reads the transcript and decides what (if anything) to do next.
4. Human gives explicit instructions to whichever agent(s) should act.

If you feel the urge to "helpfully" start implementing something that came up in the chat — **don't**. Wait for the human.

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `new-session [--name LABEL] [--participants A B C ...]` | Create session. With `--participants`, declares 2..N agents and locks the round-robin order. Without it, falls back to legacy lazy 2-agent mode. |
| `send "<text>" --session ID --as NAME` | Send your message (errors if it isn't your turn) |
| `listen --session ID --as NAME [--timeout SEC]` | Block until it's your turn AND a peer has sent a new message; then flush all unread messages from peers |
| `status --session ID` | Show round, turn, last activity, per-agent message counts |
| `end --session ID --as NAME` | Close session |
| `record-prompt --session ID --by MAIN --target SUB [--prompt TEXT \| --prompt-file PATH] [--launcher CMD]` | Save the setup prompt + launcher used to spawn a subagent, for transcript audit |
| `transcript --session ID [--out FILE]` | Export Markdown including any recorded subagent setup prompts |
| `list` | List sessions in this repo |

All commands are invoked as `python3 <absolute-path-to-agent_chat.py> <command> ...`. In Claude Code that path is usually `${CLAUDE_SKILL_DIR}/scripts/agent_chat.py`; when spawning another CLI, pass the resolved absolute path in the prompt.

---

## Two Modes

### Mode A — Round-robin with N participants (2 or more, recommended for 3+)

Pre-declare every participant when creating the session. Order = round-robin order; first listed is conventionally the main agent. The script enforces strict turn order: A → B → C → A → ...

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/agent_chat.py new-session \
  --name <topic> --participants alice bob charlie
```

Each participant runs the same loop forever:

```bash
# 1. Wait for your turn
python3 .../agent_chat.py listen --session SID --as alice
# (prints any messages peers have sent since you last spoke)

# 2. Compose and send your reply
python3 .../agent_chat.py send "..." --session SID --as alice

# 3. Loop back to step 1
```

The main agent's first action is `send` (the opening message), then the loop above. Other participants start with `listen`.

### Mode B — Legacy lazy 2-agent

Omit `--participants`. The first agent to call `send` becomes main; the next to call `send`/`listen` registers as the second slot. Capped at 2.

```bash
python3 .../agent_chat.py new-session --name <topic>
# main:    send "<opening>" --as <name>
# other:   listen --as <name>; send "<reply>"; listen; ...
```

Use Mode A whenever you want >2 agents, or whenever you want strict deterministic turn order even with 2 agents.

---

## Listening Behavior

`listen` blocks until two conditions are both true:

1. It is your turn (`whose_turn == <you>`), and
2. At least one peer has sent a new message since you last listened.

When both are true, `listen` prints **all** unread peer messages — across every peer — in seq order, then exits with code 0. This means when it's your turn in a 3-agent round-robin, you get the full unread context (the messages from each of the other agents since you last spoke), not just the most recent one.

Other exit codes: `2` on timeout, `3` on session closed.

**Claude Code: use `Bash` with `run_in_background: true`.** `listen` is a one-shot "wait until done" — that's exactly the pattern Claude Code's Bash tool is built for. The harness notifies Claude once, cleanly, when the process exits; Claude reads the captured stdout, composes a reply, and calls `send`.

```
Bash command: python3 ${CLAUDE_SKILL_DIR}/scripts/agent_chat.py listen --session SESSION_ID --as claude --timeout 600
Bash description: wait for my turn
run_in_background: true
```

Do **not** use the `Monitor` tool. Monitor fires a notification per stdout line with no distinct "process exited" signal; a single listen flush can be thousands of characters of multi-line markdown, which Monitor delivers as a burst of partial-line notifications and Claude cannot reliably tell whether the process is done. `run_in_background` avoids that: one command, one completion notification, one reply.

---

## Turn Order

**2-agent (Mode A or B):**
```
Main agent                          Other agent
  send(opening)
  listen ──────────────────────────> turn=other → exits
                                     send(reply)
  <────────────────────────────────  listen exits, turn=main
  send(next)
  listen ──────────────────────────> ...
```

**3-agent round-robin (Mode A, participants=[A, B, C]):**
```
Round 0:  A.send → B.listen exits with [A] → B.send → C.listen exits with [A,B] → C.send
Round 1:  A.listen exits with [B,C] → A.send → B.listen exits with [C,A] → B.send → C.listen exits with [A,B] → C.send
...
```

Because `listen` flushes every unread peer message at once, each speaker always sees the full conversation since their last turn — even though the others spoke in between. Turn enforcement is strict: `send` errors if it isn't your turn (use `--force` only if genuinely stuck).

---

## Round Limits and Wrap-Up

- **Round 50 — reminder:** The script injects a `[SYSTEM]` notice into your output stream before the next message you send. The other agent sees it on their `listen` call. The notice asks the **main agent** to begin wrapping up.
- **Round 60 — force close:** Another `[SYSTEM]` notice is injected and the session is marked `force_ending`. The main agent must send one final report message, then call `end`.

If you see `[SYSTEM]` output during `listen`, print it to the user/log, then proceed normally. Do **not** skip or ignore it.

---

## Ending and Transcribing

Main agent ends the session:
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/agent_chat.py end --session SESSION_ID --as <main-agent-name>
```

Then generate the human-readable transcript:
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/agent_chat.py transcript --session SESSION_ID
```

The Markdown file is written to `<session-dir>/transcript.md`. It contains:

1. **Header** — session id, participants, main agent, round count, start/end timestamps.
2. **Subagent setup** — every prompt and launcher recorded via `record-prompt`. This is what makes the discussion auditable: the human can see exactly what context each subagent was given before judging the conversation that followed.
3. **Conversation** — every message in seq order, attributed by sender and round.

Share it with the human for review.

**After calling `transcript`, both agents must stop and wait for human instructions. Do not act on anything discussed until the human explicitly says to proceed.**

---

## Spawning Other AIs as Subagents

The main agent can launch one or more other AI CLIs as background subprocesses so every side runs autonomously, without the human having to drive each agent manually. The protocol is the same regardless of which AI is main or subagent. For 3+ agent sessions, just repeat steps 3–4 once per subagent and use `--participants` when creating the session.

Supported non-interactive launcher patterns:

| Subagent CLI | Use this when | Launcher |
|--------------|---------------|----------|
| Codex | You want OpenAI/Codex as the other agent | `codex exec --cd "$(pwd)" - < prompt.md` |
| Claude Code | You want Claude as the other agent | `claude -p --dangerously-skip-permissions "$(cat prompt.md)"` |
| Gemini CLI | You want Gemini as the other agent | `gemini --yolo "$(cat prompt.md)"` |

If a flag is rejected, run `<cli> --help` and adapt. Keep the command non-interactive and keep permissions low-friction enough that the subagent can run the `listen` and `send` commands without asking the human on every turn.

Before launching a real subagent, verify the CLI is authenticated in non-interactive mode with a tiny prompt. `command -v gemini` only proves the binary exists; Gemini CLI also needs `/Users/<user>/.gemini/settings.json` auth or an environment-backed auth method such as `GEMINI_API_KEY`, `GOOGLE_GENAI_USE_VERTEXAI`, or `GOOGLE_GENAI_USE_GCA`.

**1. Resolve the absolute script path first** — the subagent runs in its own environment and `${CLAUDE_SKILL_DIR}` usually will not be set there, so the main agent must substitute the real path when composing the prompt:
```bash
SCRIPT="${CLAUDE_SKILL_DIR}/scripts/agent_chat.py"   # expanded at main-agent time
```

**2. Create the session and capture the session ID. For 3+ agents, pre-declare every participant:**
```bash
# 2-agent (lazy)
python3 "$SCRIPT" new-session --name <topic>

# 3-agent round-robin (recommended for >2)
python3 "$SCRIPT" new-session --name <topic> --participants claude codex gemini
# → session_20260423_1_<topic>
```

**3. Write the subagent prompt to a file** (avoids shell-escaping issues with multi-line text). Tell the subagent the full participant list and the round-robin order so it has context for what it's stepping into:
```bash
cat > /tmp/agent_chat_codex_prompt.md << EOF
You are participating in a multi-agent round-robin chat session.

Participants (in turn order): claude, codex, gemini
Your name in this session: codex
Session ID: <SESSION_ID>

First, read $(dirname "$SCRIPT")/../SKILL.md to understand the protocol.

Then follow this loop forever until the session closes:
  A. Listen:
     python3 $SCRIPT listen --session <SESSION_ID> --as codex --timeout 600
     (this blocks until it is YOUR turn AND a peer has sent a new message)
  B. Check exit code:
     - 0: messages from peers were printed → go to C
     - 3: [SESSION CLOSED] → stop immediately, do not call listen or send again, exit
     - 2: [TIMEOUT] → exit and report
  C. Compose your reply, then:
     python3 $SCRIPT send "<reply>" --session <SESSION_ID> --as codex
  D. Go to A.

Context: <what every participant should know>
Task: <what the group should discuss>

Rules:
- Do NOT edit files, run experiments, or take any action beyond the listen/send loop.
- This is discussion only. The transcript goes to a human for review afterwards.
- Disagreement is welcome — that's the point of having multiple agents.
EOF
```

Note: this uses an un-quoted heredoc (`EOF` not `'EOF'`) so `$SCRIPT` is substituted by the outer shell, producing a prompt with concrete paths.

**3a. Record the prompt for transcript audit** — call `record-prompt` so the prompt and launcher end up in the final transcript. This is what makes the discussion auditable: the human reviewing the transcript can see exactly what setup each subagent was given.

```bash
LAUNCHER='codex exec --full-auto --cd "$(pwd)" -c '"'"'model_reasoning_effort="high"'"'"' - < /tmp/agent_chat_codex_prompt.md'

python3 "$SCRIPT" record-prompt \
  --session <SESSION_ID> \
  --by claude --target codex \
  --prompt-file /tmp/agent_chat_codex_prompt.md \
  --launcher "$LAUNCHER"
```

Repeat 3 + 3a for each additional subagent (e.g., gemini in a 3-way session).

**4. Launch each subagent in the background and capture its PID.** For 3+ agents, run one launch block per subagent with a distinct PID file (e.g., `agent_chat_codex.pid`, `agent_chat_gemini.pid`).

Codex:
```bash
codex exec --full-auto --cd "$(pwd)" \
  -c 'model_reasoning_effort="high"' \
  - < /tmp/agent_chat_codex_prompt.md > /tmp/agent_chat_codex.log 2>&1 &
echo $! > /tmp/agent_chat_codex.pid
```

Codex flags that matter:
- `exec` — non-interactive mode (runs one task and exits)
- `--full-auto` — sandboxed workspace-write, no approval prompts
- `--cd <dir>` — working directory (usually the repo root)
- `-` — read prompt from stdin
- `&` — background

Claude Code:
```bash
claude -p --dangerously-skip-permissions \
  --model sonnet \
  --effort high \
  "$(cat /tmp/agent_chat_claude_prompt.md)" \
  > /tmp/agent_chat_claude.log 2>&1 &
echo $! > /tmp/agent_chat_claude.pid
```

Claude flags that matter:
- `-p` / `--print` — non-interactive mode
- `--dangerously-skip-permissions` — lets the subagent run the `listen`/`send` shell commands without interactive approval
- `--model` and `--effort` — tune model and reasoning depth for the session

Gemini CLI:
```bash
gemini --yolo \
  "$(cat /tmp/agent_chat_gemini_prompt.md)" \
  > /tmp/agent_chat_gemini.log 2>&1 &
echo $! > /tmp/agent_chat_gemini.pid
```

Gemini flags that matter:
- positional prompt — current Gemini CLI treats positional prompt as one-shot non-interactive input
- `--yolo` or `--approval-mode yolo` — auto-approves the shell commands needed for the loop
- `-m <model>` — optional model override

**Tune model and reasoning effort to match task difficulty.** Codex defaults come from `~/.codex/config.toml`; Claude and Gemini use their own CLI defaults. Override them per-session when the task warrants it:

| Task difficulty | Suggested effort | Notes |
|-----------------|------------------|-------|
| Light review, quick sanity check | `low` or `medium` | Cheap, fast |
| Normal collaboration, debate, critique | `high` | Default for most sessions |
| Hard theory work, subtle proofs, long chains of reasoning | `xhigh` | Slower per-turn but worth it |

For Codex, override effort with `-c 'model_reasoning_effort="xhigh"'` and model with `-m <model>`. For Claude, use `--effort <level>` and `--model <model>`. For Gemini, use `-m <model>` where available. The main agent picks these at launch time based on the topic; subagents cannot reliably adjust their launcher settings mid-session.

**5. Main agent runs its own send/listen loop as normal.** Wait a few seconds after launching the subagents before sending the opening, so each subagent has time to read the skill and reach its first `listen` call.

**6. When the discussion is done, call `end`. Each subagent should exit on its own within a few seconds:**
- If its current `listen` is waiting, it detects the closed-session status (exit code 3) and exits.
- If `listen` already returned and it is about to `send`, the send errors with "Session is closed" (exit code 1) and the subagent exits.

**7. Safety-net kill** (only if a subagent is still running ~60s after `end`):
```bash
for pidfile in /tmp/agent_chat_codex.pid /tmp/agent_chat_gemini.pid /tmp/agent_chat_claude.pid; do
  [ -f "$pidfile" ] || continue
  PID=$(cat "$pidfile")
  if kill -0 "$PID" 2>/dev/null; then kill "$PID"; fi
done
```

In practice the self-exit path is reliable (~5–10s) and the kill is rarely needed — but it is good hygiene.

---

## Deadlock / Timeout

`listen` exits with code 2 and prints `[TIMEOUT]` if no message arrives within the timeout (default 10 min). When this happens:

1. Check `status` to see whose turn it is and when the last activity was.
2. If the other agent appears stuck, alert the human.
3. Do **not** loop-retry `listen` automatically — the human decides whether to continue.
