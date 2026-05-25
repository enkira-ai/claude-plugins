#!/usr/bin/env python3
"""extract-sequence — snapshot a GitHub Epic's actionable sub-issue sequence.

Given an Epic (a GitHub issue that has sub-issues), this script:

  1. Lists every sub-issue via the GraphQL `subIssues` connection.
  2. Splits OPEN sub-issues (will be sequenced) from CLOSED (audit-only).
  3. For each OPEN sub-issue, fetches its `blocked_by` dependency list via
     the REST issue-dependencies API (GA as of 2025).
  4. Builds a DAG: blocker → blocked. In-epic blockers shape the topology;
     blockers outside the epic surface as ``external_blockers``.
  5. Topologically sorts into ``tier`` levels — every issue in tier N has
     all of its in-epic blockers in some tier < N. Items sharing a tier
     are parallel-eligible.
  6. Emits a JSON state file (default schema_version=1) that downstream
     epic-shepherd tick logic (Phase 2, future) consumes.

The output is a *snapshot* of the current state — re-run after any issue
closes to advance the sequence. Phase-1 callers can stop here; Phase-2
adds a loop that regenerates this snapshot every tick.

Usage:

    python3 extract-sequence.py --epic 437 [--repo enkira-ai/cong] \\
        [--out /tmp/epic-shepherd-state-437.json] [--default-implementer rfc-loop]

Auth: relies on the ``gh`` CLI being authenticated. No tokens read from
environment; ``gh`` provides them transparently.

Exit codes:

    0  state file written; sequence non-empty
    1  epic has no OPEN sub-issues (sequence empty — epic ready to close)
    2  epic not found, or has no sub-issues at all
    3  topology has a cycle (paused — operator must break the cycle)
    4  bad usage / ``gh`` not available / API failure

Schema (v1)::

    {
      "schema_version": 1,
      "epic": <int>,
      "epic_title": <str>,
      "repo": "<owner>/<name>",
      "generated_at": <ISO8601 UTC>,
      "default_implementer": "rfc-loop" | "autopilot" | "inline",
      "sequence": [
        {
          "issue": <int>,
          "title": <str (truncated to 100 chars)>,
          "tier": <int — 1 = ready now, N = blocked by some tier-K<N issue>,
          "blocked_by_in_epic": [<int>, ...]      (optional; omitted if empty)
          "external_blockers":   [<int>, ...]      (optional; omitted if empty)
          "parallel_with":       [<int>, ...]      (optional; same tier siblings)
        },
        ...
      ],
      "completed": [{"issue": <int>, "title": <str>}, ...],
      "in_flight_pr":    null | <int>,    (Phase-2 owns this field)
      "in_flight_issue": null | <int>,    (Phase-2 owns this field)
      "paused":          null | {"reason": <str>, "at": <ISO8601>},
      "external_blockers_total": <int>
    }

The script is read-only against GitHub. It never mutates issues or PRs.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys

DEFAULT_IMPLEMENTER = "rfc-loop"
TITLE_MAX = 100


def _run_gh(args: list[str]) -> str:
    """Run ``gh <args>`` and return stdout, raising RuntimeError on failure.

    Captures both streams; on failure includes stderr in the exception so
    the operator sees the real cause (auth expired, rate limit, etc.) rather
    than a bare non-zero exit.
    """
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"gh {' '.join(args)!r} exited {r.returncode}: "
            f"{(r.stderr or r.stdout).strip()}"
        )
    return r.stdout


def _gh_api_json(args: list[str]) -> object:
    """REST helper — ``gh api <args>`` decoded as JSON."""
    return json.loads(_run_gh(["api", *args]))


def _gh_graphql(query: str) -> dict:
    """GraphQL helper — sends ``query`` (no variables) via ``gh api graphql``."""
    return json.loads(_run_gh(["api", "graphql", "-f", f"query={query}"]))


def _detect_repo() -> str:
    """``owner/name`` of the current cwd's git repo, via ``gh repo view``."""
    out = _run_gh(["repo", "view", "--json", "nameWithOwner"]).strip()
    return json.loads(out)["nameWithOwner"]


