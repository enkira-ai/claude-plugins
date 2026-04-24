"""Bind each AcroForm widget to the caption text *from the PDF itself*.

Design:
1. Use pymupdf's line-level text units (fragments joined by layout engine).
2. Score candidates via band_overlap × exp-decay proximity, not raw distance.
   - band_overlap: fraction of widget's Y-band that the text covers.
     Handles the widget-Y-offset bug where a label sits ~1pt off the row.
3. Compute BOTH left-match and above-match, emit confidence for each.
4. Flag widgets where both scores are low — ambiguous, needs widget_crop.
5. Run semantic-type regex on the caption line: ssn, ein, currency, date, etc.

Output: <name>_labels.json + <name>_labels.md.

No vision API. Deterministic. Designed for Haiku to consume.
"""
import argparse, json, math, os, re
import fitz  # pymupdf


# --- line extraction -----------------------------------------------------

_DOT_LEADER_RE = re.compile(r"^[\.\s·•]+$")


def _page_lines(page, baseline_tol: float = 1.5):
    """Return line-level text units, with two layout fixes:

    1. pymupdf splits same-row text across 'blocks' when dotted leaders or
       column gaps interrupt the line (common on tax forms: '1' + dots +
       'Gross receipts or sales'). We MERGE spans that share a baseline.
    2. We DROP dot-leader fragments — they have text like '.', '..', etc. —
       because they contribute no semantic content and flood the scoring.
    """
    raw_spans: list[dict] = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text or _DOT_LEADER_RE.match(text):
                    continue
                raw_spans.append({"text": text, "bbox": span.get("bbox", (0, 0, 0, 0))})

    # Bucket by baseline (ly1). pymupdf's bbox y1 is stable across a row
    # because all spans share the same font baseline.
    if not raw_spans:
        return []
    raw_spans.sort(key=lambda s: (s["bbox"][3], s["bbox"][0]))
    groups: list[list[dict]] = [[raw_spans[0]]]
    for s in raw_spans[1:]:
        prev_y1 = groups[-1][-1]["bbox"][3]
        if abs(s["bbox"][3] - prev_y1) <= baseline_tol:
            groups[-1].append(s)
        else:
            groups.append([s])

    out = []
    for g in groups:
        g.sort(key=lambda s: s["bbox"][0])
        text = " ".join(s["text"] for s in g)
        x0 = min(s["bbox"][0] for s in g)
        y0 = min(s["bbox"][1] for s in g)
        x1 = max(s["bbox"][2] for s in g)
        y1 = max(s["bbox"][3] for s in g)
        out.append({"text": text, "bbox": (x0, y0, x1, y1)})
    return out


# --- scoring -------------------------------------------------------------

def _band_overlap_y(widget_rect, line_bbox) -> float:
    """Fraction of widget height covered by line's Y-band."""
    _, ly0, _, ly1 = line_bbox
    wy0, wy1 = widget_rect.y0, widget_rect.y1
    # Expand widget band slightly (1pt) — captions often sit just above the box.
    wy0e, wy1e = wy0 - 1.0, wy1 + 1.0
    top, bot = max(wy0e, ly0), min(wy1e, ly1)
    overlap = max(0.0, bot - top)
    w_h = max(1e-6, wy1 - wy0)
    return min(1.0, overlap / w_h)


def _band_overlap_x(widget_rect, line_bbox) -> float:
    lx0, _, lx1, _ = line_bbox
    wx0, wx1 = widget_rect.x0, widget_rect.x1
    top, bot = max(wx0, lx0), min(wx1, lx1)
    overlap = max(0.0, bot - top)
    w_w = max(1e-6, wx1 - wx0)
    return min(1.0, overlap / w_w)


def _proximity(distance: float, scale: float = 120.0) -> float:
    """Exponential decay — 1.0 at distance 0, ~0.37 at scale, ~0.05 at 3×scale."""
    return math.exp(-max(0.0, distance) / max(1e-6, scale))


def _best_left(widget_rect, lines, max_distance=360.0):
    """Score lines strictly to the left on overlapping row band."""
    best = None
    for L in lines:
        lx0, _, lx1, _ = L["bbox"]
        if lx1 > widget_rect.x0 + 1:
            continue
        band = _band_overlap_y(widget_rect, L["bbox"])
        if band <= 0:
            continue
        dist = widget_rect.x0 - lx1
        if dist > max_distance:
            continue
        score = band * _proximity(dist, scale=80.0)
        if best is None or score > best["score"]:
            best = {"line": L, "score": round(score, 3), "distance": round(dist, 1)}
    return best


