#!/usr/bin/env python3
"""Group meeting files (recordings, transcripts, notes) into one folder per meeting.

Google Meet, Gemini and Zoom drop their files in different places under different
names. This script reads Drive file metadata and decides which meeting each file
belongs to, so the caller can file it under `<meetings folder>/<YYYY-MM-DD HH:MM name>/`.
It never touches Drive itself: the skill does the moves with the Drive connector.

Input (stdin): JSON
  {"files":   [{"id", "title", "mimeType", "createdTime", "parentId", "parentTitle"?}, ...],
   "folders": [{"id", "title"}, ...]}   # existing meeting folders under the meetings folder
Output (stdout): JSON
  {"meetings": [{"folder": "<name>", "folder_id": "<id>" | null, "start": "<ISO>" | null,
                 "files": [{"id", "title", "kind"}]}],
   "unplaced": [{"id", "title", "why"}]}
`folder_id` is set when the meeting already has a folder; otherwise create `folder`.

Usage:
  meeting_files.py [--timezone America/New_York] < input.json
"""

import argparse
import collections
import html
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

GROUP_MINUTES = 20
GENERIC_PARENTS = {"meet recordings", "google meet", "recordings"}
MEET_CODE = re.compile(r"[a-z]{3}-[a-z]{4}-[a-z]{3}")
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def clean_name(name):
    name = re.sub(r"^\d{8}-", "", name or "")
    name = re.sub(r"\s*\(recurring\)\s*$", "", name)
    name = re.sub(r"\s*-\s*\d{4}/\d{2}/\d{2} \d{2}:\d{2} E[DS]T\s*$", "", name)
    name = re.sub(r"\s*\d{4}-\d{2}-\d{2}\s*$", "", name)
    return re.sub(r"\s{2,}", " ", name).strip()


def kind_of(f):
    title, mime = f["title"], f.get("mimeType", "")
    low = title.lower()
    if mime.startswith(("video/", "audio/")):
        return "recording"
    if "chat" in low and (title.endswith((".txt", " - Chat")) or mime == "text/plain"):
        return "chat"
    if title.endswith(".vtt") or "transcript" in low or title.endswith(".txt"):
        return "transcript"
    if mime in ("application/vnd.google-apps.document", "application/pdf"):
        return "summary"
    return "other"


