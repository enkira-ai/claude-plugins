# Phase F · BGM Generation

This is the trickiest phase. Music quality matters disproportionately to perceived video quality, but generation tools are inconsistent.

## The recommended structure

For a 6-7 min video:

```
3 instrumental beds (Suno or MiniMax Music) ≈ 7 min total, crossfaded
   ├─ Bed A · 回忆      ~3 min, warm nostalgic piano + strings
   ├─ Bed B · 高潮      ~2:30, building emotional, brass swell
   └─ Bed C · 内省      ~1:30, ambient pad, contemplative outro
```

Crossfade points placed UNDER talking-head segments so the bed transition is masked by speech.

**Vocals are optional**. The the example project tried adding 4 short vocal segments via heartlib, but the user judged the heartlib vocal style didn't match the Suno bed style cleanly. Final video shipped with bed-only. Don't promise vocals; treat them as nice-to-have.

## Tool choice (in 2026)

| Tool | Pros | Cons | Best for |
|------|------|------|----------|
| **Suno** (web) | True instrumental toggle, one-click generate, ~3 min/track | Generic if prompt is vague | **Bed generation** ✓ |
| **MiniMax Music** | Chinese-friendly prompts, similar quality | Less "instrumental" reliability | Bed generation alt |
| **HeartMuLa (heartlib)** | Open-source, runs on RunPod | **No real instrumental mode**, vocals leak even with `<||>` hack | Vocal generation if you want Chinese folk style |
| **AudioCraft / MusicGen** | Open-source, instrumental-friendly | Lower fidelity | Free fallback |

### Suno bed prompt template

```
Style (text):
warm nostalgic instrumental, solo piano with soft strings underscore,
slow contemplative ballad, cinematic memoir score, no vocals,
A minor, 70 BPM, like Joe Hisaishi or Max Richter

Lyrics: leave blank, toggle "Instrumental" ON
```

