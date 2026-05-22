---
description: Shepherd one or an ordered sequence of open PRs all the way to merge — drain every review thread, pass CI, run the test plan, then auto-merge on a green gate. Rebases each later PR onto the freshly-merged main. Pair with /loop for unattended sequence-draining.
---

Use the `pr-shepherd:pr-shepherd` skill to shepherd PR(s) to merge.

PR numbers (ordered sequence — merge in exactly this order): $ARGUMENTS

- If PR numbers are given, shepherd them in that order. After each one merges,
  rebase the next PR's branch onto the freshly-merged `main` before draining it,
  so stacked/dependent PRs never collide.
- If no PR numbers are given, shepherd every open PR authored by the current
  user, in ascending PR-number order.

For each PR: drain every review thread (reply inline, then resolve — treat the
gate as a fixpoint and re-poll after every push), run the unchecked test-plan
items, wait out CI on the hardened observe-only `watch-pr.sh` loop, then merge
(`--squash --delete-branch`) once the gate is fully green.

Never merge over a hard stop — a human "Request changes" review, a draft PR, an
unsatisfied branch-protection rule, an unresolvable conflict, or a capped
review ping-pong. Surface those and stop.

When wrapped in `/loop`, run one shepherding pass per tick and reschedule only
while a PR is still mid-flight (waiting on CI).
