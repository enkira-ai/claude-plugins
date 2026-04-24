---
name: pdf-form-fill
description: Use when the user asks to fill, review, or diff a PDF AcroForm (tax returns, government forms, insurance forms). Converts the form to reading-order markdown with {{tag_N}} placeholders, lets the LLM fill by reading prose, then writes tag-keyed values back into the PDF.
---

# PDF Form Fill

Fill AcroForm PDFs by reading them as prose with `{{tag_N}}` placeholders where the fields sit, filling by content, then writing values back.

## Why this shape

PDFs accept any string into a text widget — there is no type enforcement. The only ground truth for what a field means is the caption text next to it on the page. Instead of building a widget-centric table and asking the LLM to re-assemble the form mentally, we render the form AS prose (its natural form) and let the LLM fill inline. The `{{tag_N}}` placeholders preserve the mapping back to AcroForm widget indices.

## The rule that matters

**Fill by reading the caption in the markdown, not by memorizing tag numbers from prior sessions.** Forms change year over year; tag numbers shift. The placeholder pattern means values are bound to captions, not indices, in the LLM's reasoning — the script handles the index lookup.

## The pipeline

1. **Convert PDF → markdown with `{{tag_N}}` placeholders.**
2. **LLM reads markdown + user data → fills placeholders inline or emits a `{tag: value}` plan.**
3. **Dry-run the plan** against the PDF to catch unknown tags and type mismatches.
4. **Fill** the PDF.
5. **Verify** by re-rendering the filled PDF as markdown and reading back that values sit next to the right captions.

### Step 1 — Markdown with placeholders

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh \
    ${CLAUDE_PLUGIN_ROOT}/skills/pdf-form-fill/scripts/pdf_to_markdown.py \
    path/to/form.pdf --out ./form.md
```

Output looks like:

```
F Accounting method: (1) {{9:check}} Cash (2) {{10:check}} Accrual (3) {{11:check}} Other (specify) {{12}}
...
1 Gross receipts or sales. See instructions for line 1... {{21}}
2 Returns and allowances ........ 2 {{22}}
3 Subtract line 2 from line 1 .... 3 {{23}}
```

Widget types are inline in the placeholder so the LLM knows what value type to emit:
- `{{21}}` — Text field (string)
- `{{9:check}}` — CheckBox (true / false)
- `{{34:radio}}` — RadioButton (true / false; siblings auto-Off on fill)

### Step 2 — Fill the placeholders

Feed the markdown + user data (structured or natural-language) to the LLM. It outputs a plan JSON keyed by tag:

```json
{
  "_src": "form.pdf",
  "21": "13300",
  "22": "0",
  "23": "13300",
  "9": true,
  "10": false,
  "11": false
}
```

For radio groups: only set ONE member to `true`; the filler zeros the siblings automatically.

### Step 3 — Dry-run

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh \
    ${CLAUDE_PLUGIN_ROOT}/skills/pdf-form-fill/scripts/fill_pdf_form.py \
    path/to/form.pdf path/to/plan.json --dry-run
```

Buckets each entry as `SET_TEXT` / `CHECK_ON` / `CHECK_OFF` / `RADIO_ON` / `RADIO_OFF` / `UNKNOWN_IDX` / `TYPE_MISMATCH` / `BAD_KEY`. Exits non-zero on errors.

### Step 4 — Fill

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh \
    ${CLAUDE_PLUGIN_ROOT}/skills/pdf-form-fill/scripts/fill_pdf_form.py \
    path/to/form.pdf path/to/plan.json path/to/filled.pdf [--clear]
```

`--clear` wipes every widget before applying the plan.

### Step 5 — Verify

Regenerate the markdown from the filled PDF and read it back:

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh \
    ${CLAUDE_PLUGIN_ROOT}/skills/pdf-form-fill/scripts/pdf_to_markdown.py \
    path/to/filled.pdf --out ./filled.md
```

For filled forms, values appear inline where the placeholders were, so you can read top-to-bottom and confirm each line's value matches intent. For an extra safety pass, use `annotate_pdf_form.py` to produce a Set-of-Mark visual check (tags drawn inside each widget's top-left).

## Supplementary tools

These back up the markdown-first workflow when something goes wrong.

### `annotate_pdf_form.py` — visual check

Renders the PDF with numbered SoM overlays on each widget, tags printed INSIDE the widget's top-left (not floating above — that caused off-by-one confusion in earlier iterations).

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh \
    ${CLAUDE_PLUGIN_ROOT}/skills/pdf-form-fill/scripts/annotate_pdf_form.py \
    path/to/form.pdf --out-dir ./_annot/
```

Use when the markdown is confusing (e.g., dense grid forms where row grouping merges two visual rows that shouldn't be merged), or to spot-check a filled PDF visually.

### `widget_crop.py` — single-widget zoom

Renders a tight PNG around ONE widget + its caption. Exactly one numbered tag is drawn on the target — no overlap possible.

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh \
    ${CLAUDE_PLUGIN_ROOT}/skills/pdf-form-fill/scripts/widget_crop.py \
    path/to/form.pdf 184 185 186 --pad 80 --zoom 3
```

Use for formula rows where multiple values share a single line (e.g., `Line 42 = Line 40 × Line 41%`).

