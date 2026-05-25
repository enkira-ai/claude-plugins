#!/usr/bin/env bash
# closeout.sh — Phase 3 close-out orchestrator for epic-shepherd.
#
# When the Phase 2 tick sees an empty sequence + no in-flight PR +
# at least one completed sub-issue, it hands off to this script. The
# script verifies the epic is genuinely done, composes a close-out
# report, opens a PR for the report ("Closes #<epic>"), and records
# the PR number into state so subsequent ticks shepherd it like any
# other PR via pr-shepherd:pr-shepherd.
#
# Subcommands:
#
#   start    <epic> [--state PATH] [--repo owner/name] [--dry-run]
#       Verify rollup → compose report → branch + commit + push →
#       open PR → state.sh mark-closeout-in-flight. Prints the
#       closeout PR number to stdout on success.
#
#   finalize <epic> [--state PATH] [--reason completed]
#       Called after the closeout PR merges. Verifies the epic is
#       CLOSED (the squash-merge's `Closes #<epic>` should auto-close
#       it); if not, falls back to `gh issue close`. Records the
#       closeout in state.sh complete-closeout. Prints a one-line
#       summary and exits 0.
#
#   verify   <epic> [--state PATH] [--repo owner/name]
#       Read-only sanity check. Surfaces any inconsistency (open
#       sub-issues, missing closeout_pr while sequence is empty,
#       etc). Exit 0 if consistent, non-zero with a message
#       otherwise. Useful for an operator debugging a stuck loop.
#
# Exit codes:
#   0  success
#   2  precondition failure (e.g. some sub-issue still OPEN at start)
#   3  state mismatch (verify subcommand)
#   4  bad usage / `gh` not available / API failure
#
# All GitHub reads use `gh api graphql` / `gh api`; the only mutation
# is on `start` (branch + commit + push + `gh pr create`) and
# `finalize` (potential fallback `gh issue close`).
set -euo pipefail

PROG="$(basename "$0")"
VERSION="0.3.0"

usage() {
    sed -n '3,$p' "$0" | sed -n 's/^# \?//;1,/^$/p' >&2
    exit "${1:-4}"
}

die() { echo "FATAL: $*" >&2; exit "${2:-4}"; }
have() { command -v "$1" >/dev/null 2>&1; }

# Path to the sibling state.sh so closeout can shell out to it for
# the atomic-write contract.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_SH="$SCRIPT_DIR/state.sh"

[ -x "$STATE_SH" ] || die "missing sibling state.sh at $STATE_SH" 4
have gh || die "gh required" 4
have jq || die "jq required" 4
have git || die "git required" 4

# --- arg parsing -------------------------------------------------------------

[ $# -ge 1 ] || usage
subcmd="$1"; shift

# Help shortcut: `closeout.sh <subcmd> --help` or no-arg --help.
if [ "${subcmd:-}" = "--help" ] || [ "${subcmd:-}" = "-h" ]; then
    usage 0
fi

[ $# -ge 1 ] || { echo "FATAL: <epic> is required" >&2; usage; }
epic="$1"; shift
if [ "$epic" = "--help" ] || [ "$epic" = "-h" ]; then
    usage 0
fi
[[ "$epic" =~ ^[0-9]+$ ]] || die "epic must be a number, got $epic"

state_path="/tmp/epic-shepherd-state-${epic}.json"
repo=""
dry_run=0
reason="completed"

while [ $# -gt 0 ]; do
    case "$1" in
        --state) state_path="$2"; shift 2 ;;
        --repo) repo="$2"; shift 2 ;;
        --dry-run) dry_run=1; shift ;;
        --reason) reason="$2"; shift 2 ;;
        -h|--help) usage 0 ;;
        *) die "unexpected arg: $1" 4 ;;
    esac
done

# --- helpers -----------------------------------------------------------------

utc_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
utc_date() { date -u +%Y-%m-%d; }

read_state() {
    [ -f "$state_path" ] || die "state file missing at $state_path" 2
    cat "$state_path"
}

