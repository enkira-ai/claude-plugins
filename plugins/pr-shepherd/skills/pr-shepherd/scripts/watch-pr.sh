#!/usr/bin/env bash
#
# watch-pr.sh — observe-only CI / review-thread poll loop for the pr-shepherd skill.
#
# This script NEVER mutates anything: it does not merge, cancel a check, push,
# resolve a thread, or comment. It polls a PR's state and exits with a code that
# tells the calling agent what to do next. Re-deriving this loop by hand is
# exactly how a healthy CI run gets wrongly cancelled — so it lives here, once.
#
# Usage:
#   watch-pr.sh <PR-number> [--repo owner/repo] [--timeout S] [--interval S] [--grace S]
#
# Exit codes:
#   0  GATE GREEN   — all CI green, 0 unresolved review threads
#   2  NEEDS RESYNC — mergeStateStatus is BEHIND / DIRTY (rebase onto main)
#   3  CI NO-SHOW   — no CI checks appeared within the grace window
#   4  CI FAILED    — a check is failing or cancelled
#   5  HARD STOP    — draft / human CHANGES_REQUESTED / BLOCKED / PR closed
#   6  TIMEOUT      — wall-clock cap reached with CI still pending
#   7  THREADS OPEN — CI green but unresolved review threads remain
#  64  USAGE/ENV    — bad arguments or missing gh/jq
#
set -uo pipefail

PR=""
REPO=""
TIMEOUT=7200      # 2h — generous enough for slow test suites; tune with --timeout
INTERVAL=60
GRACE=300         # CI no-show window

usage() {
  echo "usage: watch-pr.sh <PR-number> [--repo owner/repo] [--timeout S] [--interval S] [--grace S]" >&2
  exit 64
}

while [ $# -gt 0 ]; do
  case "$1" in
    --repo)     REPO="${2:-}";     shift 2 ;;
    --timeout)  TIMEOUT="${2:-}";  shift 2 ;;
    --interval) INTERVAL="${2:-}"; shift 2 ;;
    --grace)    GRACE="${2:-}";    shift 2 ;;
    -h|--help)  usage ;;
    --*)        echo "watch-pr.sh: unknown flag: $1" >&2; usage ;;
    *)
      if [ -z "$PR" ]; then PR="$1"; shift
      else echo "watch-pr.sh: unexpected argument: $1" >&2; usage; fi ;;
  esac
done

[ -n "$PR" ] || usage
case "$PR" in *[!0-9]*) echo "watch-pr.sh: PR must be a number, got: $PR" >&2; usage ;; esac
case "${TIMEOUT}${INTERVAL}${GRACE}" in *[!0-9]*) echo "watch-pr.sh: timeout/interval/grace must be integers" >&2; usage ;; esac

command -v gh >/dev/null 2>&1 || { echo "watch-pr.sh: gh CLI not found" >&2; exit 64; }
command -v jq >/dev/null 2>&1 || { echo "watch-pr.sh: jq not found" >&2; exit 64; }

if [ -z "$REPO" ]; then
  REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)
fi
[ -n "$REPO" ] || { echo "watch-pr.sh: could not determine repo — pass --repo owner/repo" >&2; exit 64; }
OWNER="${REPO%%/*}"
NAME="${REPO##*/}"

ts()  { date -u +%H:%M:%S; }
log() { echo "[$(ts)] $*"; }

log "watch-pr.sh: PR #$PR in $REPO  (timeout=${TIMEOUT}s interval=${INTERVAL}s grace=${GRACE}s)"

START=$(date +%s)
poll=0

