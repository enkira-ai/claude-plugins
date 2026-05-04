---
name: narrative-video-production
description: End-to-end playbook for producing a multi-segment narrative video that mixes photos, embedded videos (talking heads, b-roll, archival), background music, and on-screen text/title cards — assembled in a custom in-browser composition (HTML + React/Babel-standalone, NOT Remotion), then captured via screen recording and finished with ffmpeg. Use this whenever the user wants to build a story-driven video from raw mixed-media assets — slideshow with theme, year-in-review, project retrospective, family/wedding/birthday montage with arc, course summary, documentary opener, conference recap, memorial, anniversary, organizational milestone reel — particularly when there are dozens to hundreds of photos to triage, multiple short videos to integrate, a designed musical backdrop, and a thematic structure the user has in mind. Triggers on phrases like "make a video for X", "story video", "video montage", "slideshow with music", "tribute video", "纪念视频", "聚会视频", "anniversary", "year-end recap", or whenever the user has folders of mixed media and a narrative idea but no specific tool preference.
---

# Narrative Video Production · Pipeline Skill

A 3-10 minute narrative video typically pulls from dozens-to-hundreds of photos, several short videos, and a thematic structure (story arc, metaphor, chronology, or musical progression). This skill captures the full pipeline that produces such a video — from raw material intake through final compressed mp4 — without locking into any specific subject matter.

The pipeline is **8 phases**. They are not strictly sequential — Phase A and B can interleave; Phase C runs in parallel with B; Phase F and G can iterate.

```
A · Material Intake          → inventory raw assets, capture user intent
B · Photo Pipeline           → tag with vision LLM, curate by Finder pruning
C · Video Pipeline           → normalize encoding, STT for content awareness
D · Storyboard Design        → narrative arc, theme, block timing, motif
E · Composition (Browser)    → custom React/Babel-standalone, NOT Remotion
F · BGM Generation           → instrumental beds + optional vocal layers
G · Post-mix                 → screen-record → ffmpeg mux speech + BGM + ducking
H · Compress + Deliver       → CRF 23 H.264, faststart, ~2-3 Mbps for 1080p
```

The kinds of projects this skill handles:

