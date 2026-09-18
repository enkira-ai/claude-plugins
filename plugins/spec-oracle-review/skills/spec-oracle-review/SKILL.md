---
name: spec-oracle-review
description: "Use when the implementation PR for a feature or material behaviour change is open and there is a SPEC, ADR, or issue acceptance criteria to derive from: write a spec-derived test plan BEFORE reading the implementation, then diff that plan against the code and tests to separate spec ambiguity, implementation defects, harness gaps, and unreachable requirements. Do NOT use for a small bug fix (a diff-anchored cross-agent round is enough), for an ADR / spec / architecture document PR (there is no implementation to diff against), or at spec-merge time before the implementation exists (specs move; plan against the spec as it stands when the PR opens). Triggers on: spec oracle review, blind test plan, pre-read baseline, review against the spec before reading the code, plan vs implementation, does the implementation match the spec, is the spec ambiguous, which reading did the PR take. Runs first, then the cross-agent rounds."
---

# Spec-Oracle Review

## What it is

The reviewer writes an independent reading of the spec as a test plan — an *oracle* — before
seeing one line of the implementation, posts it, and only then reads the code and its tests. The
product is the **diff between oracle and implementation**, triaged into four bins:

| Bin | Meaning | Who acts |
| --- | --- | --- |
| (a) spec | the spec admits two readings and the wrong one leaks a bad result; it owes a sentence | owner rules, spec amended in the same PR |
| (b) defect | the implementation is wrong under every defensible reading | author fixes |
| (c) harness | the behaviour is right but no test pins it; a mutation survives | author adds the test |
| (d) unreachable | the plan (or spec) names a case the codebase makes impossible by construction | spec row deleted or marked |

