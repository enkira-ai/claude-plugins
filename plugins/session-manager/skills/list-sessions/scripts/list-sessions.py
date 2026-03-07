#!/usr/bin/env python3
"""List all Claude Code sessions from history.jsonl with last access date, ID, and name."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
HISTORY_FILE = CLAUDE_DIR / "history.jsonl"


def load_sessions():
    """Parse history.jsonl and collect session metadata."""
    if not HISTORY_FILE.exists():
        print("No history file found at", HISTORY_FILE)
        sys.exit(1)

    sessions = {}
    with open(HISTORY_FILE) as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            sid = obj.get("sessionId", "")
            if not sid:
                continue

            ts = obj.get("timestamp")
            display = str(obj.get("display", ""))
            project = str(obj.get("project", ""))

            if sid not in sessions:
                sessions[sid] = {
                    "first_ts": ts,
                    "last_ts": ts,
                    "display": display,
                    "project": project,
                }
            else:
                entry = sessions[sid]
                if ts is not None:
                    if entry["last_ts"] is None or ts > entry["last_ts"]:
                        entry["last_ts"] = ts
                    if entry["first_ts"] is None or ts < entry["first_ts"]:
                        entry["first_ts"] = ts
                # Keep the first non-empty display
                if not entry["display"] and display:
                    entry["display"] = display

    return sessions


def format_ts(ts):
    """Convert epoch-ms timestamp to human-readable date string."""
    if ts is None:
        return "Unknown"
    try:
        dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return "Unknown"


def shorten_project(project):
    """Shorten project path for display."""
    home = str(Path.home())
    if project.startswith(home):
        return "~" + project[len(home):]
    return project


def main():
    sessions = load_sessions()

    if not sessions:
        print("No sessions found.")
        sys.exit(0)

    # Sort by last access time descending
    sorted_sessions = sorted(
        sessions.items(),
        key=lambda x: x[1]["last_ts"] if x[1]["last_ts"] is not None else 0,
        reverse=True,
    )

    # Print markdown table
    print("| Last Access      | Session ID (short) | Full Session ID                          | Project              | Name / First Message          |")
    print("|------------------|--------------------|------------------------------------------|----------------------|-------------------------------|")

    for sid, info in sorted_sessions:
        last = format_ts(info["last_ts"])
        short_id = sid[:8]
        project = shorten_project(info["project"])
        display = info["display"][:50] if info["display"] else "(no name)"
        # Escape pipes in display
        display = display.replace("|", "\\|")
        project = project.replace("|", "\\|")
        print(f"| {last:<16} | `{short_id}` | `{sid}` | {project:<20} | {display} |")

    print()
    print(f"**Total sessions:** {len(sorted_sessions)}")
    print()
    print("Resume a session with: `claude --resume <session-id>`")


if __name__ == "__main__":
    main()
