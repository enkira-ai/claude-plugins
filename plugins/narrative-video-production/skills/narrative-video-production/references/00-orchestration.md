# Orchestration · Project Structure & Order of Operations

## Recommended directory layout

```
<project_root>/
├── progress.md                  ← living planning doc, update each phase
├── .gitignore
├── photos_a/                    ← raw photos in any naming, subfolders OK
├── photos_b/                    ← (optional) photos from a second era / category
├── videos_raw/                  ← raw input videos (.MP4/.MOV/.mp4/.mov), any source
├── _thumbs/                     ← (gen'd Phase B) sips-resized 512px thumbs for vision LLM
├── _tags/                       ← (gen'd Phase B) JSONL output from Haiku batches
├── photos_index.csv             ← (gen'd Phase B) consolidated tagged inventory
├── videos_index.csv             ← (gen'd Phase C) ffprobe + STT summary
├── _curated/                    ← (gen'd Phase B') user-pruned photo selection
│   ├── manifest.csv             ←   new_filename → original_path mapping
│   ├── _hashlink.csv            ←   md5-based provenance (survives renames!)
│   ├── block1_xxx/              ←   photos for storyboard block 1
│   ├── block2_xxx/
│   └── ...
├── project/                     ← (Phase E) self-contained browser composition
│   ├── reunion_full.html        ←   entry point
│   ├── animations.jsx           ←   framework (Stage, Sprite, easings)
│   ├── scenes/
│   │   ├── primitives.jsx       ←   shared primitives
│   │   ├── primitives_full.jsx  ←   custom primitives for this video
│   │   ├── photos_data.js       ←   auto-generated photo path constants
│   │   └── scenes_full.jsx      ←   scene definitions with TF anchors
│   ├── _curated/                ←   moved here for self-containment
│   ├── videos/                  ←   normalized videos (Phase C output)
│   ├── photos/                  ←   draft assets (e.g., evo_2006-2026.jpg for timeline)
│   ├── bgm/                     ←   bgm.mp3 for browser preview
│   ├── logos/                   ←   any logos for outro
│   ├── serve.py                 ←   robust local server (use over python -m http.server)
│   └── favicon.ico              ←   silence 404
├── bgm/                         ← (Phase F) generated music tracks
│   ├── bed1.mp3, bed2.mp3, ...
│   ├── bed_continuous.mp3       ←   crossfaded combined bed
│   └── (optional) v1-4.mp3 vocals
├── audio_for_imovie/            ← (Phase G alt) extracted speech tracks for manual mix
├── BGM_PROMPT.md                ← bed prompts for Suno/MiniMax
├── mux_recorded.sh              ← (Phase G) final ffmpeg mux script
├── aa.mov                       ← user's screen recording (any name)
├── aa_trimmed.mp4               ← trimmed/scaled to 1920×1080 + target duration
└── reunion_final.mp4            ← (Phase H) final compressed deliverable
```

Notes:

- The `project/` folder should be **self-contained** — all assets it references live inside it. This makes `cd project/ && python3 serve.py` enough to preview. Move `_curated/` and normalized `videos/` into `project/` after Phase B'/C complete.
- The `_hashlink.csv` is critical — once the user starts moving/renaming photos in Finder during curation, filename-based mapping breaks. Hash-based mapping survives.

## Order of operations

```
[A · Intake]   inventory raw assets, count photos & videos
                   ↓
[B · Photo]    sips → Haiku tag → photos_index.csv
                   ↓
[B' · Curate]  build _curated/ folders by storyboard block
                user prunes via Finder
                regen photos_data.js from filesystem
                   ↓
[C · Video]    ffprobe → ffmpeg normalize → Deepgram STT
   (parallel)      ↓
[D · Story]    storyboard with TF (timeline anchors)
                physics/poetic theme + transitions
                idiom ↔ formula pairings (if applicable)
                   ↓
[E · Compose]  primitives_full.jsx → scenes_full.jsx → reunion_full.html
                live preview in browser via serve.py
                user reviews, requests changes, you iterate
                   ↓
[F · BGM]      generate beds (Suno/MiniMax) + optional vocals (heartlib on RunPod)
   (parallel)      ↓
[G · Post-mix] screen-record reunion_full.html via Cmd+Shift+5
                ffmpeg trim → mux speech + BGM with ducking → final mp4
                   ↓
[H · Compress] CRF 23, +faststart → ~100-150 MB for 6-7 min @ 1080p
                deliver
```

## Time budget (rough)

For ~200 photos + 7 short embedded videos + ~7-min target:

| Phase | Wall clock | Bottleneck |
|-------|------------|------------|
| A | 10 min | inspecting folders |
| B | 30 min | parallel Haiku batches |
| B' | 30-90 min | **user pruning in Finder** |
| C | 15 min | ffmpeg normalize + Deepgram STT |
| D | 30-60 min | back-and-forth on storyboard |
| E | 2-4 hours | building scenes + iterating with user |
| F | 30 min | gen + listen + decide |
| G | 30 min | record + mux |
| H | 5 min | ffmpeg compress |

**User-time-blocking phases**: B' (curation), D (storyboard), E (review iterations), F (listen/judge BGM). Plan around their availability.

## Use TaskCreate / planning tools liberally

This is a multi-day project for the user. Use the Plan / TaskCreate tools to maintain visible progress. Update `progress.md` at each major decision so the next session can pick up cold.

## When the user comes back mid-project

If the user says "let's continue the reunion video", re-read `progress.md` first. It captures:
- Current phase and state
- Decisions locked in (titles, timing, theme)
- Open questions blocking progress
- Recent errors / workarounds

Don't re-derive from code — `progress.md` is authoritative for *intent*.
