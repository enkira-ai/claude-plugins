---
name: harness-verify
description: Use to independently verify a completed feature in a harness-engineered repo. Triggers on "harness verify", "verify feature", "independent verification", "evaluator", "check feature passes". Delegates verification to an external coding CLI (codex or gemini) with a fresh context so the verdict is not biased by the generator's reasoning.
---

# Harness Verify — Independent Evaluator

You are the **evaluator dispatcher**. Your job is to verify a completed feature *without* sharing context with the agent that wrote it. You do this by handing the verification task to a **different coding CLI** (Codex or Gemini), not to yourself.

## Why a Different CLI

When the same agent that implemented a feature also validates it, self-validation bias kicks in: the model "explains why" its work is correct instead of checking whether it is. Anthropic's harness research calls this the single biggest failure mode for long-running coding agents.

The fix is an Evaluator that has **no shared state** with the Generator. Spawning a subagent inside the same Claude session does *not* cut it — it inherits priors, conversation memory, and the same model's blind spots. A separate CLI on a different model family is the strongest available isolation:

| Verifier | Isolation | Notes |
|----------|-----------|-------|
| `codex exec` (OpenAI) | Different vendor, different model | Preferred |
| `gemini -p` (Google) | Different vendor, different model | Equally good |
| Claude subagent via Task tool | Same model, fresh context | Fallback only |

## Protocol

### Step 1: Locate the Feature

```bash
FEATURE_ID="${1:-}"  # passed via $ARGUMENTS
if [ -z "$FEATURE_ID" ]; then
  echo "Usage: harness-verify <feature_id>"
  exit 1
fi

python3 -c "
import json, sys
f = next((x for x in json.load(open('features.json')) if x['id'] == $FEATURE_ID), None)
if not f: sys.exit('Feature not found')
print(json.dumps(f, indent=2))
"
```

### Step 2: Detect the Verifier CLI

Prefer in order: `codex` → `gemini` → Claude subagent fallback.

```bash
if command -v codex >/dev/null 2>&1; then
  VERIFIER="codex"
elif command -v gemini >/dev/null 2>&1; then
  VERIFIER="gemini"
else
  VERIFIER="claude-subagent"
fi
echo "Using verifier: $VERIFIER"
```

### Step 3: Build the Evaluator Prompt

Write the prompt to a temp file. The prompt must contain **only** the feature spec and instructions — do NOT include the diff, your reasoning, or commit messages. The evaluator reads the repo fresh.

```bash
cat > /tmp/harness-verify-prompt.md <<'PROMPT'
You are an independent code verifier. You have never seen this repo before.

Your task: verify that feature #<ID> is correctly and fully implemented in the current working directory.

Feature spec:
<paste feature JSON here — description + verification steps>

Project context:
- Read CLAUDE.md (or AGENTS.md) to learn the test/build commands and conventions
- Do NOT assume the feature works because code exists for it
- Actually run the verification steps listed in the spec
- For UI features: use any available browser automation or run the app
- For API features: make real requests
- For logic features: run the test suite and check the relevant cases pass

Rules:
- Be adversarial. Look for shortcuts, stubs, skipped tests, TODO markers, hard-coded return values.
- Do not trust comments or variable names. Trust only observed behavior.
- If a verification step cannot be executed, mark it UNCLEAR, not PASS.

Output exactly one JSON object on the last line, no prose after it:
{
  "feature_id": <ID>,
  "verdict": "PASS" | "FAIL" | "UNCLEAR",
  "evidence": [
    {"step": "<verification step>", "result": "<what you observed>", "status": "pass|fail|unclear"}
  ],
  "concerns": ["<any red flag you noticed>"],
  "recommendation": "<one sentence>"
}
PROMPT
```

### Step 4: Invoke the Verifier

```bash
case "$VERIFIER" in
  codex)
    # Non-interactive exec mode. --cd pins the working dir.
    # --sandbox workspace-write lets it run tests without full-auto approval.
    codex exec --cd "$(pwd)" --sandbox workspace-write \
      "$(cat /tmp/harness-verify-prompt.md)" \
      > /tmp/harness-verify-output.txt 2>&1
    ;;
  gemini)
    # -p reads prompt, --yolo auto-approves tool calls in the CWD sandbox
    gemini -p "$(cat /tmp/harness-verify-prompt.md)" --yolo \
      > /tmp/harness-verify-output.txt 2>&1
    ;;
  claude-subagent)
    # Last resort: spawn a Claude subagent with clean context via the Task tool.
    # Use the general-purpose subagent_type. Pass the prompt as the task.
    # (You do this by actually invoking Task — this section is a note for you.)
    echo "Falling back to Claude subagent. Invoke Task tool with subagent_type=general-purpose."
    ;;
esac
```

> Flag usage note: both CLIs update their flags. If `--sandbox` or `--yolo` are rejected, read `codex exec --help` / `gemini --help` and adapt. Do not silently drop the sandbox/approval flag.

### Step 5: Parse the Verdict

The verifier's output may include chatter. Extract the final JSON line:

```bash
VERDICT_JSON=$(grep -E '^\{.*"verdict".*\}$' /tmp/harness-verify-output.txt | tail -1)
echo "$VERDICT_JSON" | python3 -m json.tool
```

### Step 6: Act on the Verdict

- **PASS** — update `features.json`: set `"passes": true` for this feature. Commit as `chore: verify feature #<ID> — passed independent verification`.
- **FAIL** — leave `features.json` unchanged. Append the verifier's `concerns` and `evidence` to `progress.txt` under a `BLOCKED` entry. Do **not** retry by feeding the verdict back to the generator blindly — summarize the failure mode first, so the fix addresses the root cause.
- **UNCLEAR** — treat as FAIL for gating purposes. Log the unclear step. Often means the verification spec itself is too vague — consider tightening the feature's `verification` array.

### Step 7: Log the Verification

Append to `progress.txt`:

```text
[YYYY-MM-DD SESSION N] VERIFIED — Feature #<ID>

## Verifier
- Tool: <codex|gemini|claude-subagent>
- Verdict: <PASS|FAIL|UNCLEAR>

## Evidence
- <step>: <result>
- <step>: <result>

## Concerns
- <concern>

---
```

## When to Invoke This Skill

- After `harness-work` completes an implementation, **before** marking the feature as passing.
- When auditing whether features flagged `"passes": true` actually hold up — pass their IDs through the verifier again.
- Before a release: batch-verify the N most recent completed features.

## When NOT to Invoke

- Trivial features (e.g. "README exists") — cost of spawning an external CLI outweighs the signal.
- Features whose verification steps cannot be executed headlessly (require human visual judgement). Mark these with `"human_verify": true` in the feature spec.

## Cost & Rate Limits

External CLIs cost real tokens on someone else's bill. Keep verifier prompts tight. Do not feed them the full repo — they can read what they need. If the verifier hits a rate limit, surface that to the user; do not silently downgrade to self-verification, which defeats the entire purpose.

## Escape Hatch

If neither `codex` nor `gemini` is installed and the user insists on proceeding without them, run verification as a Claude Task subagent with `subagent_type=general-purpose`. Mark the resulting verdict as `"verifier": "same-model-fallback"` in `progress.txt` so future audits know the isolation was weaker.
