#!/usr/bin/env python3
"""Self-check for `send`'s auto-follow-into-listen behavior.

Runnable with no framework: `python3 test_send_follow.py`. Exercises the three
paths that the fused send+listen guard must get right:

  1. `--no-follow` returns immediately (exit 0, no block).
  2. A normal `send` follows into listen and prints the peer's next turn (exit 0).
  3. A follow-listen with no reply times out with listen's exit code 2.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = str(Path(__file__).resolve().parent / "agent_chat.py")


def run(args, cwd, timeout=20):
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        cwd=cwd, capture_output=True, text=True, timeout=timeout,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)

        out = run(["new-session", "--name", "t", "--participants", "a", "b"], d)
        sid = next(t for t in out.stdout.split() if t.startswith("session_"))

        # 1. --no-follow returns immediately.
        r = run(["send", "m1", "--session", sid, "--as", "a", "--no-follow"], d)
        assert r.returncode == 0, f"--no-follow exit {r.returncode}: {r.stderr}"
        assert "Sent" in r.stdout, r.stdout

        # 2 + 3. b sends and follows (background), waiting for a; a then sends and
        # its own follow-listen times out (b never replies). b's follow must have
        # printed a's message and exited 0.
        b = subprocess.Popen(
            [sys.executable, SCRIPT, "send", "from-b", "--session", sid,
             "--as", "b", "--timeout", "12"],
            cwd=d, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        # Give b time to send and enter its follow-listen.
        import time
        time.sleep(2)
        r = run(["send", "from-a", "--session", sid, "--as", "a", "--timeout", "3"], d)
        assert r.returncode == 2, f"expected follow-timeout exit 2, got {r.returncode}"
        assert "[TIMEOUT]" in r.stdout, r.stdout

        b_out, _ = b.communicate(timeout=15)
        assert b.returncode == 0, f"b follow exit {b.returncode}: {b_out}"
        assert "[a]: from-a" in b_out, b_out

    print("OK: send auto-follow behaves correctly (no-follow / round-trip / timeout)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
