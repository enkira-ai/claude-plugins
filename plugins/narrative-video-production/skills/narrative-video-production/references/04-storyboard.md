# Phase D · Storyboard Design

This is where the project lives or dies. Technical excellence elsewhere can't save a flat narrative.

## What a storyboard delivers

By the end of this phase you should have, locked in `progress.md`:

1. A **timeline** — every scene with start time, duration, and what it is (photo block, video clip, transition card, title)
2. A **theme/spine** — the overarching idea the video is "about"
3. A **block-level content map** — which photos/videos go where, what title text appears
4. A **motif** — a phrase, image, or sound that recurs and gives the video unity
5. **Decision discipline** — once locked, don't reopen unless the user explicitly does. Late storyboard changes cascade through Phase E.

## The 3-act spine that usually works

Most narrative videos benefit from a 3-act structure, even when the subject seems "flat" (like a year-in-review). Three acts give the user a sense of arrival rather than a list:

```
Act 1 · Setup / Origin              — where it started, the shared baseline
   |
   v
Act 2 · Body / Variation / Tension  — what happened, the change/divergence/conflict
   |
   v
Act 3 · Resolution / Reunion        — where it lands, the synthesis or arrival
```

Act 2 is usually the longest (50-60% of runtime). Act 1 establishes; Act 3 doesn't need to be long, just decisive.

Examples by project type:

| Project | Act 1 | Act 2 | Act 3 |
|---------|-------|-------|-------|
| Class reunion | Together in school | Each scattered after | Reconvened today |
| Wedding | How they met | The relationship's growth | The wedding day |
| Year-in-review (org) | Where we started Jan | What we built | Where we are now |
| Memorial | Early life | Their work and impact | What they leave behind |
| Project retrospective | Founding insight | Iteration / setbacks / wins | What it became |
| Hackathon recap | The kickoff | Building over the weekend | The demos |
| Course summary | First class | The work / projects | Final showcase |

The user usually has a fuzzy sense of these three acts. Your job in storyboard design is to **make them concrete** — minutes, photos, words.

## Block timing template (works for 5-7 min target)

Adapt these durations:

```
0:00  Title card (2-3s)
0:03  Anchor element / opening (10-15s — could be a video, a photo with title, or quote)
0:15  Transition card / theme statement (3-5s)
0:20  Major opening element — strongest video/photo to set the tone (40-90s)
1:30  Photo Block 1 — short montage of foundational images (12-20s)
1:50  Middle clip — short embedded video or quote (15-25s)
2:15  Photo Block 2 — bigger montage (25-35s)
2:50  Middle clip (25-30s)
3:20  Transition card (idiom + concept) (3-5s)
3:25  Photo Block 3 — emotional peak / chorus (30-40s)
4:05  Middle clip (30-40s)
4:45  Photo Block 4 — grounding / context (25-30s)
5:15  Middle clip (30-50s)
6:05  Transition card (3-5s)
6:10  Closing element — strongest punch / final word (25-35s)
6:45  Outro card with credits / motif phrase (5-8s)
```

Total ~6:50. Adjust ±30s based on user's preferred pacing. Move blocks around to fit content; the structure (alternating photo blocks ↔ middle clips, with 2-3 transition cards) is the durable pattern.

## The "TF anchor" pattern

In code, define every scene's start/end as a single object so reordering is trivial:

```js
const TF = (() => {
  const t = {};
  let c = 0;
  function add(name, dur) {
    t[name + 'Start'] = c;
    t[name + 'End']   = c + dur + CF; // CF = crossfade overlap with next
    c += dur;
  }
  add('title', 2.5);
  add('anchor1', 9.92);
  add('transOpen', 5.0);
  add('open', 71.87);
  add('block1', 14.0);
  // ... etc
  t.TOTAL = c;
  return t;
})();
```

Now `TF.block3Start` is the right offset for everything: scenes_full.jsx visibility window, mux_recorded.sh speech offsets, JSON metadata. Single source of truth for timing.

## Pacing curves matter

Don't give every photo equal dwell time. Design intentional pacing per block. Examples:

### "Memory unlock" curve (good for Act 1 introductions)

```
Block of N photos in T seconds:
   └─ photo 1:    ~2.5s  (long hold — the trigger / anchor image)
   └─ photo 2-4:  ~0.18s × 3 (fast flicker — fragments)
   └─ photo 5-N-1: 0.30s → 1.0s decelerating (slowing into focus)
   └─ photo N:    ~2.0s  (long hold on the foundational image)
```

Tells a story: "memory unlocks → chaotic → settles to source moment". Powerful for opening montages.

### "Gathering momentum" curve (good for Act 2 build-ups)