Variations per bed (recall 8-pillar tag taxonomy from heartlib's TAGS_GUIDE):

- Bed A (warm nostalgic): Folk/Score, Solo Piano, Female (vocal-ref though no vocal generated), Melancholic, Warm, Cinematic, Memory, Acoustic
- Bed B (building emotional): Score, Piano + Strings + Brass, Emotional, Building, Cinematic
- Bed C (ambient outro): Ambient, Solo Piano, Quiet, Contemplative, Outro, Instrumental

## heartlib (HeartMuLa) — when you want Chinese vocals

Use only for **short vocal segments** (per photo block, 25-35s each), NOT for beds. Run on RunPod A40 (~$0.35/hr, ~25 min total).

### Setup script

`scripts/runpod_heartlib_setup.sh` documented:

```bash
git clone https://github.com/HeartMuLa/heartlib.git
cd heartlib
pip install -e .
pip install 'huggingface_hub<1.0' hf_transfer  # important: the ==1.13 version breaks transformers
export HF_HUB_ENABLE_HF_TRANSFER=1
mkdir -p ckpt
hf download --local-dir ./ckpt 'HeartMuLa/HeartMuLaGen'
hf download --local-dir ./ckpt/HeartMuLa-oss-3B 'HeartMuLa/HeartMuLa-oss-3B-happy-new-year'
hf download --local-dir ./ckpt/HeartCodec-oss 'HeartMuLa/HeartCodec-oss-20260123'
```

Total ~7 GB download, ~5 min on RunPod fast networking.

### heartlib lyrics format

Section markers `[Verse]`, `[Chorus]`, `[Bridge]`, `[Intro]`, `[Outro]` are recognized tokens.

**Number of section markers ≈ generation length**. With 4 markers you get ~1 minute. With 7+ markers you get 3 minutes. Don't ask for 5-min single track from a model trained on 3-min songs — split into pieces.

**Tags follow 8 categories** (see heartlib PR #91 TAGS_GUIDE.md). Pick ONE per category to avoid conflict. For Chinese vocal:
```
Folk, Piano, Female, Melancholic, Warm, Cinematic, Memory, Acoustic
```

### heartlib gotchas

1. **Pure instrumental is unreliable**. Issue #16 documents the workarounds; even with `<||>` placeholders + RL model variant, vocals still leak. Use Suno for instrumentals.
2. **Mac M-series (MPS) ≈ 3-5x slower than 4090**. Use cloud GPU.
3. **Empty section markers may produce 17s of audio, not 3 min**. Use the same lyric-structure pattern as your "real" track even when empty: `[Intro] / [Verse] / [Chorus] / [Bridge] / [Verse] / [Chorus] / [Outro]`.
4. **Generate without expecting precise length control**. Let the model decide; trim with ffmpeg afterward.

### Vocal trim by Deepgram STT

Heartlib vocals often sing the lyrics in the first 30s and then drift into humming/repeats. Trim to the last clear word using Deepgram timestamps:

```bash
# Get utterance timestamps
DG=$(grep DEEPGRAM_API_KEY .env | cut -d= -f2)
curl -sS -X POST "https://api.deepgram.com/v1/listen?model=nova-2&language=zh-CN&utterances=true" \
  -H "Authorization: Token $DG" -H "Content-Type: audio/mpeg" \
  --data-binary @"vocal.mp3" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for u in d['results'].get('utterances', []):
    print(f'  [{u[\"start\"]:6.2f}-{u[\"end\"]:6.2f}] {u[\"transcript\"]}')
"

# Identify last clear utterance, then ffmpeg trim
ffmpeg -y -i vocal.mp3 -t <cut_sec> -af "afade=t=out:st=$((cut_sec - 0.6)):d=0.6" -c:a libmp3lame -b:a 192k vocal_clean.mp3
```

## RunPod recipe (full pod lifecycle, ~$0.07-0.20)

```bash
# Get API key (assume in user's .env or ask)
KEY=$(grep RUNPOD_APIKEY .env | cut -d= -f2)

# Upload your SSH pub key to RunPod account (one-time)
PUBKEY=$(cat ~/.ssh/id_ed25519.pub | sed 's/"/\\"/g')
curl -sS -X POST "https://api.runpod.io/graphql?api_key=$KEY" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"mutation { updateUserSettings(input: { pubKey: \\\"$PUBKEY\\\" }) { id } }\"}"

# Create A40 pod with PUBLIC_KEY env (DO NOT override dockerArgs — image entrypoint uses it for SSH config)
cat > /tmp/create.json <<JSON
{
  "query": "mutation CreatePod(\$pk: String!) { podFindAndDeployOnDemand(input: { cloudType: ALL gpuCount: 1 volumeInGb: 0 containerDiskInGb: 50 minVcpuCount: 8 minMemoryInGb: 32 gpuTypeId: \"NVIDIA A40\" name: \"heartlib\" imageName: \"runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04\" dockerArgs: \"\" ports: \"22/tcp\" volumeMountPath: \"/workspace\" env: [{key: \"PUBLIC_KEY\", value: \$pk}] }) { id desiredStatus } }",
  "variables": { "pk": "$PUBKEY" }
}
JSON
PID=$(curl -sS -X POST "https://api.runpod.io/graphql?api_key=$KEY" -H "Content-Type: application/json" -d @/tmp/create.json | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['podFindAndDeployOnDemand']['id'])")

# Poll for SSH ready (~30-50s)
for i in $(seq 1 15); do
  sleep 8
  RES=$(curl -sS -X POST "https://api.runpod.io/graphql?api_key=$KEY" -H "Content-Type: application/json" -d "{\"query\":\"query { pod(input:{podId:\\\"$PID\\\"}) { runtime { ports { ip publicPort privatePort isIpPublic } uptimeInSeconds } } }\"}")
  HOSTPORT=$(echo $RES | python3 -c "import json,sys; d=json.load(sys.stdin); rt=d['data']['pod']['runtime']; ports=rt['ports'] if rt else []; ssh=[p for p in ports if p['privatePort']==22 and p['isIpPublic']]; print(ssh[0]['ip']+':'+str(ssh[0]['publicPort'])) if ssh else print('')")
  [ -n "$HOSTPORT" ] && ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -p ${HOSTPORT#*:} root@${HOSTPORT%:*} "echo OK" 2>/dev/null && break
done

# scp lyrics/tags up, run setup script, run generations, scp results back
scp -P ${HOSTPORT#*:} *.txt root@${HOSTPORT%:*}:/tmp/
ssh -p ${HOSTPORT#*:} root@${HOSTPORT%:*} "bash /tmp/setup_v3.sh && python3 ./examples/run_music_generation.py --model_path=./ckpt --version='3B' --lyrics ... --tags ... --save_path ... --max_audio_length_ms 240000"
scp -P ${HOSTPORT#*:} root@${HOSTPORT%:*}:/workspace/heartlib/out/*.mp3 ./bgm/

# Terminate pod
curl -sS -X POST "https://api.runpod.io/graphql?api_key=$KEY" -H "Content-Type: application/json" \
  -d "{\"query\":\"mutation { podTerminate(input:{podId:\\\"$PID\\\"}) }\"}"
```

A40 vs RTX 4090: A40 has 48 GB VRAM (overkill, but always available). 4090 is faster for transformer inference but harder to find. Default to A40.

## Final BGM mix

Combine 3 beds (and optional vocals) into one master:

```bash
# crossfade 3 beds with speech-segment-masked transitions
ffmpeg -y -i bed1.mp3 -i bed2.mp3 -i bed3.mp3 \
  -filter_complex "
    [0:a]atrim=0:166,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=2[a1];
    [1:a]atrim=0:155,asetpts=PTS-STARTPTS[a2];
    [2:a]atrim=0:103,asetpts=PTS-STARTPTS,afade=t=out:st=98:d=5[a3];
    [a1][a2]acrossfade=d=8:c1=tri:c2=tri[ab];
    [ab][a3]acrossfade=d=8:c1=tri:c2=tri[bed]
  " -map "[bed]" \
  -c:a libmp3lame -b:a 192k bgm/bed_continuous.mp3
```

Place crossfade midpoints UNDER talking-head segments so speech audio masks the transition.

## .env safety

If user's API keys (Deepgram, RunPod) are in a `.env` file, **NEVER commit it to git**. Add to `.gitignore` BEFORE first commit. If accidentally committed, run:

```bash
git rm --cached .env
echo .env >> .gitignore
git commit -am "Untrack .env"
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

And remind user to revoke + rotate the key.

## Output of Phase F

- `bgm/bed_continuous.mp3` — single-file 6:30-7:00 master BGM
- (optional) `bgm/v1.mp3 ... v4.mp3` — short vocal segments
- `BGM_PROMPT.md` — record of prompts used (so user can iterate)
