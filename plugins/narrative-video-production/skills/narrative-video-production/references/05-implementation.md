# Phase E · Implementation (in-browser composition)

The composition is a self-contained HTML page that renders a 6-7 minute slideshow with embedded videos and synced background audio. **Not Remotion** — a custom React/Babel-standalone framework, ~200 lines, all in the browser.

## Why this framework instead of Remotion

| Feature | This | Remotion |
|---------|------|----------|
| Setup | 0 (just html + jsx files) | npm install, node_modules |
| Live edit | refresh browser | hot reload |
| Render to mp4 | manual screen recording | programmatic |
| HTML5 video sync | native | Remotion has its own |
| Chinese fonts | system fonts via CSS | configurable |
| Suitable for: | personal videos, quick iteration | scaled production |

For a one-off reunion video where iteration speed matters more than render automation, this framework wins. For studios producing many similar videos, Remotion wins. The user's project goes one-off + reunion + emotional iteration → use this.

## Framework structure (animations.jsx, ~200 lines)

The framework provides:

- **`<Stage width height duration background autoplay persistKey>`** — top-level container with playback bar, timeline persistence (localStorage), keyboard scrubbing
- **`<Sprite start end>`** — time-windowed children. Children receive `localTime`, `progress`, `duration` via `useSprite()` hook
- **`useTimeline()`** — context with `time, duration, playing, setTime, setPlaying`
- **`Easing`** — popmotion-style easings (Cubic, Expo, Sine, Back, Elastic)
- **`interpolate(input, output, ease)`** — Popmotion-style multi-keyframe interpolation
- **`animate({from, to, start, end, ease})`** — single-segment tween

Don't reinvent these. Copy `templates/animations.jsx` into the project.

## Custom primitives (primitives_full.jsx)

Reusable visual building blocks. The the example project shipped:

| Primitive | Purpose |
|-----------|---------|
| `<PhotoBlock photos={[{src, dwell, kenBurns?, locBadge?}]} />` | Sequential photos with custom dwell, crossfade, Ken Burns. Handles globalFadeIn/Out for crossfading between scenes. |
| `<VideoClip src width height fillMode />` | HTML5 `<video>` synced to Stage timeline (drift correction). |
| `<TransitionCard zh formula formulaJsx en footnote />` | Centered chalk-style transition: idiom + formula + caption. |
| `<BlockTitle cn sub en />` | Top-corner block title (mono small caps EN + serif zh + italic sub). |
| `<LocationBadge text corner visibleFrom visibleTo />` | Brief place-name badge (e.g., "黄山") on a photo. |
| `<GhostPaths phase />` | SVG bezier curves for "evolution timeline" / map-like visualization. |
| `<GhostPhotoLayer photos windowStart windowEnd holdDur />` | Floating semi-transparent thumbnails (the "other particles" effect). |
| `<BackgroundBGM src volume />` | HTML5 `<audio>` synced to Stage timeline. **Pass `autoplay={false}` to Stage** so user gesture unlocks audio. |
| `<ChalkboardBg opacity />` | Chalkboard background texture |
| `<Vignette strength />` | Edge vignette |
| `<ChalkFormula text or children x y size />` | Chalk-style italic formula with reveal animation. Pass JSX children for proper `<sup>` typography. |

Copy `templates/primitives_full.jsx.template` and customize for the project.

## Scene structure (scenes_full.jsx)

Each scene is a React component returning a `<Sprite>`:

```jsx
function SceneBlock3Mountains() {
  const photos = flattenBlock('block3', subOrder, { dwell: 35.0 / 27 });
  return (
    <Sprite start={TF.block3Start} end={TF.block3End}>
      <PhotoBlock photos={photos} globalFadeOut={CF}/>
      <BlockTitle cn="三川五岳·游学四方"
                  sub="同一个 Ψ，不同的采样"
                  en="PATHS · INDEPENDENTLY · CHOSEN"
                  fadeOutDur={CF}/>
      <PersistentEntropyChalk/>  {/* the conserved-quantity motif */}
    </Sprite>
  );
}
```

The `flattenBlock(blockKey, subOrder, opts)` helper takes the auto-generated `PHOTOS` constant and emits a list of `{ src, dwell }` records. Scene composition becomes data-driven.

## Crossfade-by-extending-end pattern

To crossfade between scene N and scene N+1 by 0.4s:

- Scene N's Sprite `end = scene_N_logical_end + 0.4`
- Scene N+1's Sprite `start = scene_N_logical_end` (no overlap on N+1 side)
- Inside scene N's render, internally fade out the last 0.4s

In the TF helper:

