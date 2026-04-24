"""Extract current widget values from a PDF into a plan JSON (index → value).

Useful for:
- Round-tripping an already-filled form into a plan you can hand-edit.
- Diffing two versions of a form (e.g., your hand-fill vs. a ground truth).

Notes on grouped CheckBoxes (treated like radio groups):
- Some forms (NY IT-201 filing status) implement radio-style choices as
  multiple CheckBox widgets sharing the same field_name. pymupdf's
  `widget.field_value` returns the parent field's /V, which is the same for
  every widget in the group — so it would falsely report all as checked.
- We instead read each widget's per-widget /AS (appearance state) directly.
"""
import argparse, json
import fitz


def _per_widget_on(doc, w):
    """Return True if THIS widget's /AS is non-/Off (not the parent /V)."""
    try:
        kind, val = doc.xref_get_key(w.xref, "AS")
        return kind == "name" and val and val != "/Off"
    except Exception:
        return w.field_value not in (None, "", "Off", False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out")
    args = ap.parse_args()

    doc = fitz.open(args.pdf)
    plan = {"_src": args.pdf}
    i = 0
    for page in doc:
        for w in page.widgets() or []:
            i += 1
            if w.field_type_string in ("CheckBox", "RadioButton"):
                plan[str(i)] = _per_widget_on(doc, w)
            else:
                plan[str(i)] = w.field_value or ""
    doc.close()
    with open(args.out, "w") as f:
        json.dump(plan, f, indent=2)
    print(f"extracted {i} widgets → {args.out}")


if __name__ == "__main__":
    main()
