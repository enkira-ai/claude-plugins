"""Render a PDF's AcroForm widgets as Set-of-Mark annotated PNGs + JSON sidecar.

Label placement heuristic (addresses off-by-one confusion in dense forms):
- Default: place tag INSIDE the widget at top-left. Keeps label visually attached
  to its own widget even when rows are packed — no accidental visual migration
  to the widget above.
- Fallback: if the widget is too small to hold the tag inside, place it to the
  RIGHT of the widget (not above), so it never collides with the row above.
- Collision check: if two tags would overlap, successive tags are nudged down
  slightly.

Outputs (next to input by default):
    <name>_page1.png, <name>_page2.png, ...    # rendered page + numbered overlays
    <name>_fields.json                         # {index: {field, type, value, rect, page}}

Text fields = red, checkboxes = blue, radio = orange, other = green.
"""
import argparse, json, os
import fitz  # pymupdf

COLOR = {
    "Text": (0.85, 0.1, 0.1),
    "CheckBox": (0.1, 0.3, 0.85),
    "RadioButton": (0.95, 0.55, 0.1),
}
DEFAULT_COLOR = (0.1, 0.7, 0.2)


def _tag_rect(widget_rect: fitz.Rect, label: str) -> fitz.Rect:
    """Compute tag placement: inside top-left if room, else to the right."""
    fsize = 8.0
    tag_h = 10.0
    tag_w = 6 + len(label) * 5.0

    # Place inside top-left of widget when widget is tall/wide enough.
    if widget_rect.height >= tag_h + 1 and widget_rect.width >= tag_w + 1:
        return fitz.Rect(
            widget_rect.x0,
            widget_rect.y0,
            widget_rect.x0 + tag_w,
            widget_rect.y0 + tag_h,
        )
    # Fallback: to the right of the widget (stays on the same row).
    return fitz.Rect(
        widget_rect.x1,
        widget_rect.y0,
        widget_rect.x1 + tag_w,
        widget_rect.y0 + tag_h,
    )


def annotate(pdf_path: str, out_dir: str, zoom: float = 2.0):
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(pdf_path))[0]
    src = fitz.open(pdf_path)

    overlay = fitz.open()
    for pg in src:
        overlay.insert_pdf(src, from_page=pg.number, to_page=pg.number)

    index = {}
    counter = 0
    # Per-page list of placed tag rects for collision nudging.
    placed_by_page: dict[int, list[fitz.Rect]] = {i: [] for i in range(src.page_count)}

    for pg_idx, page in enumerate(overlay):
        src_page = src[pg_idx]
        widgets = list(src_page.widgets() or [])
        for w in widgets:
            counter += 1
            rect = fitz.Rect(w.rect)
            color = COLOR.get(w.field_type_string, DEFAULT_COLOR)
            filled = w.field_value not in (None, "", False, "Off")
            width = 1.5 if filled else 0.7
            page.draw_rect(rect, color=color, width=width)

            label = str(counter)
            tag = _tag_rect(rect, label)

            # Nudge down if this tag would overlap an already-placed one.
            for _ in range(6):
                collides = any(tag.intersects(t) for t in placed_by_page[pg_idx])
                if not collides:
                    break
                tag = tag + (0, 2, 0, 2)

            placed_by_page[pg_idx].append(tag)

            page.draw_rect(tag, color=color, fill=color, width=0)
            page.insert_text(
                (tag.x0 + 1.5, tag.y1 - 2.2),
                label,
                fontsize=8.0,
                color=(1, 1, 1),
                fontname="helv",
            )

            short_last = w.field_name.split(".")[-1]
            short = short_last.split("[")[0] + (
                "" if "[" not in short_last else "." + short_last.rsplit("[", 1)[1].rstrip("]")
            )
            index[counter] = {
                "field": w.field_name,
                "short": short,
                "type": w.field_type_string,
                "value": w.field_value,
                "rect": [round(c, 2) for c in rect],
                "page": pg_idx + 1,
            }

    mat = fitz.Matrix(zoom, zoom)
    page_pngs = []
    for pg_idx, page in enumerate(overlay):
        pix = page.get_pixmap(matrix=mat, alpha=False)
        out = os.path.join(out_dir, f"{name}_page{pg_idx+1}.png")
        pix.save(out)
        page_pngs.append(out)

    sidecar = os.path.join(out_dir, f"{name}_fields.json")
    with open(sidecar, "w") as f:
        json.dump(
            {"source": pdf_path, "pages": src.page_count, "widgets": index},
            f,
            indent=2,
            default=str,
        )

    overlay.close()
    src.close()
    print(f"Wrote {len(page_pngs)} PNG(s) + {sidecar}  ({counter} widgets)")
    return page_pngs, sidecar


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--zoom", type=float, default=2.0)
    args = ap.parse_args()
    out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.pdf))
    annotate(args.pdf, out_dir, args.zoom)


if __name__ == "__main__":
    main()
