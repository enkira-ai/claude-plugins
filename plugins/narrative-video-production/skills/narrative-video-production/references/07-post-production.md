# Phase G + H · Post-mix and Compress

## Phase G · Recording the browser playthrough

The composition is in the browser; getting it to mp4 means screen-recording.

### Two recording paths

**Path A · Mac built-in (Cmd+Shift+5)** — recommended, simplest

- Records video at retina resolution (e.g., 2560×1440 if MacBook Air display)
- **Does NOT record system audio** by default. Don't try to fight this — record silent and mux audio in post.
- File saved as `.mov` (H.264, ~40-60 Mbps, very large)
- Allows trim in built-in editor before saving

**Path B · Puppeteer-driven headless (project/render/record.js)** — risky, often broken

- Programmatic, deterministic
- Captures via `page.screencast()` to silent webm
- Can suffer from playback rate issues, font rendering issues, video codec issues
- The the example project tried this and abandoned it — Puppeteer's video rendering doesn't always match what the user sees in their browser.

**Default to Path A** unless user already has a working Puppeteer setup.

### Recording checklist

Before user records:
1. **Restart serve.py** to ensure clean state
2. **Hard-refresh the browser** (Cmd+Shift+R) to flush cached assets
3. Confirm preview plays end-to-end without stutter
4. Set browser zoom to 100%
5. Make browser window match composition size (1920×1080) — use Chrome dev tools' device emulation
6. Hide bookmark bar, extensions, etc. Anything visible bleeds into the recording.
7. Start Cmd+Shift+5 → "Record Selected Portion" → drag the rectangle to match the canvas exactly
8. Click Record, switch to browser, click Play, wait for video to end (Stage stops at TF.TOTAL), stop recording

Common issues:
- **User's lead-in is in the recording** (a few seconds of browser before they hit Play). Trim with `--video-offset N` flag in mux script
- **Recording is slightly too long** (kept rolling after end). Trim with `-t TOTAL` in ffmpeg
- **Recording captures playback bar** at the bottom. Adjust crop region to exclude it OR run Stage in fullscreen mode if framework supports it

## Phase G · ffmpeg post-mix

Use `templates/mux_recorded.sh.template` as the starting point. The script:

1. Trims and scales the recording to 1920×1080 + target duration
2. Layers BGM with **selective ducking** under specified talking-head ranges
3. Extracts speech audio from each talking-head MP4 at known TF offsets
4. amixes everything → final mp4

### Key script parameters

```bash
bash mux_recorded.sh recording.mov \
  --video-offset 3.5 \      # skip first 3.5s lead-in
  --bgm-vol 0.55 \          # default BGM level
  --duck-vol 0.22 \          # BGM during talking heads
  --speech-vol 1.0 \         # speech multiplier
  --out reunion_final.mp4
```

### Selective ducking

The the example project ducked BGM only under bed2/bed3 talking heads (per user direction — bed1 was already subtle enough). Customize `DUCK_RANGES` in the script:

```bash
DUCK_RANGES=(
  "192.77 231.49"   # talking head 5 — under bed2
  "246.49 294.70"   # talking head 6 — bed2/bed3 transition
  "334.20 363.51"   # talking head 7 — under bed3
)
```

Smooth ducking envelope (0.5s ramps in/out) handled in script via:

```bash
# For each duck range [A, B]:
PIECE="(clip((t-(${A}-${RAMP}))/${RAMP},0,1) - clip((t-${B})/${RAMP},0,1))"
# Final BGM vol: BGM_VOL - (BGM_VOL - DUCK_VOL) * sum(PIECE_i)
```

### iMovie alternative

If user can't get the ffmpeg script to produce satisfying ducking, **switch to iMovie**. iMovie's auto-ducking is high quality and the user can drag clips around manually. Provide them:

- Trimmed recording mp4 (1920×1080, target duration)
- BGM mp3
- 7 individual speech tracks (extracted from MP4s as `.m4a`)
- A timing table showing when each speech track should start in the timeline

```python
# scripts/extract_speech_for_imovie.py
import subprocess
scenes = [
    ('01_anchor_0m02.5s',     2.5,    'anchor1.mp4'),
    ('02_open_0m17.4s',       17.42,  'open.mp4'),
    # ... etc
]
for label, start, fn in scenes:
    src = f'project/videos/{fn}'
    dst = f'audio_for_imovie/{label}.m4a'
    subprocess.run(['ffmpeg','-y','-i',src,'-vn','-c:a','aac','-b:a','192k',dst], check=True)
    print(f"  {label}  place @ {start}s")
```

The filename encodes the timeline placement (e.g., `04_yu_2m13.7s.m4a` → drop at 2:13.7). User reads the filename and drags into iMovie's audio track.

### Loudness normalization

Some embedded videos are recorded **way** quieter than others. The the example project had one video at -48 dB mean (vs others at -21 to -29 dB) — totally inaudible without boost.

Use ffmpeg's `loudnorm` filter (EBU R128) to bring outliers up:

```bash
ffmpeg -y -i source_quiet.mov -vn -af "loudnorm=I=-16:TP=-1.5:LRA=11" -c:a aac -b:a 192k normalized.m4a
```

Targets -16 LUFS integrated, true peak -1.5dB. Standard for online video. Check loudness pre/post:

```bash
ffmpeg -i file.mp4 -af volumedetect -vn -f null - 2>&1 | grep -E "mean_volume|max_volume"
```

