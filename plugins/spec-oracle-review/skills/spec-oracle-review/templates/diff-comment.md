## Plan vs. implementation — where the spec forked, what leaked, what to fix

Follow-up to the [pre-read plan](<link>). Method: read all <N> changed files at `<head sha>`,
then in a throwaway worktree (a) ran <n> probe tests encoding the plan's readings against the
**unmodified** head and (b) applied <m> single-line mutations to the PR's suite. Baseline: <k>
tests green. Every claim below is backed by a probe trace, a mutation result, or a line reference;
anything inferred from reading alone is marked *by reading*.

**Tally against the plan:** <R> rows. <p> pinned by a test. <f> forks where the PR took the other
branch. <g> with no test. <x> behaviours the spec did not ask for. <u> unreachable by construction.

### 0. Where I was wrong and the code was right

| # | My plan said | Reality | Verdict |
| --- | --- | --- | --- |
| A1 | <plan row> | <what the base branch or the code actually requires> | <spec defect the plan inherited / my misreading> |

### 1. Fork outcomes

| # | Fork | Branch the PR took | Verdict |
| --- | --- | --- | --- |
| F1 | <fork> | <branch, with `file.py` `function` cite> | **SPEC must pin**: "<proposed sentence>". Recommend <branch>, because <consequence>. |
| F2 | <fork> | <branch> | Matches plan; **fine but pin it** in §x. |
| F<n+1> (new) | <fork found while reading> | … | … |

### 2. Defects reproduced (ranked)

**2.1 <one-line title>.** <Mechanism, in two sentences.> Probe: `<trace: returned state / event
payload / row>`. <Which AC it violates.> Fix: <smallest change>. **Blocking.**

**2.2 …**

### 3. Harness gaps — mutation evidence

<m> mutations applied; <s> survived, <c> caught; controls <list> were caught, so the suite works
where it looks.

| Mutation | Survived | Plan ID it should have tripped |
| --- | --- | --- |
| M1 <drop merge-time caller-present check> | ✅ | F1.1 |
| M2 … | ❌ caught | — |

Plan rows with no test on the branch, by section (each is one focused test):

- **B1** <row> — <suggested test name>
- **B2** …

Other findings about the suite itself: <fixtures built and never asserted; a test whose name
promises what its body does not exercise; sentinel values too weak to prove absence; a PR claim
the tests do not support>.

### 4. Unreachable / dead

- <plan row or spec clause> — impossible because <constraint>; delete or mark in §x.
- <code path> — no requirement drives it; <keep with a comment | remove>.

### 5. Documentation drift

- <spec table that no longer matches shipped file names>
- <ADR metadata this PR should have updated>
- <PR body claims to correct>

### 6. Suggested order

1. <the defect that silences / loses money / violates the load-bearing AC>, with its test.
2. <the rest of bin (b) together, with payload/state tests>.
3. <bin (a) rulings pinned in the spec in this PR; implement the chosen branch>.
4. <bin (c) tests; state which tiers actually ran>.
5. <docs>.

### Verdict

<Mergeable | Not mergeable as is>: <one sentence naming the blocking items and the ACs they
violate>. Needs an owner ruling on <F-list>. Happy to turn the probe file into proper tests on the
branch if the author wants that instead of re-deriving them.

<details>
<summary>Probe script (drop into <code>tests/…</code> to reproduce 2.1–2.n)</summary>

```python
# one probe per fork / contested row; asserts the plan's reading; fails on the unmodified head
```
</details>
