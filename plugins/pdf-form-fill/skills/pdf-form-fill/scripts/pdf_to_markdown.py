"""Render a PDF as reading-order markdown with {{tag_N}} placeholders where
form widgets sit. The LLM reads the form as prose, fills placeholders by
content, then hands back a plan keyed by tag numbers.

Algorithm:
1. Collect all text spans AND widgets per page.
2. Group items by baseline (same row).
3. Within each row, sort by X.
4. Emit one markdown line per row: text spans plus {{tag_N}} placeholders
   at the right position.

Widget type is annotated inline so the LLM knows what kind of value to emit:
    {{21}}           — Text field (write a string)
    {{12:check}}     — CheckBox (write true or false)
    {{34:radio}}     — RadioButton (write true or false; siblings auto-Off)

Output: <name>.md (one file per PDF, pages separated by `---`).

Unlike label_map.py (which produces a widget-centric table), this is a
document-centric view. Use whichever fits the workflow — they're complementary.
"""
import argparse, os, re
import fitz  # pymupdf


_DOT_LEADER_RE = re.compile(r"^[\.\s·•]+$")


def _collect_items(page, baseline_tol: float = 1.5):
    """Return items (text spans + widgets) grouped into rows."""
    raw = []

    # Text spans, skip dot-leaders.
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text or _DOT_LEADER_RE.match(text):
                    continue
                bx = span.get("bbox", (0, 0, 0, 0))
                raw.append({
                    "kind": "text",
                    "text": text,
                    "bbox": bx,
                })

    # Widgets — keep the global counter consistent with annotate/label_map.
    # Caller passes `start_idx` so we know what N the first widget is.
    return raw


def _collect_all(doc):
    """Walk pages in order; assign widget tag numbers consistent with
    annotate_pdf_form.py / fill_pdf_form.py (1-based, document order)."""
    pages = []
    counter = 0
    for page in doc:
        items = _collect_items(page)
        # Add widgets with their running tag number.
        for w in (page.widgets() or []):
            counter += 1
            items.append({
                "kind": "widget",
                "tag": counter,
                "wtype": w.field_type_string,
                "bbox": tuple(w.rect),
            })
        pages.append(items)
    return pages


def _group_rows(items, baseline_tol: float = 2.5):
    """Sort items by baseline (y1), group rows, sort within row by x."""
    if not items:
        return []
    # Sort primarily by y1 (baseline). For widgets use the bbox center y.
    def baseline(it):
        _, _, _, y1 = it["bbox"]
        return y1
    items = sorted(items, key=lambda it: (baseline(it), it["bbox"][0]))
    rows = [[items[0]]]
    for it in items[1:]:
        if abs(baseline(it) - baseline(rows[-1][-1])) <= baseline_tol:
            rows[-1].append(it)
        else:
            rows.append([it])
    for r in rows:
        r.sort(key=lambda it: it["bbox"][0])
    return rows


WIDGET_SUFFIX = {
    "CheckBox": ":check",
    "RadioButton": ":radio",
    "Text": "",
    "ListBox": ":list",
    "ComboBox": ":combo",
}


def _render_row(row):
    """Render one row as a markdown string."""
    out = []
    for it in row:
        if it["kind"] == "text":
            out.append(it["text"])
        else:
            sfx = WIDGET_SUFFIX.get(it["wtype"], f":{it['wtype'].lower()}")
            out.append(f"{{{{{it['tag']}{sfx}}}}}")
    return " ".join(out)


def to_markdown(pdf_path: str, out_path: str):
    doc = fitz.open(pdf_path)
    pages = _collect_all(doc)
    lines_out = [f"# {os.path.basename(pdf_path)}\n"]
    for pg_idx, items in enumerate(pages):
        lines_out.append(f"\n## Page {pg_idx + 1}\n")
        for row in _group_rows(items):
            s = _render_row(row).strip()
            if s:
                lines_out.append(s)
        lines_out.append("")  # blank line between pages
        lines_out.append("---")
    doc.close()
    with open(out_path, "w") as f:
        f.write("\n".join(lines_out))
    print(f"Wrote {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", default=None,
                    help="Output .md path (default: <pdf_dir>/<name>.md)")
    args = ap.parse_args()
    if args.out:
        out = args.out
    else:
        base = os.path.splitext(os.path.basename(args.pdf))[0]
        out = os.path.join(os.path.dirname(os.path.abspath(args.pdf)),
                           f"{base}.md")
    to_markdown(args.pdf, out)


if __name__ == "__main__":
    main()
