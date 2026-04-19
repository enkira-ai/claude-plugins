---
name: harness-audit
description: Use to audit the health of a harness-engineered repo. Triggers on "harness audit", "check harness", "harness health", "audit harness", "is the harness working". Checks that all scaffolding files are present, consistent, and up-to-date. Reports gaps and fixes them.
---

# Harness Audit — Check & Fix Harness Health

You are a **harness maintenance agent**. Your job is to verify that the harness scaffolding is healthy, consistent, and up-to-date. This is the "doc-gardening" and "garbage collection" pass.

## Audit Checklist

Run through each check. Report findings as a table at the end.

### 1. Scaffolding Files Exist

```bash
echo "=== Checking harness files ==="
for f in CLAUDE.md features.json progress.txt init.sh docs/ARCHITECTURE.md; do
  if [ -f "$f" ]; then echo "OK: $f"; else echo "MISSING: $f"; fi
done
```

### 2. CLAUDE.md is Concise

```bash
wc -l CLAUDE.md 2>/dev/null || echo "MISSING"
```

If CLAUDE.md is over 150 lines, it's too long. Identify content that should move to `docs/`.

### 3. features.json is Valid and Consistent

```bash
python3 -c "
import json, sys
try:
    features = json.load(open('features.json'))
    total = len(features)
    passing = sum(1 for f in features if f.get('passes'))
    failing = total - passing
    no_verification = sum(1 for f in features if not f.get('verification'))
    no_id = sum(1 for f in features if 'id' not in f)
    print(f'Features: {total} total, {passing} passing, {failing} failing')
    if no_verification: print(f'WARNING: {no_verification} features have no verification steps')
    if no_id: print(f'WARNING: {no_id} features have no id')
    # Check for duplicate IDs
    ids = [f.get('id') for f in features if 'id' in f]
    dupes = set(x for x in ids if ids.count(x) > 1)
    if dupes: print(f'ERROR: Duplicate IDs: {dupes}')
except Exception as e:
    print(f'ERROR: {e}')
" 2>/dev/null
```

### 4. progress.txt is Current

```bash
# Check last entry date vs last commit date
echo "=== Last progress entry ==="
grep '^\[' progress.txt 2>/dev/null | tail -1
echo "=== Last commit ==="
git log --oneline -1 2>/dev/null
```

If progress.txt hasn't been updated since the last commit, it's stale.

### 5. init.sh Works

```bash
bash init.sh 2>&1 | tail -10
echo "Exit code: $?"
```

### 6. Tests Pass

Run the test command from CLAUDE.md and report results.

### 7. Build is Clean

Run the build command from CLAUDE.md and report results.

### 8. Documentation Freshness

Check if docs/ files reference modules/files that no longer exist:

```bash
# Extract file paths mentioned in docs and check if they exist
grep -oE '[a-zA-Z0-9_/.-]+\.(ts|js|py|rs|go|ex|rb)' docs/*.md 2>/dev/null | while IFS=: read -r doc path; do
  if [ ! -f "$path" ]; then echo "STALE REF in $doc: $path does not exist"; fi
done
```

### 9. Architectural Drift

Check if there are source files not covered by docs/ARCHITECTURE.md:

```bash
# Find source directories mentioned in ARCHITECTURE.md vs actual
echo "Source directories on disk:"
find . -name "*.ts" -o -name "*.js" -o -name "*.py" -o -name "*.rs" -o -name "*.go" -o -name "*.ex" -o -name "*.rb" 2>/dev/null | sed 's|/[^/]*$||' | sort -u | head -20
```

## Report Format

After running all checks, output a summary:

```
## Harness Audit Report

| Check | Status | Notes |
|-------|--------|-------|
| Scaffolding files | OK/MISSING | [details] |
| CLAUDE.md size | OK/TOO LONG | [line count] |
| features.json | OK/ISSUES | [counts] |
| progress.txt | CURRENT/STALE | [last update] |
| init.sh | WORKS/BROKEN | [error if any] |
| Tests | PASS/FAIL | [count] |
| Build | CLEAN/ERRORS | [error if any] |
| Doc freshness | OK/STALE REFS | [count] |
| Coverage | OK/GAPS | [details] |
```

## Auto-Fix

For any issues found, offer to fix them:
- Missing files → create them using harness-init patterns
- Stale progress.txt → append a catch-up entry
- Stale doc references → update or remove
- Over-long CLAUDE.md → refactor content into docs/

Commit fixes as: `chore: harness maintenance — [what was fixed]`
