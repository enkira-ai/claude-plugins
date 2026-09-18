## Spec-derived test plan — written before reading this PR's code

**Read**: <owning issue>, <SPEC(s) with section numbers>, <ADRs>, <architecture docs>, and the
base-branch contracts in `<paths>` (as on `<base>` at `<sha>`).
**Not read**: PR #<N> in any form. The follow-up comment pins the head it is diffed against.
**Contamination**: <none | "I saw the test file names listed in ADR-NNNN §x; nothing below is
derived from their contents">.

The point is to get a second reading of the spec on record so the diff between this plan and what
the PR built tells us where the spec admits more than one implementation. A follow-up comment does
that comparison.

### A. Where the spec forks — the reading I test against

Each row is a place where I had to choose. The last column is why the fork matters; if the PR took
the other branch and that column is bad, the spec owes a sentence, not the PR.

| # | Fork | Reading I test | Other reading | Bad result if the other branch wins |
| --- | --- | --- | --- | --- |
| F1 | <spec §x says …; AC-n says …> | <the reading> | <the other reading> | <which AC breaks, who is harmed, what is observed> |
| F2 | … | … | … | <"neither branch is unsafe; the spec should still pick one"> |

### B. Test matrix

Layer key: **U** = deterministic unit with fakes; **DB** = real database; **M** = migration
round-trip; **I** = integration (opt-in).

#### B1. <spec section> — AC-a, AC-b

| Assertion | Layer |
| --- | --- |
| <one observable assertion> | U |
| <truth table when two axes cross: mode × state, arrival × method> | U, DB |

#### B2. …

<An AC from which no test can be derived goes here as a row reading "AC-n: not testable as
written — <why>". That is a spec finding, not a gap in this plan.>

### C. What I would not accept as evidence

- <an in-memory fake for a concurrency AC; only the DB layer counts>
- <a log-line assertion for a privacy AC; it must be asserted on persisted rows and event payloads>
- <"N passed" without naming which tier ran>

### D. Where I expect the spec to be thin, before I look

Stated up front so I cannot claim afterwards that I knew:

1. <the single most likely divergence, and why>
2. …

### E. Mutation checks I will apply to the PR's suite

Each should turn a test red: <drop gate check n>; <swap the clip/remove order>; <ignore the
`granted` flag>; <add a ring window the spec forbids>; <let a second reservation proceed>.

Next: I will read the PR's implementation and tests and post the diff against this plan — which
forks it took, where it agrees, and where the spec, the code, or the harness needs a change.