while :; do
  poll=$((poll + 1))
  elapsed=$(( $(date +%s) - START ))

  # ---- PR view: state / draft / merge state / reviews -----------------------
  view=$(gh pr view "$PR" --repo "$REPO" \
      --json state,isDraft,mergeStateStatus,mergeable,reviewDecision,reviews 2>/dev/null || true)
  if [ -z "$view" ] || ! echo "$view" | jq -e . >/dev/null 2>&1; then
    log "poll $poll (${elapsed}s): gh pr view failed (network?) — will retry"
    [ "$elapsed" -ge "$TIMEOUT" ] && { log "RESULT: TIMEOUT (could not read PR)"; exit 6; }
    sleep "$INTERVAL"; continue
  fi

  state=$(echo "$view" | jq -r '.state // "UNKNOWN"')
  draft=$(echo "$view" | jq -r '.isDraft // false')
  merge_state=$(echo "$view" | jq -r '.mergeStateStatus // "UNKNOWN"')
  mergeable=$(echo "$view" | jq -r '.mergeable // "UNKNOWN"')

  # ---- terminal PR states ---------------------------------------------------
  if [ "$state" = "MERGED" ]; then log "RESULT: PR #$PR is already MERGED"; exit 0; fi
  if [ "$state" = "CLOSED" ]; then log "RESULT: PR #$PR is CLOSED (hard stop)"; exit 5; fi

  # ---- hard stops -----------------------------------------------------------
  if [ "$draft" = "true" ]; then
    log "RESULT: PR #$PR is a draft (hard stop)"; exit 5
  fi

  # latest review per non-bot author — any outstanding CHANGES_REQUESTED?
  human_cr=$(echo "$view" | jq -r '
    [ .reviews[]?
      | select(((.author.login // "") | endswith("[bot]")) | not)
      | {login: (.author.login // "?"), state: .state, at: (.submittedAt // "")} ]
    | group_by(.login)
    | map(sort_by(.at) | last)
    | map(select(.state == "CHANGES_REQUESTED"))
    | length' 2>/dev/null || echo 0)
  if [ "${human_cr:-0}" -gt 0 ]; then
    log "RESULT: a human reviewer has CHANGES_REQUESTED outstanding (hard stop)"; exit 5
  fi

  if [ "$merge_state" = "BLOCKED" ]; then
    log "RESULT: mergeStateStatus=BLOCKED — branch protection unsatisfied (hard stop)"; exit 5
  fi

  # ---- needs resync ---------------------------------------------------------
  if [ "$merge_state" = "DIRTY" ] || [ "$merge_state" = "BEHIND" ] || [ "$mergeable" = "CONFLICTING" ]; then
    log "RESULT: mergeStateStatus=$merge_state mergeable=$mergeable — branch needs rebase onto main"
    exit 2
  fi

  # ---- CI checks ------------------------------------------------------------
  checks=$(gh pr checks "$PR" --repo "$REPO" --json name,bucket,state 2>/dev/null || true)
  echo "$checks" | jq -e 'type == "array"' >/dev/null 2>&1 || checks="[]"
  n_checks=$(echo "$checks" | jq 'length' 2>/dev/null || echo 0)
  n_fail=$(echo "$checks"   | jq '[.[] | select(.bucket=="fail" or .bucket=="cancel")] | length' 2>/dev/null || echo 0)
  n_pend=$(echo "$checks"   | jq '[.[] | select(.bucket=="pending")] | length' 2>/dev/null || echo 0)
  n_pass=$(echo "$checks"   | jq '[.[] | select(.bucket=="pass" or .bucket=="skipping")] | length' 2>/dev/null || echo 0)

  # ---- unresolved review threads -------------------------------------------
  unresolved=$(gh api graphql -F owner="$OWNER" -F repo="$NAME" -F pr="$PR" -f query='
    query($owner:String!,$repo:String!,$pr:Int!){
      repository(owner:$owner,name:$repo){
        pullRequest(number:$pr){
          reviewThreads(first:100){ nodes { isResolved } }
        }}}' 2>/dev/null \
    | jq '[.data.repository.pullRequest.reviewThreads.nodes[]? | select(.isResolved==false)] | length' 2>/dev/null || true)
  [ -n "${unresolved:-}" ] || unresolved="?"

  log "poll $poll (${elapsed}s): state=$state merge=$merge_state ci=${n_pass}pass/${n_fail}fail/${n_pend}pending of ${n_checks} unresolved_threads=$unresolved"

  # ---- CI failed ------------------------------------------------------------
  if [ "${n_fail:-0}" -gt 0 ]; then
    log "RESULT: CI has ${n_fail} failing/cancelled check(s)"; exit 4
  fi

  # ---- CI still running -----------------------------------------------------
  if [ "${n_pend:-0}" -gt 0 ]; then
    [ "$elapsed" -ge "$TIMEOUT" ] && { log "RESULT: TIMEOUT after ${elapsed}s — CI still pending"; exit 6; }
    sleep "$INTERVAL"; continue
  fi

  # ---- no CI checks at all --------------------------------------------------
  if [ "${n_checks:-0}" -eq 0 ]; then
    if [ "$elapsed" -ge "$GRACE" ]; then
      log "RESULT: no CI checks after ${elapsed}s grace window — CI did not start"; exit 3
    fi
    [ "$elapsed" -ge "$TIMEOUT" ] && { log "RESULT: TIMEOUT"; exit 6; }
    sleep "$INTERVAL"; continue
  fi

  # ---- CI is green here (n_fail=0, n_pend=0, n_checks>0) --------------------
  if [ "$unresolved" = "?" ]; then
    log "poll $poll: CI green but unresolved-thread query failed — will retry"
    [ "$elapsed" -ge "$TIMEOUT" ] && { log "RESULT: TIMEOUT (CI green, thread query unavailable)"; exit 6; }
    sleep "$INTERVAL"; continue
  fi
  if [ "${unresolved:-0}" -gt 0 ]; then
    log "RESULT: CI green, but ${unresolved} unresolved review thread(s) — drain them"; exit 7
  fi

  log "RESULT: GATE GREEN — CI all green (${n_pass}/${n_checks}), 0 unresolved threads"
  exit 0
done
