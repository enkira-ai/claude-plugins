#!/usr/bin/env bash
# poll-for-pr.sh — wait for an OPEN PR that closes the given issue to appear.
#
# After epic-shepherd dispatches an implementer for an issue (rfc-loop /
# autopilot / inline), the orchestrator needs to know which PR number was
# opened so it can hand it off to pr-shepherd. This script polls until a
# matching PR appears or a wall-clock cap expires.
#
# Match criteria: an OPEN PR in the same repo whose
# `closingIssuesReferences` includes the issue. That is GitHub's
# authoritative source for "Closes #N" / "Fixes #N" / "Resolves #N" in PR
# bodies and commits.
#
# Usage:
#   poll-for-pr.sh <issue> [--repo owner/name] [--interval 60] [--cap 1800] [--once]
#
# Defaults: --interval 60s, --cap 1800s (30 min), --repo auto-detected
# from cwd. --once does a single check (useful when the orchestrator wants
# to poll its own cadence via ScheduleWakeup instead).
#
# Output:
#   On success → prints PR number to stdout, exit 0.
#   On timeout → exit 1 (orchestrator writes paused with reason
#                "no PR opened for issue #N within <cap>s").
#   Bad usage → exit 4.
#
# Read-only against GitHub; never mutates issues / PRs.
set -euo pipefail

issue=""
repo=""
interval=60
cap=1800
once=0

while [ $# -gt 0 ]; do
    case "$1" in
        --repo) repo="$2"; shift 2 ;;
        --interval) interval="$2"; shift 2 ;;
        --cap) cap="$2"; shift 2 ;;
        --once) once=1; shift ;;
        -h|--help) sed -n '3,$p' "$0" | sed -n 's/^# \?//;1,/^$/p' >&2; exit 0 ;;
        *)
            if [ -z "$issue" ]; then issue="$1"
            else echo "FATAL: unexpected arg: $1" >&2; exit 4
            fi
            shift
            ;;
    esac
done

[ -n "$issue" ] || { echo "FATAL: <issue> is required" >&2; exit 4; }
[[ "$issue" =~ ^[0-9]+$ ]] || { echo "FATAL: <issue> must be a number" >&2; exit 4; }
command -v gh >/dev/null || { echo "FATAL: gh required" >&2; exit 4; }

if [ -z "$repo" ]; then
    repo="$(gh repo view --json nameWithOwner -q .nameWithOwner)" \
        || { echo "FATAL: could not detect repo; pass --repo owner/name" >&2; exit 4; }
fi
owner="${repo%/*}"
name="${repo#*/}"

check_once() {
    # GraphQL: issue → closedByPullRequestsReferences (OPEN ones only).
    # That field is populated even while the PR is open and the issue is
    # also still open — it tracks the linking, not the closing event.
    # `// empty` keeps jq quiet if the issue itself doesn't exist
    # (returns null repository.issue rather than erroring).
    gh api graphql -F owner="$owner" -F name="$name" -F number="$issue" -f query='
        query($owner:String!, $name:String!, $number:Int!) {
            repository(owner:$owner, name:$name) {
                issue(number:$number) {
                    closedByPullRequestsReferences(first:20, includeClosedPrs:false) {
                        nodes { number state isDraft }
                    }
                }
            }
        }' 2>/dev/null | jq -r '
            (.data.repository.issue.closedByPullRequestsReferences.nodes // [])
            | map(select(.state == "OPEN"))
            | (.[0].number // empty)
        '
}

start=$(date +%s)
attempt=0
while :; do
    attempt=$((attempt + 1))
    pr="$(check_once || true)"
    if [ -n "$pr" ]; then
        echo "$pr"
        echo "  found PR #$pr for issue #$issue after ${attempt} poll(s)" >&2
        exit 0
    fi
    [ "$once" = "1" ] && { echo "  no PR yet for issue #$issue (--once)" >&2; exit 1; }
    now=$(date +%s)
    elapsed=$((now - start))
    if [ "$elapsed" -ge "$cap" ]; then
        echo "  timeout: no PR opened for issue #$issue in ${cap}s" >&2
        exit 1
    fi
    sleep "$interval"
done
