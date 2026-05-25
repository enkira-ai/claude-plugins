---
description: Snapshot a GitHub Epic's actionable sub-issue sequence — topologically sorted by blocked_by edges, with parallel-eligible items grouped into tiers. Read-only against GitHub. Output is a JSON state file (default /tmp/epic-shepherd-state-<N>.json) that future Phase-2 epic-shepherd ticks consume.
---

Use the `epic-shepherd:epic-shepherd` skill (Phase 1) to extract the
actionable sub-issue sequence for an Epic.

Epic issue number: $ARGUMENTS

Run the Phase 1 extractor:

```bash
SCRIPT="$(dirname "$(find ~/.claude -path '*epic-shepherd/scripts/extract-sequence.py' 2>/dev/null | head -1)")/extract-sequence.py"
python3 "$SCRIPT" --epic $ARGUMENTS
```

When done, report:

1. **The output path** (`/tmp/epic-shepherd-state-<N>.json` by default).
2. **The tier breakdown** (tier 1 items are actionable right now; tier
   2+ items are blocked by their listed in-epic predecessors).
3. **Any `paused` block** (cycle in the blocked-by graph) — surface the
   list of involved issues so the operator can break the cycle by
   deleting one of the backward dependency edges.
4. **`external_blockers_total`** if non-zero — these don't block
   sequencing but the operator may want to chase them out-of-band.

If no epic number was given, ask for one (do not guess).

Do **not** mutate any GitHub state in this command — `extract-sequence`
is read-only by contract. Mutation belongs in future Phase 2 / Phase 3.
