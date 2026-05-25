#!/usr/bin/env bash
# state.sh — atomic state-machine helper for epic-shepherd Phase 2.
#
# Reads/writes /tmp/epic-shepherd-state-<epic>.json (or --state <path>),
# enforces the schema, and tells the caller (the LLM agent) what to do next.
#
# Subcommands:
#   status   <epic> [--state PATH]                       — one of:
#       PAUSED <reason>
#       SHEPHERD <pr> <issue>
#       DISPATCH <issue> <implementer> <tier>
#       CLOSEOUT
#       IDLE
#       MISSING        (state file does not exist — run :extract first)
#
#   mark-in-flight <epic> <issue> <pr> [--state PATH]   — set in_flight_*
#
#   complete <epic> <issue> <pr> [--state PATH]         — move issue to
#       completed (with merged_at), clear in_flight, refresh sequence by
#       removing the just-completed issue's downstream blocker references.
#       Does NOT re-run extract-sequence; that is the caller's job (so the
#       caller can decide when to spend the API quota).
#
#   pause <epic> <reason> [--state PATH]                — set paused
#       {reason, at}; subsequent ticks will exit early on status=PAUSED.
#
#   resume <epic> [--state PATH]                        — clear paused.
#       Operator action: after fixing whatever caused the pause.
#
#   show <epic> [--state PATH]                          — pretty-print
#       current state to stderr (status + sequence head + counts).
#
# Exit codes are 0 on success; 2 on missing state; 3 on schema violation;
# 4 on bad usage. The 'status' subcommand always exits 0 and prints the
# status string to stdout so callers can capture it cleanly.
#
# Atomic-write contract: every mutation writes to <state>.tmp.$$ then
# rename()s onto <state>. flock around the read-modify-write cycle so two
# concurrent ticks can't both pop the same item.
set -euo pipefail

PROG="$(basename "$0")"

usage() {
    sed -n '3,$p' "$0" | sed -n 's/^# \?//;1,/^$/p' >&2
    exit 4
}

