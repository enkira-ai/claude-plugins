#!/usr/bin/env bash
# codex-focused-review: create a scoped Codex skill, run the review, clean up.
# Usage: codex-focused-review [--base <branch>] [--commit <sha>] [--title <title>] [--tail <n>] <prompt>
set -euo pipefail

BASE="main"
COMMIT=""
TITLE=""
TAIL_LINES=200
PROMPT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --base)   [[ $# -lt 2 ]] && { echo "Error: --base requires an argument" >&2; exit 1; }; BASE="$2";       shift 2 ;;
        --commit) [[ $# -lt 2 ]] && { echo "Error: --commit requires an argument" >&2; exit 1; }; COMMIT="$2";   shift 2 ;;
        --title)  [[ $# -lt 2 ]] && { echo "Error: --title requires an argument" >&2; exit 1; }; TITLE="$2";     shift 2 ;;
        --tail)   [[ $# -lt 2 ]] && { echo "Error: --tail requires an argument" >&2; exit 1; }; TAIL_LINES="$2"; shift 2 ;;
        --)       shift; PROMPT="$*"; break ;;
        -*)       echo "Unknown option: $1" >&2; exit 1 ;;
        *)        PROMPT="${PROMPT:+$PROMPT }$1"; shift ;;
    esac
done

if [[ ! "$TAIL_LINES" =~ ^[0-9]+$ ]]; then
    echo "Error: --tail requires a positive integer" >&2; exit 1
fi

if [[ -z "$PROMPT" ]]; then
    echo "Usage: codex-focused-review [--base <branch>] [--commit <sha>] [--title <title>] [--tail <n>] <prompt>" >&2
    exit 1
fi

# Unique skill name: sanitised title/ref + PID guards against concurrent runs
REF="${TITLE:-${COMMIT:-$BASE}}"
SAFE_REF=$(printf '%s' "$REF" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | cut -c1-40 | sed 's/-*$//')
SKILL_NAME="review-${SAFE_REF}-$$"
SKILL_DIR="$HOME/.agents/skills/$SKILL_NAME"

# Scope the description so Codex applies this skill only to this review
if [[ -n "$COMMIT" ]]; then
    SCOPE="when reviewing commit ${COMMIT}"
elif [[ -n "$TITLE" ]]; then
    SCOPE="when reviewing '${TITLE}'"
else
    SCOPE="when reviewing branch '${BASE}'"
fi

cleanup() { rm -rf "$SKILL_DIR"; }
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM
trap 'cleanup; exit 129' HUP

mkdir -p "$SKILL_DIR"
cat > "$SKILL_DIR/SKILL.md" << EOF
---
name: ${SKILL_NAME}
description: "Apply only ${SCOPE}. Do not apply to any other review."
---

${PROMPT}
EOF

# Build and run the codex review command
CMD=(codex review --title "${TITLE:-Focused review}")
if [[ -n "$COMMIT" ]]; then
    CMD+=(--commit "$COMMIT")
else
    CMD+=(--base "$BASE")
fi

"${CMD[@]}" 2>&1 | tail -n "$TAIL_LINES"