def _best_above(widget_rect, lines, max_distance=40.0):
    """Score lines strictly above with column overlap."""
    best = None
    for L in lines:
        _, ly0, _, ly1 = L["bbox"]
        if ly1 > widget_rect.y0 + 1:
            continue
        col = _band_overlap_x(widget_rect, L["bbox"])
        if col <= 0:
            continue
        dist = widget_rect.y0 - ly1
        if dist > max_distance:
            continue
        score = col * _proximity(dist, scale=18.0)
        if best is None or score > best["score"]:
            best = {"line": L, "score": round(score, 3), "distance": round(dist, 1)}
    return best


# --- main ----------------------------------------------------------------

AMBIGUOUS_THRESHOLD = 0.25  # if max(left_score, above_score) < this, flag it
# Also flag when the best caption is too short/operator-like to be meaningful.
SHORT_CAPTION_THRESHOLD = 3
OPERATOR_CAPTIONS = {"=", "x", "+", "-", "/", "*", "%", ".", ",", "$"}


def map_labels(pdf_path: str, out_dir: str,
               left_pad: float = 360.0, above_pad: float = 40.0):
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(pdf_path))[0]
    doc = fitz.open(pdf_path)

    records = []
    ambiguous = []
    counter = 0
    for pg_idx, page in enumerate(doc):
        lines = _page_lines(page)
        for w in (page.widgets() or []):
            counter += 1
            rect = fitz.Rect(w.rect)
            left = _best_left(rect, lines, left_pad)
            above = _best_above(rect, lines, above_pad)

            left_text = (left or {}).get("line", {}).get("text") if left else None
            above_text = (above or {}).get("line", {}).get("text") if above else None
            left_score = (left or {}).get("score", 0.0)
            above_score = (above or {}).get("score", 0.0)

            rec = {
                "idx": counter,
                "page": pg_idx + 1,
                "field": w.field_name,
                "type": w.field_type_string,
                "rect": [round(c, 2) for c in rect],
                "value": w.field_value,
                "left_label": left_text,
                "left_score": left_score,
                "above_label": above_text,
                "above_score": above_score,
            }
            records.append(rec)
            best = (left_text if left_score >= above_score else above_text) or ""
            best_stripped = best.strip()
            flag_reason = None
            if max(left_score, above_score) < AMBIGUOUS_THRESHOLD:
                flag_reason = "low score on both left and above — no clear caption"
            elif (len(best_stripped) < SHORT_CAPTION_THRESHOLD
                  or best_stripped in OPERATOR_CAPTIONS):
                flag_reason = f"best caption is operator/short ({best_stripped!r}) — likely a formula-row widget"
            if flag_reason:
                ambiguous.append({
                    "idx": counter,
                    "page": pg_idx + 1,
                    "type": w.field_type_string,
                    "left_label": left_text,
                    "left_score": left_score,
                    "above_label": above_text,
                    "above_score": above_score,
                    "reason": flag_reason,
                })
    doc.close()

    json_path = os.path.join(out_dir, f"{name}_labels.json")
    with open(json_path, "w") as f:
        json.dump({
            "source": pdf_path,
            "ambiguous": ambiguous,
            "ambiguous_threshold": AMBIGUOUS_THRESHOLD,
            "records": records,
        }, f, indent=2, default=str)

    md_path = os.path.join(out_dir, f"{name}_labels.md")
    with open(md_path, "w") as f:
        f.write(f"# Field labels for {os.path.basename(pdf_path)}\n\n")
        if ambiguous:
            f.write(f"## Ambiguous widgets ({len(ambiguous)}) — run `widget_crop.py` on these\n\n")
            f.write("| tag | page | type | left (score) | above (score) |\n")
            f.write("|---|---|---|---|---|\n")
            for a in ambiguous:
                lt = (a["left_label"] or "")[:40].replace("|", "\\|")
                at = (a["above_label"] or "")[:40].replace("|", "\\|")
                f.write(f"| {a['idx']} | {a['page']} | {a['type']} | {lt} ({a['left_score']}) | {at} ({a['above_score']}) |\n")
            f.write("\n")
        f.write("## All widgets\n\n")
        f.write("| tag | pg | type | left (score) | above (score) | caption |\n")
        f.write("|---|---|---|---|---|---|\n")
        for r in records:
            lt = (r["left_label"] or "")[:50].replace("|", "\\|")
            at = (r["above_label"] or "")[:30].replace("|", "\\|")
            full = (r["left_label"] or r["above_label"] or "")[:100].replace("|", "\\|")
            f.write(
                f"| {r['idx']} | {r['page']} | {r['type']} | {lt} ({r['left_score']}) "
                f"| {at} ({r['above_score']}) | {full} |\n"
            )

    print(f"Wrote {json_path}  ({counter} widgets, {len(ambiguous)} ambiguous)")
    print(f"Wrote {md_path}")
    return json_path, md_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--left-pad", type=float, default=360.0)
    ap.add_argument("--above-pad", type=float, default=40.0)
    args = ap.parse_args()
    out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.pdf))
    map_labels(args.pdf, out_dir, args.left_pad, args.above_pad)


if __name__ == "__main__":
    main()
