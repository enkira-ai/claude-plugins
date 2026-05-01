#!/usr/bin/env python3
"""
agent_chat.py — Multi-agent round-robin chat (2..N agents).

Session files live under <git-root>/.agent_chat/sessions/<session-id>/.
Each agent writes to its own JSONL file; reads from every peer's file.

Commands:
  new-session    Create a session (optionally pre-declare --participants)
  send           Send a message
  listen         Block until it's your turn AND a peer has sent a new message
  status         Show round count, whose turn, last activity
  end            Mark session ended
  transcript     Merge all JSONLs into a Markdown file (incl. setup prompts)
  record-prompt  Save a subagent setup prompt + launcher into the session
  list           List sessions found in this repo
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


def slugify(name: str) -> str:
    return name.replace(" ", "_").lower()


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
    if agent not in meta["agents"]:
        raise RuntimeError(f"Agent {agent!r} is not registered in this session")
    idx = meta["agents"].index(agent)
    return session_path / f"{meta['agent_names'][idx]}_out.jsonl"


def peer_out_files(session_path: Path, agent: str, meta: dict) -> dict:
    """Map peer-name -> file this agent reads from."""
    return {
        peer: session_path / f"{meta['agent_names'][i]}_out.jsonl"
        for i, peer in enumerate(meta["agents"])
        if peer != agent
    }


def read_records(fpath: Path) -> list:
    if not fpath.exists():
        return []
    out = []
    with open(fpath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


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

    participants = args.participants or []
    # Validate: no duplicates, no slug collisions
    if participants:
        if len(set(participants)) != len(participants):
            print("[agent_chat] --participants must be unique", file=sys.stderr)
            sys.exit(1)
        slugs = [slugify(p) for p in participants]
        if len(set(slugs)) != len(slugs):
            print(f"[agent_chat] participant names produce duplicate slugs: {slugs}", file=sys.stderr)
            sys.exit(1)
        if len(participants) < 2:
            print("[agent_chat] --participants needs at least 2 names", file=sys.stderr)
            sys.exit(1)

    agents = list(participants)
    agent_names = [slugify(a) for a in agents]
    msg_counts = {a: 0 for a in agents}

    meta = {
        "session_id": sid,
        "started": now_ts(),
        "main_agent": None,
        "predeclared": bool(participants),
        "agents": agents,
        "agent_names": agent_names,
        "msg_counts": msg_counts,
        "_seq": 0,
        "whose_turn": "either",
        "status": "waiting",
        "last_activity": now_ts(),
        "wrap_up_sent": False,
        "force_end_sent": False,
        "read_cursors": {},
        "setup": [],
    }
    save_meta(path, meta)

    # Pre-create the JSONL file for each declared participant
    for slug in agent_names:
        (path / f"{slug}_out.jsonl").touch()

    print(f"Session created: {sid}")
    print(f"Location:        {path}")
    if participants:
        print(f"Participants:    {', '.join(participants)} (round-robin in this order)")
        print()
        print("Next steps:")
        first = participants[0]
        print(f"  Main agent ({first}):")
        print(f"    python agent_chat.py send '<opening>' --session {sid} --as {first}")
        for p in participants[1:]:
            print(f"  Other ({p}):")
            print(f"    python agent_chat.py listen --session {sid} --as {p}")
    else:
        print()
        print("Next steps (legacy 2-agent lazy mode):")
        print(f"  Main agent:    python agent_chat.py send '<opening>' --session {sid} --as <your-name>")
        print(f"  Other agent:   python agent_chat.py listen --session {sid} --as <your-name>")


def register_agent(session_path: Path, meta: dict, agent: str) -> None:
    """For pre-declared sessions: validate. For lazy 2-agent: register on first appearance."""
    if meta.get("predeclared"):
        if agent not in meta["agents"]:
            print(
                f"[agent_chat] '{agent}' is not in the pre-declared participants: {meta['agents']}",
                file=sys.stderr,
            )
            sys.exit(1)
        return

    if agent in meta["agents"]:
        return
    if len(meta["agents"]) >= 2:
        print(f"[agent_chat] Session already has 2 agents: {meta['agents']}. "
              f"Create a new session with --participants for >2 agents.", file=sys.stderr)
        sys.exit(1)

    slug = slugify(agent)
    meta["agents"].append(agent)
    meta["agent_names"].append(slug)
    meta["msg_counts"][agent] = 0

    out = session_path / f"{slug}_out.jsonl"
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
    meta = load_meta(session_path)

    # First sender becomes the main agent
    if meta["main_agent"] is None:
        meta["main_agent"] = agent
        meta["status"] = "active"
        save_meta(session_path, meta)

    # Turn check
    if meta["whose_turn"] not in ("either", agent):
        if not args.force:
            print(f"[agent_chat] It's {meta['whose_turn']}'s turn. Use --force to override.",
                  file=sys.stderr)
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
        print(f"[agent_chat] ⛔ Round {FORCE_END_ROUND} — force-end injected. Main agent must close.",
              file=sys.stderr)

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

    # Round-robin turn advance
    agents = meta["agents"]
    if len(agents) >= 2:
        idx = agents.index(agent)
        next_idx = (idx + 1) % len(agents)
        meta["whose_turn"] = agents[next_idx]
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

    deadline = time.time() + args.timeout

    # Wait until at least one peer is registered
    while True:
        meta = load_meta(session_path)
        if meta.get("status") in ("ended", "force_ended"):
            print(f"[SESSION CLOSED] Session is {meta['status']}. Exiting.", flush=True)
            sys.exit(3)
        peers = [a for a in meta["agents"] if a != agent]
        if peers:
            break
        if time.time() > deadline:
            print(f"[TIMEOUT] No peers registered ({args.timeout}s). Notify human.", flush=True)
            sys.exit(2)
        time.sleep(1)

    print(
        f"[agent_chat] Listening as {agent}; peers={peers}; timeout={args.timeout}s",
        file=sys.stderr, flush=True,
    )

    cursors = dict(meta.get("read_cursors", {}).get(agent, {}))
    # cursors: {peer_name: n_records_consumed}

    while True:
        meta = load_meta(session_path)
        if meta.get("status") in ("ended", "force_ended"):
            print(
                f"\n[SESSION CLOSED] Session is {meta['status']}. "
                "No further messages expected. Exiting.",
                flush=True,
            )
            sys.exit(3)

        peers = [a for a in meta["agents"] if a != agent]
        name_for = dict(zip(meta["agents"], meta["agent_names"]))

        all_unread = []  # list[(peer, record)]
        new_per_peer = {}
        for peer in peers:
            fpath = session_path / f"{name_for[peer]}_out.jsonl"
            records = read_records(fpath)
            consumed = cursors.get(peer, 0)
            unread = records[consumed:]
            new_per_peer[peer] = len(unread)
            for rec in unread:
                all_unread.append((peer, rec))

        all_unread.sort(key=lambda x: x[1].get("seq", 0))
        has_msg = any(rec.get("type") == "message" for _, rec in all_unread)

        whose = meta.get("whose_turn", "either")
        # Exit when it's our turn AND a peer has an unread message.
        # "either" means turn-enforcement is not yet active (lazy 2-agent mode:
        # the first send fires before the second agent registers, so whose_turn
        # is never updated from "either"). Treat it as "anyone's turn" — if
        # there's an unread peer message it is for us.
        our_turn = (whose == agent or whose == "either")
        if our_turn and has_msg:
            for peer, rec in all_unread:
                sender = rec.get("from", "?")
                msg = rec.get("msg", "")
                mtype = rec.get("type", "message")
                if mtype == "message":
                    print(f"\n[{sender}]: {msg}", flush=True)
                else:
                    print(f"\n[SYSTEM]: {msg}", flush=True)
            # Persist cursors based on what we actually consumed
            new_cursors = dict(cursors)
            for peer in peers:
                new_cursors[peer] = cursors.get(peer, 0) + new_per_peer[peer]
            meta = load_meta(session_path)
            meta.setdefault("read_cursors", {})[agent] = new_cursors
            save_meta(session_path, meta)
            return

        if time.time() > deadline:
            print(
                f"\n[TIMEOUT] No turn-message in {args.timeout}s. "
                "Check if peers are still active. Notify human if stuck.",
                flush=True,
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
    print(f"Participants:  {', '.join(meta.get('agents', []))} "
          f"({'pre-declared' if meta.get('predeclared') else 'lazy'})")
    print(f"Round:         {r}")
    print(f"Whose turn:    {meta['whose_turn']}")
    print(f"Last activity: {meta['last_activity']}")
    counts = meta.get("msg_counts", {})
    if counts:
        per_agent = ", ".join(f"{a}={n}" for a, n in counts.items())
        print(f"Messages:      {per_agent}")
    if meta.get("setup"):
        print(f"Setup prompts: {len(meta['setup'])} recorded")
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


def cmd_record_prompt(args):
    sessions_dir = get_sessions_dir()
    session_path = sessions_dir / args.session
    meta = load_meta(session_path)

    if args.prompt_file:
        prompt_text = Path(args.prompt_file).read_text()
    elif args.prompt:
        prompt_text = args.prompt
    else:
        print("[agent_chat] Provide --prompt or --prompt-file", file=sys.stderr)
        sys.exit(1)

    meta.setdefault("setup", []).append({
        "launched_by": args.by,
        "target": args.target,
        "ts": now_ts(),
        "prompt": prompt_text,
        "launcher": args.launcher,
    })
    save_meta(session_path, meta)
    print(f"[agent_chat] Setup prompt recorded for target='{args.target}' "
          f"(launched by '{args.by}', {len(prompt_text)} chars)")


def cmd_transcript(args):
    sessions_dir = get_sessions_dir()
    session_path = sessions_dir / args.session
    meta = load_meta(session_path)

    agents = meta.get("agents", [])
    names = meta.get("agent_names", [])

    # Read all records from every agent's file
    all_records = []
    seen_system = set()

    for name in names:
        fpath = session_path / f"{name}_out.jsonl"
        if not fpath.exists():
            continue
        for rec in read_records(fpath):
            # Deduplicate system messages: every listener may have flushed the
            # same notice into their stream when they pulled unread, but they
            # also exist once in the original sender's file.
            if rec.get("type") != "message":
                key = (rec.get("type"), rec.get("msg", "")[:60])
                if key in seen_system:
                    continue
                seen_system.add(key)
            all_records.append(rec)

    all_records.sort(key=lambda r: r.get("seq", 0))

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
        f"**Main agent:** {meta.get('main_agent', '?')}  ",
        f"**Rounds:** {compute_round(meta)}  ",
        "",
        "---",
        "",
    ]

    setup = meta.get("setup") or []
    if setup:
        lines += [
            "## Subagent setup",
            "",
            "Prompts and launcher commands the main agent used to spawn each subagent. "
            "Useful for auditing whether the discussion was set up with adequate context.",
            "",
        ]
        for entry in setup:
            target = entry.get("target", "?")
            by = entry.get("launched_by", "?")
            ts = entry.get("ts", "?")
            lines.append(f"### Spawned `{target}` (by `{by}` at {ts})")
            lines.append("")
            if entry.get("launcher"):
                lines.append("**Launcher command:**")
                lines.append("")
                lines.append("```")
                lines.append(entry["launcher"])
                lines.append("```")
                lines.append("")
            lines.append("**Prompt:**")
            lines.append("")
            # Use 4-backtick fence in case prompt itself contains 3-backtick code blocks
            lines.append("````markdown")
            lines.append(entry.get("prompt", ""))
            lines.append("````")
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## Conversation")
    lines.append("")

    for rec in all_records:
        mtype = rec.get("type", "message")
        sender = rec.get("from", "?")
        msg = rec.get("msg", "")
        rnd = rec.get("round")

        if mtype == "message":
            header = f"**{sender}**"
            if rnd is not None:
                header += f" — round {rnd}"
            lines.append(header)
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
    p = argparse.ArgumentParser(description="Multi-agent round-robin chat")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("new-session", help="Create a new chat session")
    sp.add_argument("--name", help="Optional label appended to session ID")
    sp.add_argument(
        "--participants", nargs="+", metavar="AGENT",
        help="Pre-declare 2..N participants by name (round-robin order). "
             "First listed is conventionally the main agent. "
             "Omit for legacy lazy 2-agent mode.",
    )

    sp = sub.add_parser("send", help="Send a message")
    sp.add_argument("message")
    sp.add_argument("--session", required=True)
    sp.add_argument("--as", dest="as_agent", required=True, metavar="AGENT")
    sp.add_argument("--force", action="store_true", help="Send even if not your turn")

    sp = sub.add_parser("listen", help="Block until it's your turn AND a peer has sent a new message")
    sp.add_argument("--session", required=True)
    sp.add_argument("--as", dest="as_agent", required=True, metavar="AGENT")
    sp.add_argument("--timeout", type=int, default=DEFAULT_LISTEN_TIMEOUT, metavar="SEC",
                    help=f"Seconds before giving up (default {DEFAULT_LISTEN_TIMEOUT})")

    sp = sub.add_parser("status", help="Show session state")
    sp.add_argument("--session", required=True)

    sp = sub.add_parser("end", help="Mark session as ended")
    sp.add_argument("--session", required=True)
    sp.add_argument("--as", dest="as_agent", required=True, metavar="AGENT")

    sp = sub.add_parser("record-prompt",
                        help="Save a subagent setup prompt + launcher into the session for audit")
    sp.add_argument("--session", required=True)
    sp.add_argument("--by", required=True, metavar="AGENT",
                    help="Main agent that spawned the subagent")
    sp.add_argument("--target", required=True, metavar="AGENT",
                    help="Subagent name being spawned")
    sp.add_argument("--prompt", help="Prompt text (or use --prompt-file)")
    sp.add_argument("--prompt-file", dest="prompt_file",
                    help="Path to prompt file (preferred for multi-line prompts)")
    sp.add_argument("--launcher",
                    help="Optional launcher command line, recorded verbatim for audit")

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
        "record-prompt": cmd_record_prompt,
        "transcript": cmd_transcript,
        "list": cmd_list,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