- **Reunions, anniversaries, milestone celebrations** (class reunions, weddings, retirement)
- **Tributes, memorials** (in memoriam, retirement honors, "this is X's life")
- **Year-in-review / annual recaps** for organizations, families, projects
- **Project retrospectives** (research lab year, startup founding story, hackathon recap)
- **Course summaries / educational reels** (semester montage with student work)
- **Documentary openers** (5-10 min intro with archival footage and narration)
- **Conference recaps** (event highlights with speaker snippets)
- **Personal stories** (one person's chapter, told over photos and short clips)

Different subjects, same architecture. The story / metaphor / theme varies, but the production pipeline is the same.

## Quick start

When the user has a folder of photos + videos and a vague theme:

1. Read `references/00-orchestration.md` for the order-of-operations and project structure
2. Create a `progress.md` from `templates/progress.md.template` — this becomes the planning + state doc you update at every phase
3. `git init` early — many edits, easy rollback. Add `.gitignore` for binary assets BEFORE the first commit.

## When to read which reference

| Phase | Reference file | When to read |
|-------|----------------|--------------|
| A | `references/01-material-intake.md` | First contact — survey what's there, capture user intent |
| B | `references/02-photo-pipeline.md` | Many photos to tag/curate |
| C | `references/03-video-pipeline.md` | Short videos to normalize + transcribe |
| D | `references/04-storyboard.md` | Designing the narrative arc + theme |
| E | `references/05-implementation.md` | Writing the in-browser composition |
| F | `references/06-bgm-generation.md` | Generating instrumental beds |
| G | `references/07-post-production.md` | Recording the browser playthrough + final mux |

## Critical lessons that don't fit elsewhere

These are session-learned gotchas — read once before starting:

### Path / filename hygiene

- **Trailing space in directory names breaks tooling**: git, Python's http.server, and SSH-based file transfers all silently misroute when a path has a trailing space. If the user's project folder has one, either rename or work entirely with absolute quoted paths.
- **`+` in filenames** breaks URL routing in some HTTP servers (Python's auto-decodes `+` as space in path). Rename source media files to use `_` instead of `+` before referencing them in browser-based composition.
- **Chinese / accented / non-ASCII characters in filenames** are fine for git, ffmpeg, and modern http.server, but be careful with Bash arrays and shell expansion — wrap everything in proper quoting.

### Multimodal LLM choices

- **For photo tagging at scale (50-200+)**: dispatch parallel Haiku subagents (~20 photos per batch). They use the `Read` tool to view thumbnails and emit JSONL. No external API key needed — runs through Claude's own credit. See `references/02-photo-pipeline.md`.
- **For video transcription (Mandarin)**: Deepgram `nova-2 + language=zh-CN` works well. **`nova-3 + language=multi` does NOT work for Mandarin** despite being newer — it returns near-empty transcripts. For English, both nova-2 and nova-3 work. Confirm language before picking.

### BGM generation reality

- **Open-source music models (heartlib / HeartMuLa) have no real instrumental mode** — they're trained on songs. The `<||>` placeholder hack helps but vocals still leak. Use commercial tools (Suno, MiniMax Music) for instrumental beds.
- **Browser autoplay**: HTML5 `<audio>` autoplay fails silently on first load. Pass `autoplay={false}` to your Stage so initial state is paused → user clicks Play (= gesture) → audio unlocks.
- **Don't capture system audio in screen recording**. macOS built-in recorder doesn't support it without extra drivers. Better path: record video silent → ffmpeg post-mix speech (extracted from source talking-head videos at known timeline offsets) + BGM.

### Framework choice

The default framework is a **custom 200-line React/Babel-standalone Stage + Sprite system**, NOT Remotion. The advantages:

- No npm install / no toolchain
- Live edit JSX, refresh browser, see changes
- Browser-native HTML5 video/audio elements (real codecs, no transcoding)
- Easy to capture via macOS Cmd+Shift+5

The disadvantages:

- No "render to mp4" out of the box (have to screen-record)
- Limited to browser performance (1080p @ 60fps is fine on M-series Mac)

If the user has Remotion experience and wants programmatic rendering, you can adapt the patterns to Remotion. Default to the simpler framework — see `templates/` and `references/05-implementation.md`.

### Common cost levers

- **RunPod A40 community cloud** ~$0.35/hr, sufficient for any heartlib-style local music generation. Total music budget rarely exceeds $1.
- **Photo tagging via parallel Haiku subagents** uses Claude credits (no separate API). ~200 photos costs a few cents.
- **Deepgram STT** is per-minute, ~$0.005/minute. Total project STT budget <$0.50.
- **Suno Pro** ~$10/month for unlimited music generation if many iterations needed.

## Don't reinvent these

The `scripts/` directory has working scripts that took multiple iterations to debug. Use them:

- `serve.py` — robust local static server that swallows BrokenPipeError (browsers cancel range requests on large videos all the time). **Don't use vanilla `python -m http.server`** — it spams errors mid-recording and can corrupt long captures.
- `photos_data_gen.py` — generates JS constants from filesystem so the browser composition doesn't need a build step. Re-run anytime user moves/renames files in their curation folder.

The `templates/` directory has working scaffolding. Copy and adapt:

- `progress.md.template` — the planning + state doc structure
- `animations.jsx.template` — Stage / Sprite framework, easings, interpolation helpers
- `primitives_full.jsx.template` — custom primitives (PhotoBlock, VideoClip, BackgroundBGM, TransitionCard, etc.)
- `scenes_full.jsx.template` — full scene structure with TF (timeline anchor) pattern
- `reunion_full.html.template` — entry HTML (rename to fit the project)
- `mux_recorded.sh.template` — final ffmpeg mux script with selective ducking

Templates come from a working project (a class reunion video). Replace the domain-specific content (class names, idioms, photos) but keep the structure — the architecture generalizes.

## A note on iterating with the user

Narrative videos are emotional projects. Whether it's a reunion, a memorial, a love story, or a research retrospective, the user has memories or meaning tied to specific photos, specific moments, specific phrases. **Do not optimize purely for technical cleanliness** — when the user says "this photo doesn't go here" or "the wording feels wrong", that's not a bug report, that's the design. Treat their corrections as ground truth and update plans, not litigate.

That said: **do push back on technical infeasibility** (e.g., "Suno can't reliably do >5 min single track, here's a workaround") and on **time-budget realities** (e.g., "regenerating BGM = 15 min wall clock, not 1 min"). Your job is to be a good orchestrator, not a yes-bot.

Finally: **the audio-visual production is fundamentally a craft**, not just engineering. Pacing, breath, the moment a photo lingers vs flickers, the silence before a phrase lands — these come from the user's taste, not yours. Your role is to make iteration cheap so they can taste-test and adjust quickly. The win condition is not "I built it perfectly first time" — it's "the user iterates 10 times, each cheaply, and lands on something that feels right to them".
