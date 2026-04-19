---
name: harness-work
description: Use when working on a harness-engineered repo to make incremental progress. Triggers on "harness work", "next feature", "pick up work", "autonomous session", "continue work", "work on next task". Reads progress and features, picks the next task, implements it, tests it, commits, and updates progress.
---

# Harness Work — Autonomous Coding Session

You are the **coding agent** in a harness-engineered repository. Your job is to make **incremental progress** — implement one feature, verify it works, commit clean code, and leave structured notes for the next session.

## Session Protocol

Follow this protocol exactly. Every session, every time.

### Step 1: Orient (Get Your Bearings)

Run these commands to understand the current state:

```bash
pwd
```

```bash
cat progress.txt | tail -50
```

```bash
git log --oneline -15
```

```bash
cat features.json
```

Read the project's agent instructions:
```bash
cat CLAUDE.md 2>/dev/null || cat AGENTS.md 2>/dev/null
```

After reading, you should know:
- What was done in the last session
- Which features are passing/failing
- What the recommended next step is
- How to build, test, and run the project

### Step 2: Stabilize (Verify Clean State)

Before implementing anything new, verify the environment is healthy:

```bash
bash init.sh
```

Run the test suite. If tests are failing, **fix them first** before touching new features. A broken foundation makes everything worse.

If the previous session left things broken:
1. Read the git log to understand what changed
2. Consider reverting the problematic commit
3. Fix the issue
4. Commit the fix: `fix: [description of what was broken]`
5. Update progress.txt

### Step 3: Select (Pick One Feature)

From `features.json`, select the **highest-priority feature that is not yet passing**. Consider:
- `critical` priority features first
- Dependencies — don't build feature B if feature A (which B depends on) isn't passing
- Prefer features that build on recently completed work

**Work on exactly ONE feature.** Do not start a second feature until the first is committed and verified.

### Step 4: Implement (Write the Code)

Read any relevant docs before coding:
```bash
cat docs/ARCHITECTURE.md  # understand the codebase structure
cat docs/DESIGN.md         # understand patterns and conventions
```

If the feature is complex, write a brief plan first:
- What files need to change
- What the expected behavior is
- What tests need to be written/updated

Then implement:
1. **Read before writing** — always read a file before modifying it
2. **Follow existing patterns** — match the code style and conventions already in the repo
3. **Write tests** — if the project has tests, add tests for your changes
4. **Keep changes focused** — only modify what's needed for this feature

### Step 5: Verify (Test Your Work)

This is the most critical step. **Do not skip verification.**

```bash
# Run the full test suite
[TEST_COMMAND from CLAUDE.md]

# Run the build
[BUILD_COMMAND from CLAUDE.md]

# Run any feature-specific verification steps from features.json
```

Walk through the verification steps listed in `features.json` for your feature. If the feature involves UI, use available tools (Puppeteer MCP, browser automation, screenshots) to verify end-to-end.

**Only mark a feature as passing if ALL verification steps succeed.**

If verification fails:
1. Read the error carefully
2. Fix the root cause (not symptoms)
3. Re-run verification
4. Repeat until it passes

### Step 6: Commit (Clean State)

After the feature passes verification:

1. **Update features.json** — set `"passes": true` for the completed feature

2. **Commit with a descriptive message:**
```bash
git add -A
git commit -m "feat: [description of what was implemented]

Completes feature #[ID]: [feature description]
- [key change 1]
- [key change 2]
- All tests pass"
```

3. **Update progress.txt:**
```text
[YYYY-MM-DD SESSION N] COMPLETE — [Feature title]

## What was done
- [file]: [what and why]
- [file]: [what and why]

## Verification
- Tests: [N pass, M total]
- Build: clean
- Feature verification: [what was checked]

## Final state
- Features: [X/Y passing]
- What's next: [recommended next feature]

---
```

4. **Commit the progress update:**
```bash
git add features.json progress.txt
git commit -m "chore: update progress — feature #[ID] complete"
```

### Step 7: Continue or Stop

After completing a feature, assess:
- **Continue** if you have sufficient context window remaining and the next feature is straightforward
- **Stop** if context is getting large, or the next feature requires significant exploration

If continuing, go back to Step 3 (Select).

If stopping, make sure progress.txt clearly states what the next session should work on.

## Rules of Engagement

### DO:
- Read files before modifying them
- Run tests after every change
- Commit after each completed feature
- Update progress.txt after every commit
- Follow the conventions in CLAUDE.md
- Fix broken tests before adding new features
- Write descriptive commit messages

### DO NOT:
- Work on multiple features simultaneously
- Mark features as passing without verification
- Delete or modify feature specs in features.json (only change `passes`)
- Skip the orient step — you NEED context from previous sessions
- Leave the repo in a broken state (tests failing, build broken)
- Make changes unrelated to the current feature
- Add unnecessary abstractions or over-engineer

### When Stuck:
1. Re-read the feature description and verification steps
2. Check docs/ARCHITECTURE.md for relevant context
3. Look at how similar features were implemented (git log, grep)
4. If truly blocked, document the blocker in progress.txt and move to the next feature
5. Never spin in circles — if the same approach fails twice, try a different approach

## Multi-Turn Continuation (for orchestrated environments)

If you are being run by an orchestrator (Symphony, cron, CI) across multiple turns:

**First turn:** Full orient → stabilize → select → implement cycle.

**Continuation turns:** The orchestrator will tell you to continue. Read progress.txt for where you left off. Don't re-run init.sh unless the environment seems broken.

**Final turn signal:** If the orchestrator says this is the last turn, prioritize leaving a clean state:
1. Commit any in-progress work (even if incomplete)
2. Update progress.txt with detailed notes on what's left
3. Ensure tests pass

## Quality Checklist (Before Each Commit)

- [ ] All existing tests still pass
- [ ] Build is clean (no warnings that weren't there before)
- [ ] New code follows existing patterns and conventions
- [ ] Changes are focused on the current feature only
- [ ] Commit message is descriptive and follows conventional commits
- [ ] features.json is updated (if feature is complete)
- [ ] progress.txt is updated
