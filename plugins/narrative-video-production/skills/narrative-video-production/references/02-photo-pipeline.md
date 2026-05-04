# Phase B · Photo Pipeline

Goal: from N raw photos to a curated set organized by storyboard block, with hash-based provenance that survives renames/moves.

## B.1 Generate thumbnails (~5 min for 200 photos)

Resize all photos to long-edge ≤ 512px for cheap multimodal LLM consumption. Originals untouched.

```bash
cd <project_root>
mkdir -p _thumbs
find <photo_folders...> -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.heic" \) > /tmp/photo_list.txt
while IFS= read -r f; do
  outdir="_thumbs/$(dirname "$f")"
  mkdir -p "$outdir"
  out="_thumbs/${f%.*}.jpg"
  [ -f "$out" ] || sips -Z 512 -s format jpeg -s formatOptions 70 "$f" --out "$out" >/dev/null 2>&1
done < /tmp/photo_list.txt
```

Expect ~10MB total for 200 photos.

## B.2 Tag via parallel Haiku subagents (~5 min for 200 photos)

This is the **key automation move**. Don't tag photos one at a time, don't use external API. Dispatch ~10 Haiku subagents in parallel, each handling ~20 photos.

### Split into batches

```bash
split -l 20 /tmp/photo_list.txt /tmp/photo_batch_
mkdir -p _tags
```

### Dispatch (one Agent call per batch, all in parallel — single message, multiple Agent tool uses)

For each batch, spawn `Agent(subagent_type=general-purpose, model=haiku)` with this prompt template:

```
You are tagging photos for a [PROJECT-DESCRIPTION] video project.

Working directory: `<absolute path with proper quoting>`

Your batch list is at `/tmp/photo_batch_aa` — each line is a relative path
to an original photo.

For EACH photo in the batch:
1. Compute thumbnail path: prefix with `_thumbs/`, replace ext with `.jpg`.
2. Use the Read tool with absolute path to view the image.
3. Emit ONE JSON object on ONE line (JSONL) with these fields:
   - filename: original relative path (exactly as in batch list)
   - era: <user-defined eras, e.g. "在校"/"毕业后">
   - scene: one of [<user-defined scene tags>]
   - people_count: integer
   - mood: one of [合影正式, 抓拍, 风景, 纪念物, 单人]
   - quality: 1-5 (composition + clarity, 5 best)
   - caption_zh: ≤20 字 short description
   - dedup_key: short tag for similarity grouping
   - notes: optional

Write JSONL output to `<workdir>/_tags/batch_aa.jsonl`.

Return a concise summary: how many processed, any read failures.
```

Customize `era`, `scene` enums for the specific project. Stay disciplined: short, fixed-vocab tags so the consolidation step is clean.

### Consolidate

```python
# scripts/consolidate_tags.py (see scripts/ folder)
import json, csv, glob

rows = []
for f in sorted(glob.glob('_tags/batch_*.jsonl')):
    for line in open(f, encoding='utf-8'):
        line = line.strip()
        if line:
            rows.append(json.loads(line))

cols = ['filename','era','scene','people_count','mood','quality','caption_zh','dedup_key','notes']
with open('photos_index.csv','w',newline='',encoding='utf-8') as out:
    w = csv.DictWriter(out, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c,'') for c in cols})
```

You now have `photos_index.csv` — one row per photo with structured tags.

## B.3 Add `category` super-column (~storyboard mapping)

Map each photo to a macro category that maps to storyboard blocks. Domain-specific — write a Python `categorize(row)` function with priority rules:

```python
def categorize(r):
    f, era, scene, dk, cap = r['filename'], r['era'], r['scene'], r['dedup_key'], r['caption_zh']
    # Priority rules (most specific first):
    if '<specific_folder>' in f: return '11-海门实习'  # path-based
    if scene == '山岳' or '<keyword>' in f: return '12-不言自合·群山行'
    # ... etc
    return '99-杂项'
```

Then `include` flag — drop low quality:

```python
for r in rows:
    r['include'] = '0' if int(r['quality']) <= 2 else '1'
```

## B.4 Curate folder structure (~30 min Claude + 30-90 min user)

Build `_curated/<block>/<sub>/` folders, copying (not symlinking) photos with **renamed** filenames that encode the slide title:

```python
new_name = f"{slide_title}_{i:02d}{ext}"
shutil.copy2(src, dst)
```

The user's job: open `_curated/` in Finder, **delete unwanted photos**, **drag photos between subfolders** if categorization was off. They may also rename folders to reflect what the slide title will say.

### Hash-link tracking

Once user starts moving/renaming, filename mapping breaks. Generate `_hashlink.csv` BEFORE user starts pruning, then regenerate AFTER for verification:

```python
import hashlib, os, csv

def md5_file(p, bs=65536):
    h = hashlib.md5()
    with open(p,'rb') as f:
        while chunk := f.read(bs): h.update(chunk)
    return h.hexdigest()

# Hash all originals
orig_hash = {md5_file(p): p for p in iter_files('在校时','毕业后')}

# Hash all curated, link back
links = []
for cur in iter_files('_curated'):
    h = md5_file(cur)
    orig = orig_hash.get(h, '')
    links.append({'current_path': cur, 'original_path': orig, ...})
```

This means even if user renamed `寝室回响_03.jpg` → `当年的笔记本.jpg`, you can still recover their tags via hash.

## B.5 Generate JS constants for browser composition

The browser composition needs photo paths as JS constants. Auto-generate from filesystem so it's always in sync:

```python
# scripts/photos_data_gen.py (see scripts/ folder)
# Outputs project/scenes/photos_data.js with PHOTOS = { block1: { sub: [...], ... }, block2: ... }
```

Re-run this whenever the user moves/renames in `_curated/`.

## Pitfalls

### Case-sensitivity in extensions

Haiku subagents may emit `*.jpg` lowercase even though source is `*.JPG`. When cross-referencing later, use case-insensitive lookup:

```python
meta = {r['filename'].lower(): r for r in rows}
match = meta.get(orig_path.lower(), {})
```

### Filename gotchas

- `+` in filenames breaks URL routing later (Phase E). Rename `+` → `_` BEFORE phase E.
- Trailing space in path crashes various tools. Rename early.
- Chinese characters are fine but watch shell quoting in scripts.

### "黄山只有 2 张" — sub-categorization is unreliable

The vision LLM is fine at general scene tagging but not great at distinguishing specific landmarks. If you need fine-grained location ID (which mountain? which campus building?), accept that it'll be ~50% accurate and let the user fix manually. Don't try to engineer prompt-level rescue.

### Don't let the LLM identify people

Vision LLMs cannot reliably identify specific individuals in speaker photos. Do not prompt for person identification — you'll get hallucinated names. Have the user do this manually in Finder during curation.

## Output of Phase B

- `photos_index.csv` (~200 rows, all tagged)
- `_curated/<block>/<sub>/<title>_NN.jpg` (curated, user-pruned)
- `_curated/_hashlink.csv` (provenance map)
- `project/scenes/photos_data.js` (auto-generated)