### `label_map.py` — widget → caption table (for automation)

Produces a deterministic table of (tag, caption, confidence) — useful for subagent pipelines where a cheaper model drafts the plan. Less LLM-native than the markdown view; prefer `pdf_to_markdown.py` for interactive use.

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh \
    ${CLAUDE_PLUGIN_ROOT}/skills/pdf-form-fill/scripts/label_map.py \
    path/to/form.pdf --out-dir ./_annot/
```

Emits `_labels.md` (table) and `_labels.json` (same data + an `ambiguous` array for widgets where both left and above captions score below threshold or are just `=` / `x` / etc.).

### `extract_plan.py` — reverse-engineer a fill

Dump an existing filled PDF's values as a plan. Useful for diffing hand-fill against Claude-fill, or for round-tripping last year's filing as a starting point.

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh \
    ${CLAUDE_PLUGIN_ROOT}/skills/pdf-form-fill/scripts/extract_plan.py \
    path/to/filled.pdf path/to/plan.json
```

## Delegating the mechanical steps

The markdown generation + parsing + draft-plan assembly is deterministic — good subagent work (Haiku handles it):

```
Agent({
  description: "Draft plan for <form>",
  subagent_type: "general-purpose",
  model: "haiku",
  prompt: """
    1. Run pdf_to_markdown.py on /abs/path/form.pdf → /abs/path/form.md
    2. Read form.md. For each {{tag_N}} placeholder, match the surrounding
       caption to the target values I've provided below and write a plan JSON
       entry keyed by the tag number.
    3. For placeholders where the markdown's linearization makes the caption
       unclear (e.g., merged rows in a multi-column grid), DO NOT guess —
       add them to an `_ambiguous` list. I'll resolve those with widget_crop.
    4. Return (a) the draft plan JSON and (b) the ambiguous list.

    Target values:
    <paste user-supplied data>
  """
})
```

Main agent then runs `widget_crop.py` on ambiguous tags, finalizes the plan, dry-runs, fills, and verifies.

## For truly messy forms: docling / alternative decompilers

`pdf_to_markdown.py` uses pymupdf's positional text + AcroForm widgets. For forms with heavy visual structure (nested tables, multi-column headers, merged cells) that pymupdf flattens poorly, consider these alternatives:

- **[docling](https://github.com/docling-project/docling)** — IBM's layout-aware PDF → markdown with ML models. Better table fidelity. Heavier dependency.
- **[pymupdf4llm](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/)** — pymupdf's own markdown converter. No extra deps. Decent for text-heavy forms.
- **[marker](https://github.com/VikParuchuri/marker)** — fast markdown from PDF.

None of these natively splice widget placeholders in. The pattern is: (1) run the converter to get structured markdown, (2) get widget bboxes from pymupdf, (3) insert `{{tag_N}}` placeholders at the right offsets. If you need this, adapt `pdf_to_markdown.py` — swap the text collection step for the external tool's output.

## Red flags — stop and verify

| Situation | What to do |
|---|---|
| A `{{tag_N}}` in the markdown isn't on the expected row | Row-grouping merged two baselines. Use `widget_crop.py` on the tag. |
| Dry-run reports `UNKNOWN_IDX` | Form changed since plan was written — regenerate markdown, update tags |
| Dry-run reports `TYPE_MISMATCH` | Plan has bool where widget is Text, or vice versa. The `:check` / `:radio` suffix in the markdown prevents this if the LLM respects it |
| Radio group looks half-checked after fill | Normal — filler uses direct xref writes; re-render filled markdown to verify |
| Checkbox "on state" is unexpected | pymupdf `on_state()` varies per widget; filler auto-detects per widget |

## Gotchas

- **Radio groups**: pymupdf's `widget.field_value = "Off"` only updates the active widget — sibling `/AS` entries stay on. Our filler writes `/AS /Off` directly via `doc.xref_set_key` for every sibling.
- **Checkbox on-state**: not always `"Yes"`. Some forms use `"1"`, `"On"`, or a unique per-widget state. Filler auto-detects via `widget.on_state()`.
- **Dot leaders**: IRS forms pad captions with ".............." — the markdown converter filters these out, so they won't corrupt the reading-order.
- **Multi-column grids**: Schedule C expense section has columns A and B on the same baseline. `pdf_to_markdown.py` merges them into one line: `8 Advertising . 8 {{28}} 0 18 Office expense (see instructions) . 18 {{39}} 0`. That's correct layout-wise, but if it's hard to read, fall back to `annotate_pdf_form.py` + `widget_crop.py`.
- **AcroForm preservation**: don't flatten the output PDF unless you have to — flattening bakes values as graphic content and loses the fillable structure.

## File layout convention

```
form.pdf                     # source blank (or last-year's filled) form
form.md                      # markdown with {{tag_N}} placeholders
plan.json                    # your fill plan (tag → value)
filled.pdf                   # output
_annot/form_page{N}.png      # optional visual check (SoM overlay)
_annot/form_labels.md        # optional widget↔caption table
filled.md                    # verification: filled PDF re-rendered as markdown
```

Keep `plan.json` under version control — it's the portable artifact. The filled PDF can be regenerated anytime.