A diff-anchored review asks *is this code wrong given what it is trying to do*. This review asks
*is what it is trying to do the one thing the spec says, and does the spec say one thing*. The two
are complementary and the order matters — see [Where it sits](#where-it-sits).

## The one-way door: independence

You cannot un-read a diff. Everything below depends on Phase 1 being posted before the reviewer
has seen the implementation, and on the reviewer not being the author.

**Before the plan is posted, do not open the PR in any form.** The PR number is all the planner
needs — to post the comment. Its branch name, head commit, body, files, and threads are each
information about the implementation, and a list of the ways to see the diff is a how-to. A
driver hands the planner the owning issue and the base commit; without one, take only the issue
number from the PR title and nothing else.

**Isolation is structural, not a tool allowlist.** Run Phase 1 in a worktree checked out at the
PR's **base** commit, so the implementation is not on disk, and name in the prompt the PR number
and the worktree paths that are off limits. Do not restrict the planner's tools beyond that: each
issue needs a different number of specs, ADRs, and base-branch contracts read, and a planner
starved of context writes a plan with no value. Given the base tree, the issue, this skill, and
the no-read list, trust it.

**Do read**: the owning issue and its acceptance criteria; the SPEC(s); every ADR the spec cites;
architecture documents; and the *base branch's* code that the PR builds on — its contracts,
protocols, types, and existing tests. Reading the base is the codebase-consistency half of the
check, not contamination.

**If you wrote any of the code, you cannot be the oracle.** Use a fresh session with no author
context. Vendor difference is a separate axis: the oracle's independence comes from not reading
the implementation, but if the repository requires a different vendor from the author, honour
that too.

**Declare contamination honestly.** If you saw test file names in an ADR, or a spec section that
was written alongside the implementation, say so in the plan header. A plan that hides what it
knew is worthless as evidence.

## Phase 0 — Anchor

1. Identify the owning issue, the spec set, and pin SHAs: *spec as on `<base>` at `<sha>`*,
   *PR head `<sha>`*. The plan is against those and nothing else; a moved head retires the
   comparison, not the plan.
2. Confirm the change is the kind this review is for. **Yes**: an implementation PR for a feature
   or material behaviour change with a spec, ADR, or acceptance criteria behind it. **No**: a small
   bug fix (a diff-anchored cross-agent round is enough); an ADR, spec, or architecture document PR
   (nothing to diff a plan against); a typo, version bump, or straight revert. Skip when there is no
   spec at all — then the only finding is "write the spec". Say so on the PR if you skip.

## Phase 1 — Blind oracle (post before reading code)

Use `templates/plan-comment.md`. The comment has five parts; each one exists to make the later
diff checkable rather than impressionistic.

**Header.** What was read, that the PR was not opened, the base/spec commit, and any
contamination. Not the head commit: the plan does not know it, and the diff comment pins it.

**A. Fork table.** Every place the spec allowed you two readings. Columns:
`# | Fork | Reading I test | Other reading | Bad result if the other branch wins`.
A fork earns a row only if the two readings produce *different observable outcomes* — that is the
nocuous/innocuous test. State the bad result concretely: which AC breaks, who is harmed, what the
operator or caller sees. Rows whose "bad result" column says *neither branch is unsafe* are still
worth listing (the spec should still pick one) but must not later be reported as blockers.
Number the forks; the second comment refers to them by number.

**B. Test matrix.** Grouped by spec section. Each row is one assertion plus the layer it must run
at (unit with fakes / real database / migration round-trip / integration). Every acceptance
criterion gets at least one row. **An AC from which you cannot derive a test is itself a finding**:
put it in the plan as a spec defect, do not quietly skip it. Truth tables are better than prose
where the spec crosses two axes (mode × state, arrival time × method).

**C. What I would not accept as evidence.** Name the cheap substitutes in advance: an in-memory
fake for a concurrency AC, a log-line assertion for a privacy AC, a grep for a behavioural
property, a "N passed" without saying which tier ran.

**D. Predicted thin spots.** Ranked, pre-registered: *"these are the places I expect the
implementation and I to diverge, stated now so I cannot claim afterwards that I knew."* Three to
six items. This is what makes the second comment honest — you will report how many came true.

**E. Mutation checks.** Single-line mutations you will apply to the PR's suite, named before you
have seen the suite: drop a gate check, swap an ordering, ignore a returned flag, add a timeout the
spec forbids, let a second winner through. Each should turn a test red.

Post it. **Never edit the plan after posting.** Corrections go in the second comment under
"where I was wrong".

## Phase 2 — Read and diff

Read every changed file at the pinned head, then every new or changed test. Produce:

**Tally.** Plan rows → *pinned by a test* / *fork took the other branch* / *no test* / *behaviour
the spec did not ask for*. A single line of counts; it is the summary a human reads first.

**Fork outcomes.** `# | Fork | Branch the PR took | Verdict` where the verdict is one of
*SPEC must pin*, *defect*, *fine*, *fine but pin it*. Cite the function or line that shows which
branch was taken. New forks discovered while reading get the next numbers.

**Where I was wrong and the code was right.** Mandatory section, first in the comment when it is
non-empty. Plan rows that described the wrong obligation, tested an unreachable case, or read a
capability as a requirement. These are the plan's inherited spec defects and are as valuable as
anything found in the code. A checklist that records only its own hits is not an honest one.

## Phase 3 — Empirical checks

Everything here runs in a **throwaway worktree at the pinned head** (`git worktree add`), never in
the author's checkout; remove it when done. Do not report a defect you have not reproduced unless
it is explicitly marked *by reading*.

**Probes.** One executable test per fork and per contested plan row, encoding the plan's reading,
run against the *unmodified* head. Report pass/fail per probe. Classify each failure: *spec fork*
(the PR's branch is defensible under the text) or *defect regardless of reading*. Include the
trace — the returned state, the emitted event, the row — not a paraphrase.

**Mutations.** Apply the Phase 1 list plus whatever the reading suggested, one line each, and run
the PR's suite. Report survived/caught per mutation with the plan ID it should have tripped.
Include two or three **controls** — mutations you expect the suite to catch — so a clean survival
rate is evidence about the suite and not about a broken runner. A survived mutation is a bin (c)
item with a test name attached.

**Unreachable.** Plan rows that cannot happen by construction (a `ge=1` field, a closed enum, a
schema that forbids the key) go to bin (d) with the constraint that makes them impossible. Code
paths that no requirement drives go there too — that is the dead-code half of the same category.

Also check what the PR *claims*: "N passed" when the integration tier was skipped, "migration
executed" when only SQL was rendered, "simultaneous-winner tests pass" when no test delivers two
winners. Overstated evidence is a finding.

## Phase 4 — Triage and post

Use `templates/diff-comment.md`. Order: forks → defects ranked → harness gaps by plan ID →
unreachable → documentation drift → suggested fix order → verdict.

For each bin (a) item: name the spec section, **propose the sentence**, recommend one branch and
say why, and name who rules. For bin (b): rank, mark blocking, attach the probe. For bin (c): the
test to add and the plan ID. For bin (d): what to delete or mark.

The verdict says *mergeable / not mergeable as is*, lists what needs an owner ruling, and offers
to turn the probes into real tests on the branch so nobody re-derives them.

## Phase 5 — Handoff to the diff-anchored review

1. Owner rules on every bin (a) fork. The ruling lands **in the spec**, in the same PR — not in a
   code comment, not only in the PR thread.
2. Author fixes bin (b), adds bin (c), cleans bin (d).
3. **Then** the repository's cross-agent or diff-anchored review rounds run on the post-ruling
   head. Pass the fork rulings to that reviewer as its focus / "already settled" list so it does
   not re-litigate a human decision it cannot see the history of.
4. If those rounds move the head materially, re-run the **mutation subset only**; the oracle does
   not need rewriting for a head that changed for code reasons.

## Where it sits

**When:** as the **first** review on the implementation PR, against the spec as it stands when
the PR opens — not at spec-merge time. Specs change between merge and implementation, and a plan
against a superseded spec is noise; the base worktree gives Phase 1 everything it needs without
the implementation. Run it before any diff-anchored review posts, for three reasons:

- Independence is a one-way door. Once a diff-anchored reviewer has posted, the next reader is
  anchored on those findings; the blind plan can no longer be written.
- Spec forks move the head more than code findings do. A ruling on a fork can invalidate a whole
  module; diff-anchored rounds run before the rulings are spent on a head that will change for
  reasons the reviewer could not see, and most repositories cap those rounds.
- The fork table is exactly the "already settled" input the diff-anchored reviewer needs. Without
  it, that reviewer re-raises owner decisions every round.

The diff-anchored review then does what it is better at: mechanical defects, races, resource
handling, and error paths on a design that is no longer moving.

## Anti-patterns

- Editing the plan after reading the code, or writing it with the diff open "just to get the
  file names".
- Reading the PR's review threads first. Other reviewers' findings are contamination until Phase 4.
- The author writing their own oracle. The plan and the code then share one reading.
- Reporting innocuous forks as blockers. The "bad result" column exists to stop this.
- Reporting from reading alone when a probe would take ten minutes.
- Only recording the plan's hits. The "where I was wrong" section is mandatory.
- Letting the PR resolve a fork silently in code. The sentence goes in the spec.
- Running it on a change with no spec. Then the finding is "write the spec"; say that and stop.
- Running it on an ADR or spec PR, or on a small bug fix. The first has no implementation to diff;
  the second is what the cross-agent round is for.
- Restricting the planner's tools to enforce blindness. Put it in a base worktree instead.

## Lineage

Nothing here is new; the combination and its cost are. Independent verification from requirements
without contact with the implementation is IV&V (IEEE 1012). Triaging a coverage gap into *test
shortfall / requirement inadequacy / dead code* is DO-178C §6.4.4. Deriving tests from a
requirement to find defects in the requirement is Perspective-Based Reading (Basili, Shull et al.).
Two independent readings of one spec as an ambiguity detector is N-version programming and
differential testing (Knight & Leveson; McKeeman). Only pinning forks whose readings differ in
consequence is the nocuous/innocuous ambiguity distinction (Chantree, Nuseibeh et al.). Measuring
a suite by what it fails to catch is mutation testing (DeMillo, Lipton, Sayward). Writing the
prediction before looking at the data is pre-registration. Sampling several implementations of one
requirement and treating behavioural disagreement as ambiguity is ClarifyGPT (FSE 2024). What an
LLM changes is that the second reader costs minutes, not a team.