```js
function add(name, dur) {
  t[name + 'Start'] = c;
  t[name + 'End'] = c + dur + CF;  // sprite mounted through crossfade tail
  c += dur;                         // cursor advances by logical dur only
}
```

Each scene component computes its own fade-out:

```jsx
const fadeOut = 1 - clamp((localTime - (duration - CF)) / CF, 0, 1);
```

## Path drawing (when needed for diagrams)

For the "不约而同" transition card showing path-family converging to classical path, use **SVG with pre-baked Bezier control points + stroke-dashoffset draw-on**, NOT feTurbulence (looks digital, not chalk):

```jsx
{candidates.map((p, i) => {
  const draw = Easing.easeOutCubic(clamp((localTime - 1.0 - i*0.15) / 0.7, 0, 1));
  const d = `M ${start.x} ${start.y} C ${p.c1[0]} ${p.c1[1]}, ${p.c2[0]} ${p.c2[1]}, ${end.x} ${end.y}`;
  return (
    <path d={d} pathLength="100"
          stroke={COLORS.chalkDim} strokeWidth="2"
          fill="none" strokeLinecap="round"
          style={{ strokeDasharray: 100, strokeDashoffset: 100 * (1 - draw) }}/>
  );
})}
```

Layer 2 strokes per path (a wider dusty + a narrower main) for chalk feel. Don't fully erase candidate paths — fade to ~22% opacity, leaving "ghosts" that visually echo when the next transition reuses the path metaphor.

This pattern was developed via agent-chat with Codex; transcript can be re-derived if needed.

## Composition entry HTML

```html
<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8"/>
<title>...</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;1,400;1,500&family=JetBrains+Mono:wght@400;500&family=Noto+Serif+SC:wght@400;500;600&display=swap" rel="stylesheet">
<style>html, body { margin: 0; padding: 0; height: 100%; background: #000; overflow: hidden; } #root { position: absolute; inset: 0; }</style>
</head>
<body>
<div id="root"></div>

<script src="https://unpkg.com/react@18.3.1/umd/react.development.js"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js"></script>
<script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js"></script>

<script type="text/babel" src="animations.jsx"></script>
<script type="text/babel" src="scenes/primitives.jsx"></script>
<script type="text/babel" src="scenes/primitives_full.jsx"></script>
<script type="text/babel" src="scenes/photos_data.js"></script>
<script type="text/babel" src="scenes/scenes_full.jsx"></script>

<script type="text/babel" data-presets="env,react">
  function VideoFull() {
    return (
      <Stage width={1920} height={1080} duration={TF.TOTAL}
             background={COLORS.bg} persistKey="myproject" autoplay={false}>
        <BackgroundBGM src="bgm/bgm.mp3" volume={0.55}/>
        <SceneTitleFull/>
        <SceneVideoOpen/>
        <SceneBlock1/>
        {/* ... etc ... */}
        <Vignette strength={0.55}/>
      </Stage>
    );
  }
  ReactDOM.createRoot(document.getElementById('root')).render(<VideoFull/>);
</script>
</body>
</html>
```

## Live preview

```bash
cd <project>/project
python3 serve.py 8000  # use scripts/serve.py — robust against BrokenPipeError
```

Then open `http://localhost:8000/reunion_full.html`. **Click Play** (Space won't unlock audio — only mouse click is a "user gesture" for some browsers).

## Common Phase E issues

### Audio doesn't play

Browser autoplay policy: `<audio>` must be triggered by a user gesture. The fix: pass `autoplay={false}` to Stage so initial state is paused, user clicks Play, useEffect reacts to `playing: true` and calls `audio.play()` within the gesture window. See `BackgroundBGM` primitive.

### Chinese filenames in URL

If filenames have `+`, browser/server may URL-decode it as space → 404. Rename `+` → `_` in the source files.

### Video lags / stutters

The `<video>` drift correction in `VideoClip` only re-seeks if drift > 0.4s. If video is consistently behind on slow systems, lower threshold to 0.2s. But more often, the issue is that browser is GPU-decoding too many video elements simultaneously — only ONE video should be visible (mounted via Sprite) at a time.

### Server crashes mid-recording

Use the bundled `serve.py` (in `scripts/`), not `python -m http.server`. The bundled version swallows BrokenPipeError that browsers throw when canceling range requests on large videos.

## Output of Phase E

A working browser preview at `http://localhost:8000/reunion_full.html` that:
- Plays end-to-end without gaps
- Shows BGM playing in sync
- Photo blocks at correct timing
- Videos embedded and playing with audio
- All transitions render
- ~6-7 min total

User should sign off on this BEFORE moving to Phase G (recording).