## Phase H · Final compression

Mac screen recordings are 40+ Mbps. Compress to ~2-3 Mbps for sharing.

```bash
ffmpeg -y -i reunion_final_recorded.mp4 \
  -c:v libx264 -preset medium -crf 23 -pix_fmt yuv420p \
  -c:a aac -b:a 128k \
  -movflags +faststart \
  reunion_final.mp4
```

For 6-7 min @ 1080p:
- CRF 20 → ~250-350 MB (highest quality you'd reasonably use)
- **CRF 23 → ~100-150 MB (recommended sharing default)**
- CRF 26 → ~70-100 MB (small but visible quality drop)
- CRF 28 → ~50-70 MB (mediocre quality, only for emails / messaging)

`-movflags +faststart` reorders MP4 metadata so the file starts playing while still downloading — crucial for sharing via WeChat, email, etc.

## Why post-mix in ffmpeg vs iMovie?

| Aspect | ffmpeg script | iMovie |
|--------|--------------|--------|
| **Reproducibility** | re-run with new BGM in 30 sec | manual drag every time |
| **Sync precision** | exact TF offsets | depends on user's eye/hand |
| **Volume curves** | scriptable, smooth | auto-ducking is good but opaque |
| **Time invested per pass** | ~3 min | ~10-30 min |
| **Ducking control** | per-range custom | auto-ducking is simpler |
| **User accessibility** | Claude only | non-technical user can iterate |

The ffmpeg path is faster for technical users, but iMovie wins when the user wants to **listen and adjust by ear** during multiple iterations. Default to ffmpeg for the first pass, switch to iMovie if user feedback gets specific ("this fade is too abrupt", "BGM should swell here").

## Output of Phase G + H

- `reunion_final.mp4` — 1920×1080, ~100-150 MB, ~6-7 min, plays everywhere
- All intermediate audio tracks in `bgm/` and `audio_for_imovie/` (in case user wants to redo)
- Source `aa_trimmed.mp4` (silent video) preserved (can re-mix without re-recording)

Deliver the final mp4 to user. Done.

## Honest current state of "automated final assembly"

**This phase is the least automated part of the pipeline today.** The user's confirmed practical workflow is:

1. macOS Cmd+Shift+5 to record the browser preview (silent video)
2. ffmpeg trim + scale to 1920×1080 + target duration
3. Open iMovie, drag the silent video in, drag in BGM mp3 + per-speech .m4a tracks (filename hints at timeline position), align by ear/eye, set per-track volumes (use iMovie's auto-ducking for the BGM-vs-speech mix), export
4. ffmpeg compress the iMovie export to CRF 23 + faststart

The `mux_recorded.sh` script in templates produces a usable mp4 in one shot, but **iMovie consistently produces better-feeling final mixes** because the user can listen and adjust each transition by ear. For high-stakes/personal projects, default to iMovie. For quick previews, use the script.

## Future improvement · programmatic HTML→mp4 via timecut

A path that hasn't been validated end-to-end on this pipeline but is worth trying when iteration cost is high enough:

**timecut** (https://github.com/tungs/timecut) by Steven Tung overrides `Date.now()`, `performance.now()`, and `requestAnimationFrame()` so the rendered page believes wall-clock is advancing exactly 1/fps per "tick". Puppeteer captures one frame, advances the virtual clock, captures the next. Frame-perfect, immune to system sleep, can run faster or slower than real-time. NOT to be confused with `cleancut` or other similarly-named tools.

This solves several problems with macOS screen recording:

- No need to be present / let it run real-time — render at any speed
- No frame drops from system load
- Exact 1920×1080 viewport, not retina-scaled
- Reproducible (re-run produces identical bytes)
- No worry about audio capture (do it in post anyway)

**The catch**: HTML5 `<video>` elements do not time-travel under timecut. They play in real wall-clock, controlled by the platform decoder — not by `Date.now()`. So scenes containing embedded `<video>` clips would either freeze on the first frame or stutter randomly under timecut. Photo/animation scenes would render correctly.

For projects that have NO embedded video clips (pure photo+animation+title slideshow), timecut should work out of the box. For projects with embedded video (the typical case), you need one of:

1. **Pre-extract source videos to PNG frame sequences**: `ffmpeg -i src.mp4 -r 30 frame_%05d.png`. Replace the `<VideoClip>` primitive with a component that picks the right PNG based on `localTime × fps`. ~30 min of work per video to set up; then timecut works perfectly. Audio still extracted separately and muxed in post.
2. **timesnap-core with experimental video preprocessor** (https://github.com/tungs/timesnap-core, sister project to timecut): does roughly #1 automatically. Less battle-tested; expect to debug.

Neither path has been validated on this pipeline yet. If the user is making N similar videos and the manual iMovie step is the bottleneck, this is the next thing to try.

**Recommended starting point**: build a small test composition with 3 photo blocks + 1 transition card (NO video clips), run it through timecut, confirm frame-perfect output. Then attempt the PNG-sequence VideoClip replacement on one source video. If both work, scale up.

## Maintenance note

When commercial tools change behavior (new Suno version, new Cmd+Shift+5 features, RunPod pricing changes, heartlib model updates), this phase needs updating. The other phases (B, C, D, E) are anchored on stable primitives (ffmpeg, Deepgram, vision LLMs, browser DOM) so they degrade gracefully. Phase G is where the user's actual choice of tool is most exposed.
