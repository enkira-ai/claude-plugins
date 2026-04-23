#!/usr/bin/env python3
"""
agent_chat.py — Ping-pong inter-agent chat (Claude Code <-> Codex or any two agents).

Session files live under <git-root>/.agent_chat/sessions/<session-id>/.
Each agent writes to its own JSONL file; reads from the other's.

Commands:
  new-session   Create a session (human runs this, or main agent)
  send          Send a message
  listen        Block until the other agent sends, then print and exit
  status        Show round count, whose turn, last activity
  end           Mark session ended
  transcript    Merge both JSONLs into a Markdown file
  list          List sessions found in this repo
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WRAP_UP_ROUND = 50
FORCE_END_ROUND = 60
DEFAULT_LISTEN_TIMEOUT = 600  # 10 minutes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_git_root() -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        return None


def get_sessions_dir(interactive: bool = False) -> Path:
    root = find_git_root()
    if root:
        return root / ".agent_chat" / "sessions"
    if interactive:
        print("[agent_chat] Not inside a git repo.", file=sys.stderr)
        print("  Where should sessions live? (press Enter for ~/.agent_chat/sessions): ", end="", flush=True)
        ans = input().strip()
        base = Path(ans) if ans else Path.home() / ".agent_chat" / "sessions"
        return base
    # Non-interactive fallback: use cwd
    return Path.cwd() / ".agent_chat" / "sessions"


def load_meta(session_path: Path) -> dict:
    f = session_path / "metadata.json"
    if not f.exists():
        print(f"[agent_chat] Session not found: {session_path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(f.read_text())


def save_meta(session_path: Path, meta: dict) -> None:
    (session_path / "metadata.json").write_text(json.dumps(meta, indent=2))


def agent_out_file(session_path: Path, agent: str, meta: dict) -> Path:
    """The file this agent WRITES to."""
    agents = meta.get("agents", [])
    if agent not in agents:
        # Will be registered soon; use slot based on current count
        idx = len(agents)
    else:
        idx = agents.index(agent)
    if idx == 0:
        return session_path / f"{meta.get('agent_names', ['a', 'b'])[0]}_out.jsonl"
    return session_path / f"{meta.get('agent_names', ['a', 'b'])[1]}_out.jsonl"


def other_out_file(session_path: Path, agent: str, meta: dict) -> Path | None:
    """The file this agent READS from. Returns None if the other agent hasn't registered yet."""
    agents = meta.get("agents", [])
    names = meta.get("agent_names", [])
    if len(agents) < 2 or agent not in agents:
        return None
    idx = agents.index(agent)
    other_idx = 1 - idx
    return session_path / f"{names[other_idx]}_out.jsonl"


