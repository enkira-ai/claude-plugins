# Phase C · Video Pipeline

Goal: take 5-10 raw embedded videos with mixed encoding/aspect/loudness, produce a uniform set ready for embedding, plus transcripts to inform storyboard.

## C.1 ffprobe inventory (~30 sec)

```bash
for f in <videos_folder>/*.{mp4,mov,MP4,MOV,m4v}; do
  [ -f "$f" ] || continue
  ffprobe -v error -print_format json -show_format -show_streams "$f" \
    | python3 -c "
import json, sys
d = json.load(sys.stdin)
v = next((s for s in d['streams'] if s['codec_type']=='video'), {})
a = next((s for s in d['streams'] if s['codec_type']=='audio'), {})
print(f'{sys.argv[1]:50s} {float(d[\"format\"][\"duration\"]):6.1f}s  {v.get(\"width\",\"?\")}x{v.get(\"height\",\"?\")} @ {v.get(\"r_frame_rate\",\"?\")}  {v.get(\"codec_name\",\"?\")} + {a.get(\"codec_name\",\"?\")}'
" "$f"
done
```

Aggregate into `videos_index.csv` with columns:
`file, role, duration_sec, width, height, fps, vcodec, acodec, vbitrate_kbps, abitrate_kbps, size_mb, normalized_path, audio_path, stt_path, summary`

`role` is your call: `opening-anchor`, `closing-anchor`, `middle`, `reference`.

## C.2 Normalize encoding (~2 min per video on M-series Mac)

Pick ONE reference video as the encoding baseline (usually the opening anchor or whatever's already in the target codec). Re-encode the rest to match.

```bash
mkdir -p <project>/videos
for src in <raw_videos>/*.{mp4,MP4,mov,MOV}; do
  [ -f "$src" ] || continue
  base=$(basename "$src")
  dst="<project>/videos/${base%.*}.mp4"
  # Skip the reference video — already encoded
  ffmpeg -y -i "$src" \
    -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1" \
    -r 30 \
    -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
    -c:a aac -b:a 192k -ar 48000 -ac 2 \
    -movflags +faststart \
    "$dst"
done
```

Result: all videos at 1920×1080, 30fps, H.264 CRF 20, AAC 192k, +faststart. Browser-friendly, mux-ready.

### Filename hygiene during this step

Rename `+` → `_` BEFORE this step. The `+` in `张智建+汪晨璐.mp4` causes URL-decoding issues in Phase E (browser interprets `+` as space). Do it once here:

```bash
for f in *+*.mp4; do mv "$f" "${f//+/_}"; done
```

## C.3 Extract audio + Deepgram STT (~30 sec per video)

```bash
mkdir -p <project>/audio_for_stt <project>/_stt
for f in <project>/videos/*.mp4; do
  base=$(basename "$f" .mp4)
  ffmpeg -y -i "$f" -vn -acodec libmp3lame -q:a 2 "<project>/audio_for_stt/${base}.mp3"
done

# Deepgram STT (Mandarin-friendly model — DO NOT use nova-3 multi)
DG_KEY=$(grep DEEPGRAM_API_KEY <user's .env path> | cut -d= -f2)
for f in <project>/audio_for_stt/*.mp3; do
  base=$(basename "$f" .mp3)
  curl -sS -X POST "https://api.deepgram.com/v1/listen?model=nova-2&language=zh-CN&smart_format=true&punctuate=true&utterances=true" \
    -H "Authorization: Token $DG_KEY" \
    -H "Content-Type: audio/mpeg" \
    --data-binary @"$f" \
    -o "<project>/_stt/${base}.json"
  # Extract plain transcript
  python3 -c "
import json
d = json.load(open('<project>/_stt/${base}.json'))
print(d['results']['channels'][0]['alternatives'][0]['transcript'])
" > "<project>/_stt/${base}.txt"
done
```

### CRITICAL: Deepgram model choice for Mandarin

- ✅ `nova-2 + language=zh-CN` works
- ❌ `nova-3 + language=multi` does NOT work for Mandarin — returns near-empty transcripts despite being newer

This was a real surprise; spend the first hour on a known-good model.

## C.4 Use STT to inform storyboard

Read each transcript. Look for:

- **Catchphrases that recur** across multiple contributors → potential motif (e.g., "我爱物理" appeared in 3 different videos in the example project)
- **Strong opening hooks** — finds the right candidate for `opening-anchor` (e.g., "我找到了 20 年前的笔记本，但密码忘了…" naturally opens the "unlock memories" arc)
- **Strong closing punches** — finds `closing-anchor` (e.g., "玩物理永远年轻")
- **Geographic references** for "ghost path" visualization (e.g., "I'm calling from Seattle" → city node in the post-grad evolution scene)

Add a 1-2 sentence Chinese summary to each row of `videos_index.csv`. Use Claude/GPT to summarize, not the user — they're busy.

## C.5 Optional: trim middle-segment videos by utterance timestamps

If a middle-segment video has 35s of content where 25s is meaningful and 10s is filler/repetition, you can trim. Deepgram returns word-level + utterance-level timestamps:

```python
import json
d = json.load(open('_stt/<file>.json'))
for u in d['results'].get('utterances', []):
    print(f'  [{u["start"]:6.2f}-{u["end"]:6.2f}] {u["transcript"]}')
```

Find the cut points where speech reaches a natural close, then ffmpeg trim with crossfade:

```bash
# Drop trailing humming/dead-air, fade out 0.6s
ffmpeg -y -i source.mp4 -t <cut_point_s> -af "afade=t=out:st=$((cut_point - 0.6)):d=0.6" -c:a libmp3lame -b:a 192k trimmed.mp4
```

But: **don't aggressively trim**. The user's contributors submitted these videos personally. A clean trim of trailing silence is fine. Cutting WORDS is risky — the user may have memories tied to specific phrases.

## Output of Phase C

- `<project>/videos/*.mp4` — uniform 1920×1080 H.264 AAC
- `videos_index.csv` — duration, codec, summary per video
- `<project>/_stt/*.{json,txt}` — full transcripts and word-level timestamps
- Recommendations for opening/closing anchor selection