# Derive the (owner, name) repo from --repo, the state file, or gh
# detection in that priority order. Sets $owner and $name globals.
resolve_repo() {
    local s
    if [ -z "$repo" ] && [ -f "$state_path" ]; then
        s="$(cat "$state_path")"
        repo="$(jq -r '.repo // ""' <<<"$s")"
    fi
    if [ -z "$repo" ]; then
        repo="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)" \
            || die "could not detect repo; pass --repo owner/name" 4
    fi
    [[ "$repo" == */* ]] || die "--repo must be 'owner/name', got '$repo'" 4
    owner="${repo%/*}"
    name="${repo#*/}"
}

# Pull the epic's title + state + sub-issue rollup via GraphQL.
# Echoes JSON: {title, state, subIssues:[{number,state,title},...]}
fetch_epic_rollup() {
    gh api graphql \
        -F owner="$owner" -F name="$name" -F number="$epic" \
        -f query='
            query($owner:String!, $name:String!, $number:Int!) {
                repository(owner:$owner, name:$name) {
                    issue(number:$number) {
                        title state
                        subIssues(first:100) {
                            nodes { number state title }
                        }
                    }
                }
            }' \
        | jq '.data.repository.issue // null'
}

# Get a single PR's title / merge_commit / merged_at as TSV: title<TAB>sha<TAB>merged_at
fetch_pr_meta() {
    local pr="$1"
    gh api "repos/$owner/$name/pulls/$pr" \
        --jq '[.title, (.merge_commit_sha // ""), (.merged_at // "")] | @tsv' \
        2>/dev/null || echo -e "\t\t"
}

# Get the file list for a PR. Echoes newline-separated filenames.
fetch_pr_files() {
    local pr="$1"
    gh api --paginate "repos/$owner/$name/pulls/$pr/files" \
        --jq '.[].filename' 2>/dev/null || true
}

# Truncate a string to N chars with an ellipsis. POSIX-only.
trunc() {
    local s="$1" n="${2:-60}"
    if [ "${#s}" -le "$n" ]; then
        printf '%s' "$s"
    else
        printf '%s…' "${s:0:$((n-1))}"
    fi
}

# Escape a literal for safe insertion into a Markdown table cell:
# strip newlines, replace "|" with "\|".
md_cell() {
    printf '%s' "$1" | tr '\n' ' ' | sed 's/|/\\|/g'
}

# --- compose report ----------------------------------------------------------

# Writes the report Markdown to stdout. Reads enriched completed
# entries from $1 (a JSON array of {issue, pr, title, merge_commit_sha,
# merged_at, files[]}).
compose_report() {
    local enriched="$1"
    local epic_title repo_url completed_count pr_count
    local s; s="$(read_state)"
    epic_title="$(jq -r '.epic_title // ""' <<<"$s")"
    repo_url="https://github.com/$owner/$name"
    completed_count="$(jq 'length' <<<"$enriched")"
    pr_count="$(jq '[.[] | select(.pr != null)] | length' <<<"$enriched")"

    # Header
    cat <<EOF
# Epic #${epic} close-out — ${epic_title}

**Closed:** $(utc_date) UTC
**Total sub-issues completed:** ${completed_count}
**Total PRs merged:** ${pr_count}
**Generated by:** epic-shepherd v${VERSION}

## Summary

This is the close-out for [Epic #${epic}](${repo_url}/issues/${epic}). All
sub-issues are resolved; the merged PRs are listed below in completion
order.

## Merged PRs

| # | Sub-issue | PR | Title | Merged | Files touched |
|---|-----------|-------|-------|--------|---------------|
EOF

    # Table rows
    local idx=0
    while IFS= read -r row; do
        idx=$((idx + 1))
        local issue pr title merged_at files_json
        issue="$(jq -r '.issue' <<<"$row")"
        pr="$(jq -r '.pr // ""' <<<"$row")"
        title="$(jq -r '.title // ""' <<<"$row")"
        merged_at="$(jq -r '.merged_at // ""' <<<"$row")"
        files_json="$(jq -c '.files // []' <<<"$row")"

        # Truncate merged_at to YYYY-MM-DD
        local merged_short="${merged_at:0:10}"

        local pr_cell="—"
        if [ -n "$pr" ]; then
            pr_cell="[#${pr}](${repo_url}/pull/${pr})"
        fi

        local title_cell
        title_cell="$(md_cell "$(trunc "$title" 60)")"

        # Files: top 5 + "+N more" if longer
        local files_cell="—"
        local files_count
        files_count="$(jq 'length' <<<"$files_json")"
        if [ "$files_count" -gt 0 ]; then
            local top
            top="$(jq -r '.[0:5] | map("`" + . + "`") | join(", ")' <<<"$files_json")"
            if [ "$files_count" -gt 5 ]; then
                local more=$((files_count - 5))
                files_cell="${top} (+${more} more)"
            else
                files_cell="${top}"
            fi
            files_cell="$(md_cell "$files_cell")"
        fi

        printf '| %d | #%s | %s | %s | %s | %s |\n' \
            "$idx" "$issue" "$pr_cell" "$title_cell" "$merged_short" "$files_cell"
    done < <(jq -c '.[]' <<<"$enriched")

    # What landed bullet list
    cat <<EOF

## What landed

EOF
    while IFS= read -r row; do
        local pr title
        pr="$(jq -r '.pr // ""' <<<"$row")"
        title="$(jq -r '.title // ""' <<<"$row")"
        if [ -n "$pr" ]; then
            printf -- '- #%s: %s\n' "$pr" "$title"
        fi
    done < <(jq -c '.[]' <<<"$enriched")

    cat <<EOF

## Closing

Merging this report PR squash-closes Epic #${epic} (\`Closes #${epic}\` below).

Closes #${epic}
EOF
}

# Enrich the state's completed array with PR metadata + files.
# Echoes a JSON array.
enrich_completed() {
    local s; s="$(read_state)"
    local raw
    raw="$(jq -c '.completed // []' <<<"$s")"

    # Build the enriched array element-by-element so we can call gh per PR.
    local enriched="[]"
    local count
    count="$(jq 'length' <<<"$raw")"
    local i=0
    while [ "$i" -lt "$count" ]; do
        local entry pr issue
        entry="$(jq -c ".[$i]" <<<"$raw")"
        pr="$(jq -r '.pr // ""' <<<"$entry")"
        issue="$(jq -r '.issue // ""' <<<"$entry")"
        local title="" merged_at="" sha="" files_json="[]"
        if [ -n "$pr" ] && [ "$pr" != "null" ]; then
            local meta
            meta="$(fetch_pr_meta "$pr")"
            title="$(printf '%s' "$meta" | awk -F'\t' '{print $1}')"
            sha="$(printf '%s' "$meta" | awk -F'\t' '{print $2}')"
            merged_at="$(printf '%s' "$meta" | awk -F'\t' '{print $3}')"
            local files
            files="$(fetch_pr_files "$pr")"
            files_json="$(printf '%s' "$files" | jq -R -s 'split("\n") | map(select(length > 0))')"
        fi
        # Fall back to state-recorded title if PR fetch failed.
        if [ -z "$title" ]; then
            title="$(jq -r '.title // ""' <<<"$entry")"
        fi
        if [ -z "$merged_at" ]; then
            merged_at="$(jq -r '.merged_at // ""' <<<"$entry")"
        fi
        enriched="$(jq -c \
            --argjson el "$entry" \
            --arg title "$title" \
            --arg sha "$sha" \
            --arg merged_at "$merged_at" \
            --argjson files "$files_json" \
            '. + [$el + {title: $title, merge_commit_sha: $sha, merged_at: $merged_at, files: $files}]' \
            <<<"$enriched")"
        i=$((i + 1))
    done
    printf '%s' "$enriched"
}

# --- subcommands -------------------------------------------------------------

cmd_start() {
    resolve_repo

    echo "  closeout: starting for epic #$epic in $owner/$name (dry-run=$dry_run)" >&2

    # 1. Verify rollup. Skipped under --dry-run so an operator can
    # preview the report markdown against a synthetic state file
    # without hitting the GitHub API or risking accidental mutation.
    if [ "$dry_run" != "1" ]; then
        local rollup
        rollup="$(fetch_epic_rollup)"
        if [ "$rollup" = "null" ] || [ -z "$rollup" ]; then
            die "epic #$epic not found in $owner/$name" 2
        fi
        local epic_state
        epic_state="$(jq -r '.state' <<<"$rollup")"
        if [ "$epic_state" != "OPEN" ]; then
            die "epic #$epic is already $epic_state — nothing to close out" 2
        fi
        local still_open
        still_open="$(jq -r '[.subIssues.nodes[] | select(.state == "OPEN") | .number] | join(", ")' <<<"$rollup")"
        if [ -n "$still_open" ]; then
            die "epic #$epic still has OPEN sub-issues: $still_open — refusing to close out" 2
        fi
    else
        echo "  [dry-run] skipping GitHub rollup verification" >&2
    fi

    # 2. Load + enrich completed. Under --dry-run, skip PR-meta fetches
    # too (they would hit GitHub) — render the report from whatever
    # title/pr fields the state file already carries.
    local enriched
    if [ "$dry_run" = "1" ]; then
        enriched="$(jq -c '.completed // [] | map(. + {title: (.title // ""), files: []})' <<<"$(read_state)")"
    else
        enriched="$(enrich_completed)"
    fi
    local report
    report="$(compose_report "$enriched")"

    # 3. Write the report.
    local report_dir="docs/reports"
    local report_file="${report_dir}/$(utc_date)-epic-${epic}-closeout.md"
    if [ "$dry_run" = "1" ]; then
        echo "  [dry-run] would write report to: $report_file" >&2
        echo "  [dry-run] --- report content ---" >&2
        echo "$report" >&2
        echo "  [dry-run] --- end report ---" >&2
        echo "  [dry-run] would create branch docs/epic-${epic}-closeout, commit, push, open PR" >&2
        exit 0
    fi

    # 4. Branch + commit + push + PR.
    local branch="docs/epic-${epic}-closeout"
    if git rev-parse --verify "refs/heads/$branch" >/dev/null 2>&1; then
        die "branch $branch already exists locally — delete it or finish the existing closeout" 4
    fi
    if git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
        die "branch $branch already exists on origin — finish or delete the upstream first" 4
    fi

    mkdir -p "$report_dir"
    printf '%s\n' "$report" > "$report_file"

    git checkout -b "$branch" || die "git checkout -b $branch failed" 4
    git add "$report_file" || die "git add $report_file failed" 4
    local epic_title
    epic_title="$(jq -r '.epic_title // ""' <<<"$(read_state)")"
    local commit_msg="docs(epic-${epic}): close-out report — ${epic_title}"
    git commit -m "$commit_msg" || die "git commit failed" 4
    git push -u origin "$branch" \
        || die "git push -u origin $branch failed; branch may exist upstream or you lack push" 4

    # 5. Compose PR body (checklist of merged PRs + Closes #<epic>).
    local pr_body_file
    pr_body_file="$(mktemp)"
    {
        echo "Close-out for Epic #${epic}."
        echo
        echo "## Merged sub-issues"
        echo
        jq -r '.[] | "- [x] #\(.issue)" + (if .pr then " (PR #\(.pr))" else "" end)' <<<"$enriched"
        echo
        echo "Report: \`${report_file}\`"
        echo
        echo "Merging this PR squash-closes the epic."
        echo
        echo "Closes #${epic}"
    } > "$pr_body_file"

    local pr_url
    pr_url="$(gh pr create \
        --title "docs(epic-${epic}): close-out report" \
        --body-file "$pr_body_file" \
        --base main \
        --head "$branch")" \
        || { rm -f "$pr_body_file"; die "gh pr create failed" 4; }
    rm -f "$pr_body_file"

    local pr_num
    pr_num="$(printf '%s' "$pr_url" | grep -oE '[0-9]+$')"
    [[ "$pr_num" =~ ^[0-9]+$ ]] || die "could not parse PR number from URL: $pr_url" 4

    # 6. Record into state.
    "$STATE_SH" mark-closeout-in-flight "$epic" "$pr_num" "$branch" --state "$state_path" \
        || die "state.sh mark-closeout-in-flight failed" 4

    echo "  closeout: opened PR #$pr_num ($pr_url)" >&2
    echo "$pr_num"
}

cmd_finalize() {
    resolve_repo

    local s; s="$(read_state)"
    local closeout_pr
    closeout_pr="$(jq -r '.closeout_pr // ""' <<<"$s")"
    if [ -z "$closeout_pr" ] || [ "$closeout_pr" = "null" ]; then
        die "no closeout_pr in state — was 'closeout.sh start' run?" 2
    fi

    # Verify the epic is now CLOSED.
    local rollup epic_state
    rollup="$(fetch_epic_rollup)"
    epic_state="$(jq -r '.state' <<<"$rollup")"
    if [ "$epic_state" != "CLOSED" ]; then
        echo "  closeout: epic #$epic still OPEN after closeout PR merged — falling back to gh issue close" >&2
        gh issue close "$epic" --repo "$owner/$name" --reason "$reason" \
            || die "gh issue close failed" 4
    fi

    "$STATE_SH" complete-closeout "$epic" "$closeout_pr" --state "$state_path" \
        || die "state.sh complete-closeout failed" 4

    local completed_n pr_n
    completed_n="$(jq '.completed | length' <<<"$s")"
    pr_n="$(jq '[.completed[] | select(.pr != null)] | length' <<<"$s")"
    echo "Epic #${epic} closed — ${completed_n} completed sub-issues (${pr_n} PRs merged), closeout PR #${closeout_pr}"
}

cmd_verify() {
    resolve_repo
    local s; s="$(read_state)"
    local closeout_pr closeout_branch sequence_len in_flight
    closeout_pr="$(jq -r '.closeout_pr // "null"' <<<"$s")"
    closeout_branch="$(jq -r '.closeout_branch // "null"' <<<"$s")"
    sequence_len="$(jq '.sequence | length' <<<"$s")"
    in_flight="$(jq -r '.in_flight_pr // "null"' <<<"$s")"

    echo "=== closeout.sh verify epic #$epic ===" >&2
    echo "state file: $state_path" >&2
    echo "  sequence_len:    $sequence_len" >&2
    echo "  in_flight_pr:    $in_flight" >&2
    echo "  closeout_pr:     $closeout_pr" >&2
    echo "  closeout_branch: $closeout_branch" >&2

    local rollup epic_state
    rollup="$(fetch_epic_rollup)"
    epic_state="$(jq -r '.state' <<<"$rollup")"
    echo "  epic state on GH:    $epic_state" >&2
    local open_subs
    open_subs="$(jq -r '[.subIssues.nodes[] | select(.state == "OPEN") | .number] | join(", ")' <<<"$rollup")"
    if [ -n "$open_subs" ]; then
        echo "  open sub-issues:     $open_subs" >&2
    else
        echo "  open sub-issues:     (none)" >&2
    fi

    local inconsistencies=0
    if [ "$closeout_pr" = "null" ] && [ "$sequence_len" -eq 0 ] && [ "$in_flight" = "null" ] && [ "$epic_state" = "OPEN" ] && [ -z "$open_subs" ]; then
        echo "INCONSISTENT: sequence empty + no in-flight + no closeout_pr but epic still OPEN; run 'closeout.sh start' to begin Phase 3" >&2
        inconsistencies=$((inconsistencies + 1))
    fi
    if [ "$closeout_pr" != "null" ] && [ -n "$open_subs" ]; then
        echo "INCONSISTENT: closeout PR opened (#$closeout_pr) but sub-issues are still OPEN ($open_subs); a sub-issue was likely reopened mid-closeout" >&2
        inconsistencies=$((inconsistencies + 1))
    fi
    if [ "$closeout_pr" != "null" ] && [ "$closeout_branch" = "null" ]; then
        echo "INCONSISTENT: closeout_pr set but closeout_branch is null (paired fields drifted)" >&2
        inconsistencies=$((inconsistencies + 1))
    fi

    if [ "$inconsistencies" -gt 0 ]; then
        exit 3
    fi
    echo "OK: closeout state consistent" >&2
}

case "$subcmd" in
    start)    cmd_start    ;;
    finalize) cmd_finalize ;;
    verify)   cmd_verify   ;;
    *)        usage        ;;
esac