def append_record(path: Path, record: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")
        f.flush()
        os.fsync(f.fileno())


def next_seq(meta: dict) -> int:
    meta["_seq"] = meta.get("_seq", 0) + 1
    return meta["_seq"]


def compute_round(meta: dict) -> int:
    counts = meta.get("msg_counts", {})
    agents = meta.get("agents", [])
    if len(agents) < 2:
        return 0
    return min(counts.get(a, 0) for a in agents)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_new_session(args):
    sessions_dir = get_sessions_dir(interactive=True)

    date_str = datetime.now().strftime("%Y%m%d")
    n = 1
    while True:
        label = f"_{args.name}" if args.name else ""
        sid = f"session_{date_str}_{n}{label}"
        path = sessions_dir / sid
        if not path.exists():
            break
        n += 1

    path.mkdir(parents=True)

    meta = {
        "session_id": sid,
        "started": now_ts(),
        "main_agent": None,
        "agents": [],
        "agent_names": [],   # parallel to agents, tracks file-name slugs
        "msg_counts": {},    # {agent_name: int} — only 'message' type
        "_seq": 0,
        "whose_turn": "either",
        "status": "waiting",
        "last_activity": now_ts(),
        "wrap_up_sent": False,
        "force_end_sent": False,
    }
    save_meta(path, meta)

    print(f"Session created: {sid}")
    print(f"Location:        {path}")
    print()
    print("Next steps:")
    print(f"  Main agent:    python agent_chat.py send '<opening message>' --session {sid} --as <your-name>")
    print(f"  Other agent:   python agent_chat.py listen --session {sid} --as <your-name>")


def register_agent(session_path: Path, meta: dict, agent: str) -> None:
    """Add agent to session on first appearance. First registrant becomes main_agent."""
    if agent in meta["agents"]:
        return
    if len(meta["agents"]) >= 2:
        print(f"[agent_chat] Session already has 2 agents: {meta['agents']}", file=sys.stderr)
        sys.exit(1)

    # Use agent name as file slug (sanitised)
    slug = agent.replace(" ", "_").lower()
    meta["agents"].append(agent)
    meta["agent_names"].append(slug)
    meta["msg_counts"][agent] = 0

    # Create the JSONL file for this agent
    idx = len(meta["agents"]) - 1
    out = session_path / f"{meta['agent_names'][idx]}_out.jsonl"
    if not out.exists():
        out.touch()

    save_meta(session_path, meta)


def inject_system(out_file: Path, meta: dict, msg_type: str, msg: str) -> None:
    record = {
        "seq": next_seq(meta),
        "from": "system",
        "ts": now_ts(),
        "type": msg_type,
        "msg": msg,
    }
    append_record(out_file, record)


def cmd_send(args):
    sessions_dir = get_sessions_dir()
    session_path = sessions_dir / args.session
    meta = load_meta(session_path)

    if meta["status"] in ("ended", "force_ended"):
        print("[agent_chat] Session is closed. Run `transcript` to export.", file=sys.stderr)
        sys.exit(1)

    agent = args.as_agent
    register_agent(session_path, meta, agent)
    meta = load_meta(session_path)  # reload after register wrote it

    # First sender becomes the main agent
    if meta["main_agent"] is None:
        meta["main_agent"] = agent
        meta["status"] = "active"
        save_meta(session_path, meta)

    # Turn check
    if meta["whose_turn"] not in ("either", agent):
        if not args.force:
            print(f"[agent_chat] It's {meta['whose_turn']}'s turn. Use --force to override.", file=sys.stderr)
            sys.exit(1)

    out = agent_out_file(session_path, agent, meta)

    # Increment this agent's message count
    meta["msg_counts"][agent] = meta["msg_counts"].get(agent, 0) + 1
    current_round = compute_round(meta)

    # --- Milestone checks (inject system message BEFORE the real message) ---
    if current_round >= WRAP_UP_ROUND and not meta["wrap_up_sent"]:
        meta["wrap_up_sent"] = True
        inject_system(out, meta, "wrap_up_reminder", (
            f"[SYSTEM — Round {WRAP_UP_ROUND}] This conversation has reached {WRAP_UP_ROUND} rounds. "
            f"Main agent ({meta['main_agent']}): please start wrapping up — summarise conclusions, "
            f"list open questions, and prepare a report for human review. "
            f"The session will be force-closed at round {FORCE_END_ROUND} if not ended first."
        ))
        print(f"[agent_chat] ⚠  Round {WRAP_UP_ROUND} — wrap-up reminder injected.", file=sys.stderr)

    if current_round >= FORCE_END_ROUND and not meta["force_end_sent"]:
        meta["force_end_sent"] = True
        inject_system(out, meta, "force_end", (
            f"[SYSTEM — Round {FORCE_END_ROUND}] Force-closing session. "
            f"Main agent ({meta['main_agent']}): write your final report as your NEXT message, "
            f"then call `agent_chat.py end --session {args.session} --as {meta['main_agent']}`. "
            f"No further exchanges after that."
        ))
        meta["status"] = "force_ending"
        print(f"[agent_chat] ⛔ Round {FORCE_END_ROUND} — force-end injected. Main agent must close.", file=sys.stderr)

    # --- Write the actual message ---
    seq = next_seq(meta)
    record = {
        "seq": seq,
        "round": current_round,
        "from": agent,
        "ts": now_ts(),
        "type": "message",
        "msg": args.message,
    }
    append_record(out, record)

    # Update turn
    agents = meta["agents"]
    if len(agents) == 2:
        other = [a for a in agents if a != agent][0]
        meta["whose_turn"] = other
    meta["last_activity"] = now_ts()
    save_meta(session_path, meta)

    print(f"[agent_chat] Sent (round {current_round}, seq {seq}, turn → {meta['whose_turn']})")


def cmd_listen(args):
    sessions_dir = get_sessions_dir()
    session_path = sessions_dir / args.session
    meta = load_meta(session_path)

    agent = args.as_agent
    register_agent(session_path, meta, agent)
    meta = load_meta(session_path)

    # Wait for the other agent to register (they may not have joined yet)
    deadline = time.time() + args.timeout
    watch = other_out_file(session_path, agent, meta)
    while watch is None or not watch.exists():
        if meta.get("status") in ("ended", "force_ended"):
            print(f"[SESSION CLOSED] Session is {meta['status']}. Exiting.", flush=True)
            sys.exit(3)
        if time.time() > deadline:
            print(f"[TIMEOUT] Other agent never appeared ({args.timeout}s). Notify human.", flush=True)
            sys.exit(2)
        time.sleep(1)
        meta = load_meta(session_path)
        watch = other_out_file(session_path, agent, meta)

    # Per-agent read cursor: how many lines of the other agent's file have we already consumed?
    read_key = f"read_{agent}"
    skip = meta.get(read_key, 0)

    print(f"[agent_chat] Listening on {watch.name} (from line {skip}, timeout {args.timeout}s)...",
          file=sys.stderr, flush=True)

    deadline = time.time() + args.timeout
    lines_processed = 0

    with open(watch) as f:
        # Seek past already-read lines
        for _ in range(skip):
            f.readline()

        while True:
            line = f.readline()
            if line:
                line = line.strip()
                if not line:
                    continue
                lines_processed += 1
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue

                sender = rec.get("from", "?")
                msg = rec.get("msg", "")
                mtype = rec.get("type", "message")

                if mtype == "message":
                    print(f"\n[{sender}]: {msg}", flush=True)
                    # Persist updated cursor so next listen call skips this message
                    meta = load_meta(session_path)
                    meta[read_key] = skip + lines_processed
                    save_meta(session_path, meta)
                    return  # ping-pong: received one message, our turn now
                else:
                    # System message: print and continue listening
                    print(f"\n[SYSTEM]: {msg}", flush=True)

            else:
                # Check if session has been closed by the other agent
                current_meta = load_meta(session_path)
                if current_meta.get("status") in ("ended", "force_ended"):
                    print(
                        f"\n[SESSION CLOSED] Session is {current_meta['status']}. "
                        "No further messages expected. Exiting.",
                        flush=True
                    )
                    sys.exit(3)

                if time.time() > deadline:
                    print(
                        f"\n[TIMEOUT] No message in {args.timeout}s. "
                        "Check if the other agent is still active. Notify human if stuck.",
                        flush=True
                    )
                    sys.exit(2)
                time.sleep(0.5)


def cmd_status(args):
    sessions_dir = get_sessions_dir()
    session_path = sessions_dir / args.session
    meta = load_meta(session_path)

    r = compute_round(meta)
    print(f"Session:       {meta['session_id']}")
    print(f"Status:        {meta['status']}")
    print(f"Main agent:    {meta.get('main_agent', 'not set')}")
    print(f"Agents:        {', '.join(meta.get('agents', []))}")
    print(f"Round:         {r}")
    print(f"Whose turn:    {meta['whose_turn']}")
    print(f"Last activity: {meta['last_activity']}")
    if meta.get("wrap_up_sent"):
        print("⚠  Wrap-up reminder sent at round 50")
    if meta.get("force_end_sent"):
        print("⛔ Force-end injected at round 60")


def cmd_end(args):
    sessions_dir = get_sessions_dir()
    session_path = sessions_dir / args.session
    meta = load_meta(session_path)

    meta["status"] = "ended"
    meta["ended"] = now_ts()
    meta["ended_by"] = args.as_agent
    save_meta(session_path, meta)

    print(f"[agent_chat] Session {args.session} ended by {args.as_agent}.")
    print(f"[agent_chat] Generate transcript: python agent_chat.py transcript --session {args.session}")


def cmd_transcript(args):
    sessions_dir = get_sessions_dir()
    session_path = sessions_dir / args.session
    meta = load_meta(session_path)

    agents = meta.get("agents", [])
    names = meta.get("agent_names", [])

    # Read all records from both files
    all_records = []
    seen_system_seqs = set()

    for name in names:
        fpath = session_path / f"{name}_out.jsonl"
        if not fpath.exists():
            continue
        with open(fpath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    # Deduplicate system messages by (type, first-50-chars-of-msg)
                    if rec.get("type") != "message":
                        key = (rec.get("type"), rec.get("msg", "")[:60])
                        if key in seen_system_seqs:
                            continue
                        seen_system_seqs.add(key)
                    all_records.append(rec)
                except json.JSONDecodeError:
                    pass

    # Sort by seq
    all_records.sort(key=lambda r: r.get("seq", 0))

    # Build markdown — simple alternating format
    lines = [
        "# Agent Chat Transcript",
        "",
        f"**Session:** {meta['session_id']}  ",
        f"**Started:** {meta.get('started', '?')}  ",
    ]
    if meta.get("ended"):
        lines.append(f"**Ended:** {meta['ended']}  ")
    lines += [
        f"**Participants:** {', '.join(agents)}  ",
        f"**Rounds:** {compute_round(meta)}  ",
        "",
        "---",
        "",
    ]

    for rec in all_records:
        mtype = rec.get("type", "message")
        sender = rec.get("from", "?")
        msg = rec.get("msg", "")

        if mtype == "message":
            lines.append(f"**{sender}:**")
            lines.append("")
            lines.append(msg)
            lines.append("")
            lines.append("---")
            lines.append("")
        else:
            lines.append(f"> {msg}")
            lines.append("")

    transcript = "\n".join(lines)

    out_path = Path(args.out) if args.out else session_path / "transcript.md"
    out_path.write_text(transcript)
    print(f"[agent_chat] Transcript written to {out_path}")


def cmd_list(args):
    sessions_dir = get_sessions_dir()
    if not sessions_dir.exists():
        print("No sessions found.")
        return
    sessions = sorted(p for p in sessions_dir.iterdir() if p.is_dir())
    if not sessions:
        print("No sessions found.")
        return
    for sp in sessions:
        mf = sp / "metadata.json"
        if not mf.exists():
            continue
        m = json.loads(mf.read_text())
        r = compute_round(m)
        ag = ", ".join(m.get("agents", []))
        print(f"{sp.name:50} [{m.get('status','?'):12}] round={r:3}  agents={ag}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Ping-pong inter-agent chat")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("new-session", help="Create a new chat session")
    sp.add_argument("--name", help="Optional label appended to session ID")

    sp = sub.add_parser("send", help="Send a message")
    sp.add_argument("message")
    sp.add_argument("--session", required=True)
    sp.add_argument("--as", dest="as_agent", required=True, metavar="AGENT")
    sp.add_argument("--force", action="store_true", help="Send even if not your turn")

    sp = sub.add_parser("listen", help="Block until the other agent sends a message")
    sp.add_argument("--session", required=True)
    sp.add_argument("--as", dest="as_agent", required=True, metavar="AGENT")
    sp.add_argument("--timeout", type=int, default=DEFAULT_LISTEN_TIMEOUT,
                    metavar="SEC", help=f"Seconds before giving up (default {DEFAULT_LISTEN_TIMEOUT})")

    sp = sub.add_parser("status", help="Show session state")
    sp.add_argument("--session", required=True)

    sp = sub.add_parser("end", help="Mark session as ended")
    sp.add_argument("--session", required=True)
    sp.add_argument("--as", dest="as_agent", required=True, metavar="AGENT")

    sp = sub.add_parser("transcript", help="Generate Markdown transcript")
    sp.add_argument("--session", required=True)
    sp.add_argument("--out", help="Output path (default: session/transcript.md)")

    sub.add_parser("list", help="List sessions in this repo")

    args = p.parse_args()

    dispatch = {
        "new-session": cmd_new_session,
        "send": cmd_send,
        "listen": cmd_listen,
        "status": cmd_status,
        "end": cmd_end,
        "transcript": cmd_transcript,
        "list": cmd_list,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