```
   └─ photo 1: 1.5s
   └─ photo 2-N: 1.0s → 0.5s accelerating
   └─ ends with rapid 4-5 frame burst into next scene
```

Tells: "calm → speeding up → tipping into next thing". Good before transition cards.

### "Even ritualistic" curve (good for "year-by-year" sequences)

```
   └─ all N photos: equal dwell ≈ T/N
   └─ each labeled with year/date/place
```

Tells: "evenly spaced events". Boring on its own; combine with on-screen year labels for clarity.

## Theme / metaphor (optional but elevating)

A thematic frame elevates a slideshow into a meaningful video. The user should drive this — your job is to suggest options and support whatever they pick. Some patterns:

| Theme type | Examples | When it works |
|-----------|----------|---------------|
| **Geographic** | "from this room to the world", tributaries, ghost paths to cities | When subjects live/dispersed across places |
| **Temporal** | seasons, years, "from then to now" | When time is the through-line |
| **Physical / scientific** | quantum entanglement, entropy, evolution, paths converging | When the user has a science background |
| **Musical** | phrases as chapters, key changes as act transitions | When music is central anyway |
| **Architectural** | the room they shared, the building, layers of foundation | When a place is meaningful |
| **Botanical / cyclical** | seed → tree, river → sea, bloom cycles | For organic / generational stories |
| **Literary** | a quote that recurs, a poem broken into lines | When the user is writerly |

Don't impose a theme. Ask: "what's the through-line for you?" and let them describe. Then offer a metaphor that fits, not one that's clever.

### Idiom / quote pairing for transition cards

If you've found a theme, transition cards become powerful: a 3-5s card with one phrase that crystallizes the moment. This works in any language. Examples:

- "from many, one" between Act 2 and Act 3
- "what we built / what built us" between sections
- 一句话 / one line / un mot — the user's chosen phrase
- A formula or symbol if the user has a technical background

The card should be **one beat**: either a phrase OR a formula OR a date OR a name. Not all three. Less crowded = more poetic.

### Make any technical content legible

If the theme involves formulas, symbols, or domain jargon, **rewrite for legibility**. Generic notation feels like an exam; named/contextual notation feels like a story. Example transformation:

```
⟨f|i⟩ = ∫𝒟x · e^(iS/ℏ)        ← opaque
                                ↓
⟨2026 reunion | 2002 NJU⟩ = Σ paths · e^(iS/ℏ)   ← reads as story
```

Anyone can read the second left-to-right as "from 2002 NJU to 2026 reunion, sum over all paths". Add a small footnote demystifying any remaining symbol.

The same principle applies in any domain: name your variables with story-words, not generic letters.

## Block titles use a 3-line pattern (when a block needs a title)

Top of screen during each photo block:

```
[mono small caps small]    SUBTITLE / SECTION TAG / DATE
[serif main big]           THE BLOCK'S NAME (in primary language)
[serif italic medium]      a deeper concept or translation
```

The first line is a stylistic cap that scans like a chapter heading. The second is the immediate description. The third is the deeper reading or alternate-language translation. Bilingual works well even for monolingual audiences — adds gravity.

Not every block needs a title. Photo blocks that are purely visual rhythm (e.g., a fast Act 2 montage) can run without text.

## Picking the conserved quantity / motif

The single phrase, image, or sound that recurs throughout. Should:

- Be **short** (3-4 syllables / 1-3 words)
- Express something the user feels deeply
- Land naturally in the closer (last 8s of the video)
- Ideally already exist somewhere in the source material (you'll catch this in Phase C STT scan)

Once chosen, weave references into:

- Title scene (subtle setup — small text, not the centerpiece)
- A persistent on-screen visual (small text in a corner, or a recurring graphic)
- The final transition card (just before the closing anchor)
- The outro (the payoff — full size, clearly read)

A motif done right makes the video feel inevitable rather than constructed.

## Output of Phase D

Update `progress.md` with the locked storyboard:

```markdown
## Phase D · Storyboard (LOCKED)

| Time | Scene | Duration | Title | Notes |
|------|-------|----------|-------|-------|
| 0:00 | Title | 2.5s | "<title>" | |
| 0:03 | Anchor | 9.9s | (intro from <person>) | |
| 0:13 | Transition | 5s | <theme tagline> | |
| 0:18 | OPEN video | 72s | (<source>) | |
| ... | ... | ... | ... | ... |

Theme: <one-sentence frame>
Motif: <the recurring phrase / symbol>
Total: ~6:50
```

Lock these decisions before starting Phase E. Changing duration mid-Phase E means recomputing TF and adjusting every scene.
