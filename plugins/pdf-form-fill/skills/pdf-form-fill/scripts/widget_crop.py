"""Render a small PNG crop around one or more widgets — for visual verification
when text-proximity labeling is ambiguous (e.g., checkbox grids, multi-column
layouts, or overlapping tag labels in dense forms).

Cheaper than re-rendering a full annotated page: feeds the LLM just the
relevant widget + its surrounding caption at high resolution.

Usage:
    run-python.sh widget_crop.py <pdf> <index> [<index> ...] [--pad 80] [--zoom 3]

Writes one PNG per index: <name>_tag<N>.png
"""
import argparse, os
import fitz  # pymupdf


def crop_widgets(pdf_path: str, indices: list[int], out_dir: str,
                 pad: float = 80.0, zoom: float = 3.0):
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(pdf_path))[0]
    doc = fitz.open(pdf_path)

    # Walk widgets in document order to find requested indices.
    target_map: dict[int, tuple[int, fitz.Widget]] = {}
    counter = 0
    for pg_idx, page in enumerate(doc):
        for w in (page.widgets() or []):
            counter += 1
            if counter in indices:
                target_map[counter] = (pg_idx, w)

    missing = [i for i in indices if i not in target_map]
    if missing:
        print(f"WARN: no widget for indices {missing}")

    outputs = []
    for idx in sorted(target_map):
        pg_idx, w = target_map[idx]
        page = doc[pg_idx]
        rect = fitz.Rect(w.rect)
        clip = fitz.Rect(
            max(0, rect.x0 - pad),
            max(0, rect.y0 - pad / 2),
            min(page.rect.width, rect.x1 + pad),
            min(page.rect.height, rect.y1 + pad / 2),
        )
        # Redraw the widget rect on a copy so the crop shows what was clicked.
        overlay = fitz.open()
        overlay.insert_pdf(doc, from_page=pg_idx, to_page=pg_idx)
        op = overlay[0]
        op.draw_rect(rect, color=(0.9, 0.1, 0.1), width=1.2)
        # One and only one tag in the crop — no overlap possible.
        label = str(idx)
        tag_w = 6 + len(label) * 5.0
        tag_h = 10.0
        tag = fitz.Rect(rect.x0 - tag_w - 1, rect.y0, rect.x0 - 1, rect.y0 + tag_h)
        if tag.x0 < clip.x0:  # fallback: tuck inside top-left of widget
            tag = fitz.Rect(rect.x0, rect.y0, rect.x0 + tag_w, rect.y0 + tag_h)
        op.draw_rect(tag, color=(0.9, 0.1, 0.1), fill=(0.9, 0.1, 0.1), width=0)
        op.insert_text(
            (tag.x0 + 1.5, tag.y1 - 2.2),
            label,
            fontsize=8.0,
            color=(1, 1, 1),
            fontname="helv",
        )
        pix = op.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
        out = os.path.join(out_dir, f"{name}_tag{idx}.png")
        pix.save(out)
        outputs.append(out)
        overlay.close()
    doc.close()
    for o in outputs:
        print(f"Wrote {o}")
    return outputs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("indices", type=int, nargs="+")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--pad", type=float, default=80.0)
    ap.add_argument("--zoom", type=float, default=3.0)
    args = ap.parse_args()
    out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.pdf))
    crop_widgets(args.pdf, args.indices, out_dir, args.pad, args.zoom)


if __name__ == "__main__":
    main()
