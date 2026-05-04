# Phase A · Material Intake

The user comes in with rough material. Your first job is to inventory it without touching anything.

## What to look for

```bash
# Top-level survey
ls -la <project_root>/
du -sh <project_root>/*/ | sort -h

# Photo counts per top-level + subfolders (handles non-ASCII names)
find <photo_folders...> -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.heic" \) | wc -l
for d in <photo_folder>/*/; do echo "$d: $(find "$d" -type f -name '*.jpg' | wc -l)"; done

# Video inventory
ls -la <videos_folder>/
ffprobe -v error -show_entries format=duration -of default=nw=1 <videos_folder>/*.mp4
```

Most projects fall into one of these shapes:

- **Folder per era / chapter**: `before/`, `during/`, `after/` — common for chronological stories
- **Folder per person / contributor**: `alice/`, `bob/`, `chris/` — common for tributes and reunions
- **Folder per category / event**: `weddings/`, `trips/`, `awards/` — common for retrospectives
- **One big flat folder**: needs Phase B tagging to give it any structure

## What to extract from the user

Don't proceed past intake until you have rough answers to:

| Question | Why it matters |
|----------|----------------|
| **Total length target** (3 min vs 5 min vs 10 min) | Sets photo block density and pacing budget |
| **Theme / spine** ("the year we shipped", "from then to now", "in memoriam", "rivers and mountains") | Drives storyboard, transitions, motif |
| **Anchor element(s)** — what's the strongest opening element? closing element? | Determines edit points. Often the strongest emotional beats. |
| **Motif / through-line** — a phrase, image, or sound that recurs | The thing that ties everything together; appears at start AND end |
| **Audience** — who's watching? insider group, family, public? | Tightens decisions on jargon, references, duration |
| **Deadline + iteration time available** | If <1 day, simplify (skip BGM generation, use stock music or no music); if >1 week, full iteration |
| **Special constraints** — must include person X / event Y / song Z? | Catch these now, not in Phase E |

## What's typical (across project types)

- 50-300 raw photos, multiple categories
- 0-10 short embedded videos (talking heads, b-roll, archival), 10-90 seconds each
- 0-2 anchor video(s) — typically one for opening, one for closing
- 2-5 middle videos to interleave between photo blocks (if available)
- Story arc with 3 acts: setup → body → resolution
- Total length: 3-7 minutes for personal projects, up to 10 minutes for organizational
- Roughly 50% video time, 40% photo time, 10% transitions/title (if videos available)
- 100% photos when no embedded videos (slideshow with title cards as transitions)

## Output of Phase A

Update `progress.md` with:

```markdown
## Phase A · Inventory

**Total raw material**:
- Photos: N (in K subfolders)
- Videos: M total, total duration ~Ms (avg K seconds)

**Anchors decided**:
- Opening: <video filename or photo title>
- Closing: <video filename or final image>
- Motif: "<the recurring phrase / image / sound>"

**Theme**: <one-sentence description>
**Target length**: ~N min
**Audience**: <insider | family | public | mixed>
**Constraints**: <list anything that MUST be included>
**User availability**: <time blocks for review iterations>
```

Then move to Phase B (photos) and Phase C (videos) — these can run in parallel.

## Common pitfalls

- **Skipping the theme question**: Without it, you'll over-produce and the user will have to redo. Ask explicitly. If user says "I don't know yet", suggest 2-3 frames and let them pick.
- **Counting wrong**: User often estimates verbally; reality differs. Don't trust the verbal estimate, run `find | wc -l`.
- **Missing nested folders**: Photos may be 3-4 levels deep. Use recursive `find`.
- **Trailing-space directory**: e.g., `nju /` vs `nju/`. Happens when copying from cloud storage. Detect with `ls -la <parent_dir> | grep ^d` and rename early.
- **Filenames with `+`** in source media break URL routing in browser composition (Phase E). Catch in Phase A, rename: `for f in *+*.mp4; do mv "$f" "${f//+/_}"; done`
- **"I have hundreds of photos"** — check whether they're already de-duplicated. Cloud photo libraries often double-export. Catch obvious duplicates by file hash before tagging.
