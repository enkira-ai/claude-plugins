#!/usr/bin/env python3
"""Self-check for `send`'s auto-follow-into-listen behavior.

Runnable with no framework: `python3 test_send_follow.py`. Exercises:

  * follow paths — `--no-follow` returns immediately (exit 0); a normal `send`
    follows into listen and prints the peer's next turn (exit 0); a follow-listen
    with no reply times out with listen's exit code 2.
  * `--end` atomicity — a peer blocked in auto-follow sees the session close
    (exit 3) instead of replying to the final message.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parent / "agent_chat.py")


def run(args, cwd, timeout=20):
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        cwd=cwd, capture_output=True, text=True, timeout=timeout,
    )


def new_session(cwd, name):
    out = run(["new-session", "--name", name, "--participants", "a", "b"], cwd)
    return next(t for t in out.stdout.split() if t.startswith("session_"))


def wait_turn(cwd, sid, who, tries=200):
    meta_path = Path(cwd) / ".agent_chat" / "sessions" / sid / "metadata.json"
    for _ in range(tries):
        try:
            if json.loads(meta_path.read_text()).get("whose_turn") == who:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for turn → {who}")


def test_follow(cwd):
    sid = new_session(cwd, "follow")

    # --no-follow returns immediately.
    r = run(["send", "m1", "--session", sid, "--as", "a", "--no-follow"], cwd)
    assert r.returncode == 0, f"--no-follow exit {r.returncode}: {r.stderr}"
    assert "Sent" in r.stdout, r.stdout

    # b sends and follows (waiting for a); a then sends and its own follow-listen
    # times out (b never replies). b's follow must have printed a's message.
    b = subprocess.Popen(
        [sys.executable, SCRIPT, "send", "from-b", "--session", sid,
         "--as", "b", "--timeout", "12"],
        cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    wait_turn(cwd, sid, "a")
    r = run(["send", "from-a", "--session", sid, "--as", "a", "--timeout", "3"], cwd)
    assert r.returncode == 2, f"expected follow-timeout exit 2, got {r.returncode}: {r.stdout}"
    assert "[TIMEOUT]" in r.stdout, r.stdout

    b_out, _ = b.communicate(timeout=15)
    assert b.returncode == 0, f"b follow exit {b.returncode}: {b_out}"
    assert "[a]: from-a" in b_out, b_out


def test_end_atomic(cwd):
    sid = new_session(cwd, "end")

    # a opens (turn → b). b sends and enters auto-follow, waiting for a.
    run(["send", "open", "--session", sid, "--as", "a", "--no-follow"], cwd)
    wait_turn(cwd, sid, "b")
    b = subprocess.Popen(
        [sys.executable, SCRIPT, "send", "b-turn", "--session", sid,
         "--as", "b", "--timeout", "12"],
        cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    wait_turn(cwd, sid, "a")

    # a sends the final report with --end. b's follow-listen must see the closed
    # session and exit 3 WITHOUT sending another message.
    r = run(["send", "final", "--session", sid, "--as", "a", "--end"], cwd)
    assert r.returncode == 0, f"--end exit {r.returncode}: {r.stderr}"
    assert "Session ended" in r.stdout, r.stdout

    b_out, _ = b.communicate(timeout=15)
    assert b.returncode == 3, f"peer should exit 3 on close, got {b.returncode}: {b_out}"

    meta = json.loads((Path(cwd) / ".agent_chat" / "sessions" / sid / "metadata.json").read_text())
    assert meta["status"] == "ended", meta
    # b sent exactly once (b-turn); it must NOT have squeezed a reply past --end.
    assert meta["msg_counts"]["b"] == 1, f"peer replied after close: {meta['msg_counts']}"


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
        test_follow(d)
        test_end_atomic(d)
    print("OK: send auto-follow + --end atomic close behave correctly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