def parse_title(title, tz):
    """Return (start, has_time, name) from a file title; start is a datetime or date."""
    m = re.match(r"(?P<n>.*?) - (?P<d>\d{4}/\d{2}/\d{2}) (?P<t>\d{2}:\d{2}) E[DS]T(?: - .*)?$", title)
    if m:
        start = datetime.strptime(f"{m['d']} {m['t']}", "%Y/%m/%d %H:%M").replace(tzinfo=ZoneInfo("America/New_York"))
        name = None if m["n"].startswith("Meeting started") else m["n"]
        return start.astimezone(tz), True, name
    m = re.match(r"(?P<n>.*?) - (?P<d>\d{4}_\d{2}_\d{2}) (?P<h>\d{2})_(?P<mi>\d{2}) P[DS]T - .*", title)
    if m:
        start = datetime.strptime(f"{m['d']} {m['h']}{m['mi']}", "%Y_%m_%d %H%M").replace(
            tzinfo=ZoneInfo("America/Los_Angeles"))
        return start.astimezone(tz), True, m["n"]
    m = re.match(rf"Meeting Summary — (?P<n>.*?) — (?P<d>(?:{MONTHS}) \d{{1,2}}, \d{{4}})", title)
    if m:
        return datetime.strptime(m["d"], "%B %d, %Y").date(), False, m["n"]
    m = re.match(r"Meeting started (?P<d>\d{4}/\d{2}/\d{2}) (?P<t>\d{2}:\d{2}) E[DS]T", title)
    if m:
        start = datetime.strptime(f"{m['d']} {m['t']}", "%Y/%m/%d %H:%M").replace(tzinfo=ZoneInfo("America/New_York"))
        return start.astimezone(tz), True, None
    m = re.match(r"(?P<code>[a-z]{3}-[a-z]{4}-[a-z]{3}) \((?P<d>\d{4}-\d{2}-\d{2}) (?P<t>\d{2}:\d{2}) GMT(?P<o>[-+]\d+)\)", title)
    if m:
        start = datetime.strptime(f"{m['d']} {m['t']}", "%Y-%m-%d %H:%M").replace(
            tzinfo=timezone(timedelta(hours=int(m["o"]))))
        return start.astimezone(tz), True, None
    m = re.match(r"GMT(?P<d>\d{8})-(?P<t>\d{6})_", title)  # Zoom: UTC start time
    if m:
        start = datetime.strptime(m["d"] + m["t"], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return start.astimezone(tz), True, None
    m = re.match(r"GMT(?P<d>\d{8})[-_](?P<rest>.*)\.\w+$", title)
    if m:
        rest = re.sub(r"^Meeting Notes-\s*", "", m["rest"]).replace("-", " ")
        return datetime.strptime(m["d"], "%Y%m%d").date(), False, rest
    m = re.match(r"(?P<d>20\d{6})-(?P<rest>.*)\.\w+$", title)
    if m:
        return datetime.strptime(m["d"], "%Y%m%d").date(), False, m["rest"].replace("-", " ")
    m = re.match(r"[0-9a-f-]{36}-(?P<e>\d{10,13})(?: \(\d+\))?\.\w+$", title)
    if m:
        epoch = int(m["e"])
        return datetime.fromtimestamp(epoch / 1000 if epoch > 1e11 else epoch, tz), True, None
    m = re.search(rf"(?:{MONTHS}) \d{{1,2}}, \d{{4}}", title)
    if m:
        return datetime.strptime(m.group(0), "%B %d, %Y").date(), False, None
    m = re.search(r"\d{4}-\d{2}-\d{2}", title)
    if m:
        return datetime.strptime(m.group(0), "%Y-%m-%d").date(), False, None
    return None, False, None


def parse_folder(title, tz):
    """Existing meeting folder `YYYY-MM-DD[ HH:MM] name` -> (day, start|None, name)."""
    m = re.match(r"(?P<d>\d{4}-\d{2}-\d{2})(?: (?P<t>\d{2}:\d{2}))? (?P<n>.+)$", title)
    if not m:
        return None
    day = m["d"]
    start = (datetime.strptime(f"{day} {m['t']}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
             if m["t"] else None)
    return day, start, m["n"]


def parent_name(f):
    parent = (f.get("parentTitle") or "").strip()
    if not parent or parent.lower() in GENERIC_PARENTS or re.fullmatch(r"\d\d-\d\d", parent):
        return None
    return clean_name(parent)


def is_placeholder(name):
    return not name or name == "Meeting" or MEET_CODE.fullmatch(name)


def plan(files, folders, tz):
    items, unplaced = [], []
    for f in files:
        f = dict(f, title=html.unescape(f.get("title") or ""))
        start, has_time, name = parse_title(f["title"], tz)
        if start is None:
            unplaced.append({"id": f["id"], "title": f["title"], "why": "no date or time in the title"})
            continue
        name = name or parent_name(f)
        if not name:
            code = MEET_CODE.match(f["title"])
            name = code.group(0) if code else "Meeting"
        items.append({"f": f, "start": start, "has_time": has_time, "name": clean_name(name),
                      "kind": kind_of(f)})

    groups = []
    for folder in folders:
        parsed = parse_folder(html.unescape(folder["title"]), tz)
        if parsed:
            day, start, name = parsed
            groups.append({"day": day, "start": start, "names": {name.lower()}, "items": [],
                           "folder": folder["title"], "folder_id": folder["id"]})

    items.sort(key=lambda i: str(i["start"]))
    for it in items:
        day = str(it["start"])[:10]
        target = None
        for g in groups:
            if g["day"] != day:
                continue
            if it["has_time"] and g["start"] is not None:
                if abs((it["start"] - g["start"]).total_seconds()) <= GROUP_MINUTES * 60:
                    target = g
            elif it["name"].lower() in g["names"]:
                target = g
            if target:
                break
        if target is None:
            target = {"day": day, "start": it["start"] if it["has_time"] else None,
                      "names": set(), "items": [], "folder": None, "folder_id": None}
            groups.append(target)
        target["items"].append(it)
        target["names"].add(it["name"].lower())
        if target["start"] is None and it["has_time"] and target["folder_id"] is None:
            target["start"] = it["start"]

    out = []
    for g in sorted(groups, key=lambda g: (g["day"], str(g["start"]))):
        if not g["items"]:
            continue
        if g["folder"] is None:
            names = [i["name"] for i in g["items"] if not is_placeholder(i["name"])] or \
                    [i["name"] for i in g["items"]]
            name = collections.Counter(names).most_common(1)[0][0]
            g["folder"] = (f"{g['day']} {g['start'].strftime('%H:%M')} {name}" if g["start"]
                           else f"{g['day']} {name}")
        out.append({"folder": g["folder"], "folder_id": g["folder_id"],
                    "start": g["start"].isoformat() if g["start"] else None,
                    "files": [{"id": i["f"]["id"], "title": i["f"]["title"], "kind": i["kind"]}
                              for i in g["items"]]})
    return {"meetings": out, "unplaced": unplaced}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--timezone", default="America/New_York")
    args = ap.parse_args()
    data = json.load(sys.stdin)
    json.dump(plan(data.get("files", []), data.get("folders", []), ZoneInfo(args.timezone)),
              sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