def _fetch_epic(owner: str, name: str, epic: int) -> dict:
    """Return ``{title, subIssues: [{number, state, title}, ...]}`` for the epic.

    Raises if the issue doesn't exist or has no sub-issues at all (the
    caller turns that into exit code 2).

    gh's GraphQL surface returns a non-zero exit (caught by ``_run_gh``)
    on "Could not resolve to an Issue" — we re-raise that as a clean
    "issue not found" error so ``main`` can map it to exit 2.
    """
    q = (
        f'{{ repository(owner: "{owner}", name: "{name}") {{ '
        f'  issue(number: {epic}) {{ '
        f'    title '
        f'    subIssues(first: 100) {{ nodes {{ number state title }} }} '
        f'  }} '
        f'}} }}'
    )
    try:
        raw = _gh_graphql(q)
    except RuntimeError as exc:
        msg = str(exc)
        if "Could not resolve" in msg or "Resource not found" in msg:
            raise RuntimeError(
                f"issue #{epic} not found in {owner}/{name}"
            ) from exc
        raise
    data = raw["data"]["repository"].get("issue") if raw.get("data") else None
    if data is None:
        raise RuntimeError(f"issue #{epic} not found in {owner}/{name}")
    return data


def _fetch_blockers(owner: str, name: str, issue: int) -> list[dict]:
    """Return the open + closed ``blocked_by`` list for ``issue``.

    The dependency API returns ``[]`` (HTTP 200) for an issue with no deps.
    On HTTP 404 (some tenants still classify it preview) we treat that as
    "no deps" so the snapshot still completes — same pattern as
    ``.github/scripts/auto-unblock.sh`` in cong.
    """
    try:
        return _gh_api_json([
            f"repos/{owner}/{name}/issues/{issue}/dependencies/blocked_by"
        ])
    except RuntimeError as exc:
        if "404" in str(exc) or "Not Found" in str(exc):
            return []
        raise


