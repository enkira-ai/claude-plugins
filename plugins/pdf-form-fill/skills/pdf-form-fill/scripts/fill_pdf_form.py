"""Fill a PDF's AcroForm widgets from a plan JSON keyed by the Set-of-Mark index.

Plan JSON format:
    {
      "1": "Jianghong Chang",        // text field
      "12": true,                    // checkbox / radio: true = on, false = off
      "25": "13300",
      "_comments": { ... }           // anything starting with _ is ignored
    }

Radio-group handling: pymupdf's high-level checkbox setter does NOT coordinate
sibling widgets in a radio group — leaving stale /AS on-states on other members.
We bypass it with direct xref writes that force every sibling to /Off except the
one being turned on, and set the parent field's /V.
"""
import argparse, json, sys
import fitz  # pymupdf


TRUTHY = {True, 1, "1", "X", "x", "Yes", "yes", "Y", "y", "check", "checked"}
FALSY = {False, 0, None, "", "Off", "off", "No", "no", "0", "uncheck"}


def _on_state(widget):
    try:
        s = widget.on_state()
        if s and s != "Off":
            return s
    except Exception:
        pass
    states = (widget.button_states() or {}).get("normal", [])
    for s in states:
        if s and s != "Off":
            return s
    return "Yes"


def _iter_widgets(doc):
    counter = 0
    for page in doc:
        for w in (page.widgets() or []):
            counter += 1
            yield counter, page, w


def clear_all(doc):
    cleared = 0
    for _, _, w in _iter_widgets(doc):
        if w.field_type_string == "RadioButton":
            doc.xref_set_key(w.xref, "AS", "/Off")
        elif w.field_type_string == "CheckBox":
            w.field_value = "Off"
            w.update()
        else:
            w.field_value = ""
            w.update()
        cleared += 1
    return cleared


def _group_members(doc, field_name):
    out = []
    for page in doc:
        for w in page.widgets() or []:
            if w.field_name == field_name:
                out.append(w)
    return out


def _set_radio_on(doc, target):
    on_state = _on_state(target)
    for sib in _group_members(doc, target.field_name):
        state = on_state if sib.xref == target.xref else "Off"
        doc.xref_set_key(sib.xref, "AS", f"/{state}")
    try:
        parent = doc.xref_get_key(target.xref, "Parent")
        if parent and parent[0] == "xref":
            parent_xref = int(parent[1].split()[0])
            doc.xref_set_key(parent_xref, "V", f"/{on_state}")
    except Exception:
        pass


def _is_grouped_checkbox(doc, widget):
    """A CheckBox is part of a radio-style group when multiple widgets share
    its field_name. NY IT-201 filing status is a real example: 5 CheckBox
    widgets all named 'Filing_status', differing only by on-state."""
    return len(_group_members(doc, widget.field_name)) > 1


def plan_to_actions(doc, plan):
    """Resolve plan into a list of (idx, widget_type, action, value_or_reason).
    Used by both apply_plan and the dry-run reporter."""
    widget_by_idx = {i: (p, w) for i, p, w in _iter_widgets(doc)}
    actions = []
    for key, val in plan.items():
        if key.startswith("_"):
            continue
        try:
            idx = int(key)
        except ValueError:
            actions.append((None, None, "BAD_KEY", f"non-integer key: {key!r}"))
            continue
        if idx not in widget_by_idx:
            actions.append((idx, None, "UNKNOWN_IDX", f"no widget at index {idx}"))
            continue
        _, w = widget_by_idx[idx]
        t = w.field_type_string
        if t == "RadioButton":
            if val in TRUTHY:
                actions.append((idx, t, "RADIO_ON", val))
            elif val in FALSY:
                actions.append((idx, t, "RADIO_OFF", val))
            else:
                actions.append((idx, t, "TYPE_MISMATCH",
                                f"RadioButton expects bool-ish, got {val!r}"))
        elif t == "CheckBox":
            grouped = _is_grouped_checkbox(doc, w)
            if val in TRUTHY:
                actions.append((idx, t, "RADIO_ON" if grouped else "CHECK_ON", val))
            elif val in FALSY:
                actions.append((idx, t, "RADIO_OFF" if grouped else "CHECK_OFF", val))
            else:
                actions.append((idx, t, "TYPE_MISMATCH",
                                f"CheckBox expects bool-ish, got {val!r}"))
        else:
            if isinstance(val, bool):
                actions.append((idx, t, "TYPE_MISMATCH",
                                f"Text field got bool {val!r}; expected string"))
            else:
                actions.append((idx, t, "SET_TEXT", "" if val is None else str(val)))
    return actions


