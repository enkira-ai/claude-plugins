"""Extract current widget values from a PDF into a plan JSON (index → value).

Useful for:
- Round-tripping an already-filled form into a plan you can hand-edit.
- Diffing two versions of a form (e.g., your hand-fill vs. a ground truth).
"""
import argparse, json
import fitz


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
            if w.field_type_string == "CheckBox":
                plan[str(i)] = w.field_value not in (None, "", "Off", False)
            elif w.field_type_string == "RadioButton":
                # Extract /AS appearance state; "On" of any kind → true.
                val = w.field_value
                plan[str(i)] = val not in (None, "", "Off", False)
            else:
                plan[str(i)] = w.field_value or ""
    doc.close()
    with open(args.out, "w") as f:
        json.dump(plan, f, indent=2)
    print(f"extracted {i} widgets → {args.out}")


if __name__ == "__main__":
    main()
