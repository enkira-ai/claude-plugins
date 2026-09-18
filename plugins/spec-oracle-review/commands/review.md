---
allowed-tools: ["Bash", "Read", "Grep", "Glob", "Write", "Edit", "Skill"]
description: Blind spec-derived test plan for a PR, then plan-vs-implementation diff with probes and mutations
---

Run a spec-oracle review of `$ARGUMENTS` (a PR number or URL; optionally followed by spec paths
to read).

Load the `spec-oracle-review` skill and follow it phase by phase. The two things the command
exists to enforce:

1. **Phase 1 is posted before any implementation is read.** Take from the PR only its owning
   issue and base commit — `gh pr view <N> --json baseRefOid,closingIssuesReferences`, nothing
   more; not the body, not the branch, not the head. Open a worktree at the base commit and write
   the plan from there, without opening the PR again until the plan comment is on it. If the
   current session authored any of the code, stop and say the oracle needs a fresh session. If
   the PR is a small bug fix or an ADR/spec document, say this review is not for it and stop.
2. **Phases 2–4 are empirical.** Read the diff at the pinned head, then open a throwaway
   worktree at that head, run the probes and the mutations there, remove the worktree, and post
   the triage comment with traces attached.

If `$ARGUMENTS` is empty, ask for the PR. If the PR has no spec, ADR, or acceptance criteria to
derive from, say so and stop — the finding is "write the spec".