def _set_check_on(doc, w):
    """Set a single (non-grouped) CheckBox to its on-state via direct xref.
    pymupdf's high-level `widget.field_value = on_state` setter is unreliable
    when on-state contains URL-encoded chars (e.g. 'elec#20funds#20withdrawal'):
    it writes /V but doesn't propagate to /AS, and on reload V reverts to /Off."""
    on = _on_state(w)
    doc.xref_set_key(w.xref, "AS", f"/{on}")
    doc.xref_set_key(w.xref, "V", f"/{on}")


def _set_check_off(doc, w):
    doc.xref_set_key(w.xref, "AS", "/Off")
    doc.xref_set_key(w.xref, "V", "/Off")


def apply_plan(doc, plan):
    actions = plan_to_actions(doc, plan)
    widget_by_idx = {i: (p, w) for i, p, w in _iter_widgets(doc)}
    set_count = 0
    warnings = []
    for idx, _t, action, payload in actions:
        if action in ("BAD_KEY", "UNKNOWN_IDX", "TYPE_MISMATCH"):
            warnings.append(f"#{idx}: {action} — {payload}")
            continue
        _, w = widget_by_idx[idx]
        if action == "RADIO_ON":
            _set_radio_on(doc, w)
        elif action == "RADIO_OFF":
            doc.xref_set_key(w.xref, "AS", "/Off")
        elif action == "CHECK_ON":
            _set_check_on(doc, w)
        elif action == "CHECK_OFF":
            _set_check_off(doc, w)
        elif action == "SET_TEXT":
            w.field_value = payload
            w.update()
        set_count += 1
    return set_count, warnings


def dry_run_report(doc, plan):
    actions = plan_to_actions(doc, plan)
    buckets: dict[str, list] = {}
    for a in actions:
        buckets.setdefault(a[2], []).append(a)
    lines = []
    lines.append(f"Dry run — {len(actions)} plan entries resolved")
    for action_name, rows in sorted(buckets.items()):
        lines.append(f"  {action_name}: {len(rows)}")
        if action_name in ("BAD_KEY", "UNKNOWN_IDX", "TYPE_MISMATCH"):
            for idx, t, _, payload in rows[:20]:
                lines.append(f"    #{idx} [{t}]: {payload}")
            if len(rows) > 20:
                lines.append(f"    ... and {len(rows) - 20} more")
    errors = sum(1 for a in actions if a[2] in ("BAD_KEY", "UNKNOWN_IDX", "TYPE_MISMATCH"))
    lines.append(f"Errors: {errors}")
    return "\n".join(lines), errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("plan")
    ap.add_argument("dst", nargs="?")
    ap.add_argument("--clear", action="store_true",
                    help="Clear every widget before applying the plan")
    ap.add_argument("--dry-run", action="store_true",
                    help="Validate the plan against the PDF and print a report; do not write output")
    args = ap.parse_args()

    with open(args.plan) as f:
        plan = json.load(f)
    fields = plan.get("fields", plan) if isinstance(plan, dict) else plan

    doc = fitz.open(args.src)

    if args.dry_run:
        report, errors = dry_run_report(doc, fields)
        print(report)
        doc.close()
        sys.exit(1 if errors else 0)

    if not args.dst:
        print("dst argument required unless --dry-run", file=sys.stderr)
        sys.exit(2)

    if args.clear:
        n = clear_all(doc)
        print(f"cleared {n} widgets")
    n, warns = apply_plan(doc, fields)
    print(f"set {n} widgets")
    for w in warns:
        print(f"  WARN: {w}", file=sys.stderr)
    doc.save(args.dst, deflate=True, garbage=3)
    doc.close()
    print(f"wrote {args.dst}")


if __name__ == "__main__":
    main()