def _build_state(
    owner: str,
    name: str,
    epic: int,
    default_implementer: str,
) -> tuple[dict, int]:
    """Return ``(state_dict, exit_code)``.

    Exit code mapping (so the CLI can return it without re-deriving from
    the state):

        0  sequence non-empty
        1  no OPEN sub-issues (epic ready to close)
        3  topology contains a cycle (paused)
    """
    epic_data = _fetch_epic(owner, name, epic)
    subs = epic_data["subIssues"]["nodes"]
    if not subs:
        raise RuntimeError(
            f"epic #{epic} has no sub-issues — nothing to sequence"
        )

    open_subs = sorted(
        [s for s in subs if s["state"] == "OPEN"], key=lambda s: s["number"]
    )
    closed_subs = sorted(
        [s for s in subs if s["state"] == "CLOSED"], key=lambda s: s["number"]
    )
    open_nums: set[int] = {s["number"] for s in open_subs}

    # Build in-epic + external dep maps.
    in_epic_blockers: dict[int, list[int]] = {}
    external_blockers: dict[int, list[int]] = {}
    for s in open_subs:
        n = s["number"]
        in_epic_blockers[n] = []
        external_blockers[n] = []
        for b in _fetch_blockers(owner, name, n):
            if b.get("state") != "open":
                continue
            if b["number"] in open_nums:
                in_epic_blockers[n].append(b["number"])
            else:
                external_blockers[n].append(b["number"])

    # Topological tiering.
    sub_lookup = {s["number"]: s for s in open_subs}
    remaining = set(open_nums)
    tiers: list[list[int]] = []
    while remaining:
        frontier = sorted(
            n for n in remaining
            if not (set(in_epic_blockers[n]) & remaining)
        )
        if not frontier:
            # cycle — pause and surface
            return (
                {
                    "schema_version": 1,
                    "epic": epic,
                    "epic_title": epic_data["title"],
                    "repo": f"{owner}/{name}",
                    "generated_at": _utcnow(),
                    "default_implementer": default_implementer,
                    "sequence": [],
                    "completed": [
                        {"issue": s["number"], "title": _truncate(s["title"])}
                        for s in closed_subs
                    ],
                    "in_flight_pr": None,
                    "in_flight_issue": None,
                    "paused": {
                        "reason": (
                            f"cycle in blocked_by graph among sub-issues "
                            f"{sorted(remaining)}"
                        ),
                        "at": _utcnow(),
                    },
                    "external_blockers_total": sum(
                        len(v) for v in external_blockers.values()
                    ),
                },
                3,
            )
        for n in frontier:
            sub_lookup[n]["_tier"] = len(tiers) + 1
        tiers.append(frontier)
        remaining -= set(frontier)

    # Emit sequence with tier + parallel_with annotations.
    sequence = []
    for frontier in tiers:
        siblings = sorted(frontier)
        for n in siblings:
            s = sub_lookup[n]
            item: dict = {
                "issue": n,
                "title": _truncate(s["title"]),
                "tier": s["_tier"],
            }
            if in_epic_blockers[n]:
                item["blocked_by_in_epic"] = sorted(in_epic_blockers[n])
            if external_blockers[n]:
                item["external_blockers"] = sorted(external_blockers[n])
            if len(siblings) > 1:
                item["parallel_with"] = [m for m in siblings if m != n]
            sequence.append(item)

    state = {
        "schema_version": 1,
        "epic": epic,
        "epic_title": epic_data["title"],
        "repo": f"{owner}/{name}",
        "generated_at": _utcnow(),
        "default_implementer": default_implementer,
        "sequence": sequence,
        "completed": [
            {"issue": s["number"], "title": _truncate(s["title"])}
            for s in closed_subs
        ],
        "in_flight_pr": None,
        "in_flight_issue": None,
        "paused": None,
        "external_blockers_total": sum(
            len(v) for v in external_blockers.values()
        ),
    }
    return state, (0 if sequence else 1)


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _truncate(s: str, n: int = TITLE_MAX) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _atomic_write(path: str, payload: str) -> None:
    """Write ``payload`` to ``path`` atomically (tmp then rename).

    Phase 2's tick loop competes with itself on this file; the rename keeps
    a reader from seeing a half-written state. The tmp lives in the same
    directory so rename is atomic on POSIX.
    """
    d = os.path.dirname(os.path.abspath(path)) or "."
    tmp = f"{path}.tmp.{os.getpid()}"
    os.makedirs(d, exist_ok=True)
    with open(tmp, "w") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--epic", type=int, required=True,
        help="GitHub Epic issue number (an issue with sub-issues).",
    )
    ap.add_argument(
        "--repo", default=None,
        help="<owner>/<name>; defaults to gh-detected from cwd.",
    )
    ap.add_argument(
        "--out", default=None,
        help=(
            "Output path for the JSON state file. Defaults to "
            "/tmp/epic-shepherd-state-<epic>.json. Use '-' for stdout."
        ),
    )
    ap.add_argument(
        "--default-implementer", default=DEFAULT_IMPLEMENTER,
        choices=("rfc-loop", "autopilot", "inline"),
        help=(
            "Implementer used by Phase-2 ticks for sequence items that do "
            "not override it. Default 'rfc-loop' (safer; enforces TDD)."
        ),
    )
    args = ap.parse_args(argv)

    try:
        repo = args.repo or _detect_repo()
    except RuntimeError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 4
    if "/" not in repo:
        print(f"FATAL: --repo must be 'owner/name', got {repo!r}", file=sys.stderr)
        return 4
    owner, name = repo.split("/", 1)

    try:
        state, code = _build_state(
            owner, name, args.epic, args.default_implementer
        )
    except RuntimeError as exc:
        msg = str(exc)
        print(f"FATAL: {msg}", file=sys.stderr)
        if "not found" in msg or "no sub-issues" in msg:
            return 2
        return 4

    payload = json.dumps(state, indent=2) + "\n"
    out = args.out or f"/tmp/epic-shepherd-state-{args.epic}.json"
    if out == "-":
        sys.stdout.write(payload)
    else:
        _atomic_write(out, payload)
        # tier breakdown to stderr so stdout is JSON-only for piping
        tiers: dict[int, list[int]] = {}
        for item in state["sequence"]:
            tiers.setdefault(item["tier"], []).append(item["issue"])
        print(f"wrote {out}", file=sys.stderr)
        print(
            f"  epic={args.epic} repo={repo} "
            f"sequence={len(state['sequence'])} "
            f"completed={len(state['completed'])} "
            f"external_blockers_total={state['external_blockers_total']}",
            file=sys.stderr,
        )
        for t in sorted(tiers):
            tag = " (parallel)" if len(tiers[t]) > 1 else ""
            print(f"  tier {t}{tag}: {tiers[t]}", file=sys.stderr)
        if state["paused"]:
            print(
                f"  PAUSED: {state['paused']['reason']}",
                file=sys.stderr,
            )

    return code


if __name__ == "__main__":
    sys.exit(main())
