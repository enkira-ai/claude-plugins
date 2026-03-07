#!/usr/bin/env python3
"""Rename a Claude Code session by appending a /rename entry to history.jsonl."""

import json
import sys
import time
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
HISTORY_FILE = CLAUDE_DIR / "history.jsonl"


def get_session_project(session_id):
    """Find the project path for a given session ID."""
    if not HISTORY_FILE.exists():
        return None
    with open(HISTORY_FILE) as f:
        for line in f:
            try:
                obj = json.loads(line)
                if obj.get("sessionId") == session_id:
                    return obj.get("project", "")
            except json.JSONDecodeError:
                continue
    return None


def session_exists(session_id):
    """Check if a session ID exists (full or short match)."""
    if not HISTORY_FILE.exists():
        return None
    with open(HISTORY_FILE) as f:
        for line in f:
            try:
                obj = json.loads(line)
                sid = obj.get("sessionId", "")
                if sid == session_id or sid.startswith(session_id):
                    return sid
            except json.JSONDecodeError:
                continue
    return None


def main():
    if len(sys.argv) < 3:
        print("Usage: rename-session.py <session-id> <new-name>")
        print("  session-id: full or short (8-char) session ID")
        print("  new-name:   the new name for the session")
        sys.exit(1)

    session_id = sys.argv[1]
    new_name = " ".join(sys.argv[2:])

    # Resolve short IDs
    full_id = session_exists(session_id)
    if not full_id:
        print(f"Error: No session found matching '{session_id}'")
        sys.exit(1)

    project = get_session_project(full_id) or ""

    # Append a /rename entry to history.jsonl
    entry = {
        "display": f"/rename {new_name}",
        "pastedContents": {},
        "timestamp": int(time.time() * 1000),
        "project": project,
        "sessionId": full_id,
    }

    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

    print(f"Renamed session `{full_id[:8]}` to: {new_name}")


if __name__ == "__main__":
    main()