die() { echo "FATAL: $*" >&2; exit "${2:-4}"; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- arg parsing -------------------------------------------------------------

[ $# -ge 2 ] || usage
subcmd="$1"; shift
epic="$1"; shift
[[ "$epic" =~ ^[0-9]+$ ]] || die "epic must be a number, got $epic"

state_path="/tmp/epic-shepherd-state-${epic}.json"
extra_args=()
while [ $# -gt 0 ]; do
    case "$1" in
        --state) state_path="$2"; shift 2 ;;
        *) extra_args+=("$1"); shift ;;
    esac
done

have jq || die "jq required (apt install jq / brew install jq)" 4

# --- helpers -----------------------------------------------------------------

read_state() {
    [ -f "$state_path" ] || return 1
    cat "$state_path"
}

# Atomic write: write to .tmp.<pid> then rename. Caller passes the new JSON
# on stdin. Uses flock so concurrent ticks don't race.
write_state() {
    local tmp="${state_path}.tmp.$$"
    local lock="${state_path}.lock"
    {
        flock -w 30 9 || die "could not acquire write lock on $state_path" 4
        cat > "$tmp"
        # Validate it parses before swapping.
        jq -e '.schema_version == 1' "$tmp" >/dev/null \
            || { rm -f "$tmp"; die "schema validation failed (schema_version must be 1)" 3; }
        mv "$tmp" "$state_path"
    } 9>"$lock"
}

utc_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# --- subcommands -------------------------------------------------------------

cmd_status() {
    local s
    s="$(read_state)" || { echo "MISSING"; return 0; }

    # PAUSED takes precedence over everything.
    if jq -e '.paused != null' <<<"$s" >/dev/null; then
        local reason
        reason="$(jq -r '.paused.reason' <<<"$s")"
        echo "PAUSED $reason"
        return 0
    fi

    # If a PR is in flight, shepherd it.
    if jq -e '.in_flight_pr != null' <<<"$s" >/dev/null; then
        local pr issue
        pr="$(jq -r '.in_flight_pr' <<<"$s")"
        issue="$(jq -r '.in_flight_issue' <<<"$s")"
        echo "SHEPHERD $pr $issue"
        return 0
    fi

    # If sequence has work, dispatch the tier-1 head. Multiple tier-1
    # items? Caller picks the first (sequence is already deterministically
    # sorted in extract-sequence.py: tier asc, issue asc within tier).
    if jq -e '.sequence | length > 0' <<<"$s" >/dev/null; then
        local head implementer tier default_implementer
        head="$(jq -r '.sequence[0]' <<<"$s")"
        default_implementer="$(jq -r '.default_implementer' <<<"$s")"
        implementer="$(jq -r --arg d "$default_implementer" \
            '.implementer // $d' <<<"$head")"
        local issue
        issue="$(jq -r '.issue' <<<"$head")"
        tier="$(jq -r '.tier' <<<"$head")"
        echo "DISPATCH $issue $implementer $tier"
        return 0
    fi

    # Sequence empty + no in-flight = ready for closeout (Phase 3).
    if jq -e '.completed | length > 0' <<<"$s" >/dev/null; then
        echo "CLOSEOUT"
        return 0
    fi

    echo "IDLE"
}

cmd_mark_in_flight() {
    local issue="${extra_args[0]:-}"
    local pr="${extra_args[1]:-}"
    [[ "$issue" =~ ^[0-9]+$ && "$pr" =~ ^[0-9]+$ ]] \
        || die "mark-in-flight needs <issue> <pr>" 4
    local s; s="$(read_state)" || die "state file missing — run :extract first" 2
    if jq -e '.in_flight_pr != null' <<<"$s" >/dev/null; then
        local existing_pr existing_issue
        existing_pr="$(jq -r '.in_flight_pr' <<<"$s")"
        existing_issue="$(jq -r '.in_flight_issue' <<<"$s")"
        die "already in-flight: PR #$existing_pr (issue #$existing_issue). \
Clear it via 'complete' or 'pause' first." 3
    fi
    jq --argjson pr "$pr" --argjson issue "$issue" \
        '.in_flight_pr = $pr | .in_flight_issue = $issue' <<<"$s" \
        | write_state
    echo "marked in-flight: PR #$pr for issue #$issue" >&2
}

cmd_complete() {
    local issue="${extra_args[0]:-}"
    local pr="${extra_args[1]:-}"
    [[ "$issue" =~ ^[0-9]+$ && "$pr" =~ ^[0-9]+$ ]] \
        || die "complete needs <issue> <pr>" 4
    local s; s="$(read_state)" || die "state file missing" 2

    # Sanity: the issue we are completing should be the one currently
    # in_flight_issue (or at least be in the sequence). Don't be silently
    # forgiving — the caller might be acting on stale state.
    local in_flight_issue
    in_flight_issue="$(jq -r '.in_flight_issue // "null"' <<<"$s")"
    if [ "$in_flight_issue" != "$issue" ] && [ "$in_flight_issue" != "null" ]; then
        die "issue mismatch: in_flight_issue=$in_flight_issue, you said $issue. \
The state may be stale — re-run :extract." 3
    fi

    local merged_at; merged_at="$(utc_now)"
    jq --argjson issue "$issue" --argjson pr "$pr" --arg at "$merged_at" '
        # remove the issue from sequence and from any downstream
        # blocked_by_in_epic / parallel_with references.
        .sequence = (
            .sequence
            | map(select(.issue != $issue))
            | map(
                if (.blocked_by_in_epic // []) | index($issue) then
                    .blocked_by_in_epic |= map(select(. != $issue))
                    | (if (.blocked_by_in_epic | length) == 0
                       then del(.blocked_by_in_epic) else . end)
                else . end
              )
            | map(
                if (.parallel_with // []) | index($issue) then
                    .parallel_with |= map(select(. != $issue))
                    | (if (.parallel_with | length) == 0
                       then del(.parallel_with) else . end)
                else . end
              )
        )
        | .completed += [{issue: $issue, pr: $pr, merged_at: $at}]
        | .in_flight_pr = null
        | .in_flight_issue = null
    ' <<<"$s" | write_state
    echo "marked completed: issue #$issue closed by PR #$pr" >&2
}

cmd_pause() {
    local reason="${extra_args[*]:-}"
    [ -n "$reason" ] || die "pause needs <reason>" 4
    local s; s="$(read_state)" || die "state file missing" 2
    jq --arg r "$reason" --arg at "$(utc_now)" \
        '.paused = {reason: $r, at: $at}' <<<"$s" | write_state
    echo "PAUSED: $reason" >&2
}

cmd_resume() {
    local s; s="$(read_state)" || die "state file missing" 2
    jq '.paused = null' <<<"$s" | write_state
    echo "resumed" >&2
}

cmd_show() {
    local s; s="$(read_state)" || die "state file missing" 2
    echo "=== epic-shepherd state ($state_path) ===" >&2
    jq -r '
        "epic: #\(.epic)  repo: \(.repo)",
        "generated_at: \(.generated_at)",
        "paused: \(.paused // "no")",
        "in_flight_pr: \(.in_flight_pr // "(none)")",
        "in_flight_issue: \(.in_flight_issue // "(none)")",
        "sequence (\(.sequence | length)):",
        (.sequence[:5] | .[] | "  tier \(.tier)  #\(.issue)  \(.title // "")"),
        (if (.sequence | length) > 5 then "  ... and \((.sequence | length) - 5) more" else empty end),
        "completed: \(.completed | length)"
    ' <<<"$s" >&2
    cmd_status
}

case "$subcmd" in
    status)         cmd_status         ;;
    mark-in-flight) cmd_mark_in_flight ;;
    complete)       cmd_complete       ;;
    pause)          cmd_pause          ;;
    resume)         cmd_resume         ;;
    show)           cmd_show           ;;
    *) usage ;;
esac
