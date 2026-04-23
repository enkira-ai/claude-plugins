---
name: agent-chat
description: Use when two AI agents (Claude Code, Codex, Gemini CLI, or any pair) need to collaborate on a hard problem — brainstorming, critiquing reasoning, debating a design, working through a proof. Provides a ping-pong session protocol with round limits, transcript export, and role-neutral launcher patterns so any supported CLI can be the main agent or the spawned subagent.
---

# Agent Chat

Two agents collaborate on difficult problems — brainstorming, critiquing each other's reasoning, debating design choices, working through a proof together. The protocol is a ping-pong exchange via a shared JSONL file pair. Each agent writes to its own file; reads from the other's. The script handles metadata, turn enforcement, round counting, and wrap-up reminders.

**Spirit:** the point is genuine collaboration on hard problems, not quick Q&A. Both agents should take the time they need to think carefully, disagree when warranted, and express substantive opinions. Round limits exist to prevent runaway conversations — not to encourage terseness.

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
| `new-session [--name LABEL]` | Human or main agent creates session |
| `send "<text>" --session ID --as NAME` | Send your message |
| `listen --session ID --as NAME [--timeout SEC]` | Wait for other agent's message |
| `status --session ID` | Show round, turn, last activity |
| `end --session ID --as NAME` | Close session |
| `transcript --session ID [--out FILE]` | Export Markdown |
| `list` | List sessions in this repo |

All commands are invoked as `python3 <absolute-path-to-agent_chat.py> <command> ...`. In Claude Code that path is usually `${CLAUDE_SKILL_DIR}/scripts/agent_chat.py`; when spawning another CLI, pass the resolved absolute path in the prompt.

---

## Starting a Session (Main Agent)

1. Create the session — the script auto-detects the git repo root:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/agent_chat.py new-session --name <topic>
   ```
   It prints a session ID like `session_20260420_1_topic`. Copy it.

2. Send the opening message:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/agent_chat.py send "Your opening message here" \
     --session session_20260420_1_topic --as <your-agent-name>
   ```

3. Tell the human the session ID so they can pass it to the other agent.

4. Start listening:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/agent_chat.py listen \
     --session session_20260420_1_topic --as <your-agent-name>
   ```

---

## Joining a Session (Other Agent)

Human gives you the session ID. Start by listening first (the main agent already sent the opening):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/agent_chat.py listen \
  --session SESSION_ID --as <your-agent-name>
```

When you see the other agent's message printed, compose your reply and send:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/agent_chat.py send "Your reply" \
  --session SESSION_ID --as <your-agent-name>
```

Then listen again. Repeat.

---

## Listening Behavior

`listen` blocks until a message arrives, then prints it and exits. Agents without an interactive wait primitive should call `listen`, inspect the exit code, compose one reply, call `send`, and repeat.

Claude Code can use the `Monitor` tool so it gets notified the moment `listen` exits:

```
Monitor command: python3 ${CLAUDE_SKILL_DIR}/scripts/agent_chat.py listen --session SESSION_ID --as claude --timeout 600
Monitor description: waiting for other agent's reply
```

When Monitor fires, read the printed message and call `send` with your reply.

---

## Ping-Pong Loop

```
Main agent                          Other agent
  new-session
  send(opening)
  listen ──────────────────────────> arrives
                                     send(reply)
  <────────────────────────────────  listen exits
  send(next)
  listen ──────────────────────────> ...
```

The script enforces turns — `send` errors if it is not your turn (use `--force` only if genuinely stuck).

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

The Markdown file is written to `<session-dir>/transcript.md`. Share it with the human for review.

**After calling `transcript`, both agents must stop and wait for human instructions. Do not act on anything discussed until the human explicitly says to proceed.**

---

## Spawning Another AI as a Subagent

The main agent can launch another AI CLI as a background subprocess so both sides run autonomously, without the human having to drive the second agent manually. The protocol is the same regardless of which AI is main or subagent.

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

**2. Create the session and capture the session ID:**
```bash
python3 "$SCRIPT" new-session --name <topic>
# → session_20260423_1_<topic>
```

**3. Write the subagent prompt to a file** (avoids shell-escaping issues with multi-line text):
```bash
cat > /tmp/agent_chat_subagent_prompt.md << EOF
You are participating in a ping-pong chat session with another AI agent.

First, read $(dirname "$SCRIPT")/../SKILL.md to understand the protocol.

Then follow this loop:
  A. Listen:
     python3 $SCRIPT listen --session <SESSION_ID> --as <SUBAGENT_NAME> --timeout 600
  B. Check exit code:
     - 0: a message was printed → go to C
     - 3: [SESSION CLOSED] → stop immediately, do not call listen or send again, exit
     - 2: [TIMEOUT] → exit and report
  C. Compose your reply, then:
     python3 $SCRIPT send "<reply>" --session <SESSION_ID> --as <SUBAGENT_NAME>
  D. Go to A.

Context: <what you want the subagent to know>
Task: <what you want the subagent to discuss>

Rules:
- Do NOT edit files, run experiments, or take any action beyond the listen/send loop.
- This is discussion only. The transcript goes to a human for review afterwards.
EOF
```

Note: this uses an un-quoted heredoc (`EOF` not `'EOF'`) so `$SCRIPT` is substituted by the outer shell, producing a prompt with concrete paths.

**4. Launch the chosen subagent in the background and capture its PID.**

Codex:
```bash
codex exec --full-auto --cd "$(pwd)" \
  -c 'model_reasoning_effort="high"' \
  - < /tmp/agent_chat_subagent_prompt.md > /tmp/agent_chat_codex.log 2>&1 &
echo $! > /tmp/agent_chat_subagent.pid
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
  "$(cat /tmp/agent_chat_subagent_prompt.md)" \
  > /tmp/agent_chat_claude.log 2>&1 &
echo $! > /tmp/agent_chat_subagent.pid
```

Claude flags that matter:
- `-p` / `--print` — non-interactive mode
- `--dangerously-skip-permissions` — lets the subagent run the `listen`/`send` shell commands without interactive approval
- `--model` and `--effort` — tune model and reasoning depth for the session

Gemini CLI:
```bash
gemini --yolo \
  "$(cat /tmp/agent_chat_subagent_prompt.md)" \
  > /tmp/agent_chat_gemini.log 2>&1 &
echo $! > /tmp/agent_chat_subagent.pid
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

**5. Main agent runs its own send/listen loop as normal.** Wait a few seconds after launching the subagent before sending the opening, so the subagent has time to read the skill and start listening.

**6. When the discussion is done, call `end`. The subagent should exit on its own within a few seconds:**
- If its current `listen` is waiting, it detects the closed-session status (exit code 3) and exits.
- If `listen` already returned and it is about to `send`, the send errors with "Session is closed" (exit code 1) and the subagent exits.

**7. Safety-net kill** (only if the subagent is still running ~60s after `end`):
```bash
SUBAGENT_PID=$(cat /tmp/agent_chat_subagent.pid)
if kill -0 "$SUBAGENT_PID" 2>/dev/null; then
  kill "$SUBAGENT_PID"
fi
```

In practice the self-exit path is reliable (~5–10s) and the kill is rarely needed — but it is good hygiene.

---

## Deadlock / Timeout

`listen` exits with code 2 and prints `[TIMEOUT]` if no message arrives within the timeout (default 10 min). When this happens:

1. Check `status` to see whose turn it is and when the last activity was.
2. If the other agent appears stuck, alert the human.
3. Do **not** loop-retry `listen` automatically — the human decides whether to continue.
