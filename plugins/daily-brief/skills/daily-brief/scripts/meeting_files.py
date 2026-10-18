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
  meeting_files.py [--timezone America/New_York] [--allow-weak] < input.json

--timezone is the zone folder names are written and read in. Pass the same one on
every run for a given meetings folder (`context.recordings.folder_timezone`), or
existing folders' times are misread.
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
# What Meet and Gemini append after the timestamp ("… - 2026/10/14 11:01 EDT - Recording").
MEET_SUFFIX = re.compile(r"(Notes by Gemini|Recording|Chat|Transcript)(\.\w{2,4})?", re.I)
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


# Abbreviations Meet writes in titles. They are ambiguous worldwide (IST, CST), so
# only unambiguous ones map to a zone; anything else is read in the profile's zone.
ZONE_ABBREVIATIONS = {
    "EDT": "America/New_York", "EST": "America/New_York",
    "CDT": "America/Chicago", "MDT": "America/Denver", "MST": "America/Denver",
    "PDT": "America/Los_Angeles", "PST": "America/Los_Angeles",
    "AKDT": "America/Anchorage", "AKST": "America/Anchorage", "HST": "Pacific/Honolulu",
    "BST": "Europe/London", "GMT": "Etc/UTC", "UTC": "Etc/UTC",
    "WET": "Europe/Lisbon", "WEST": "Europe/Lisbon",
    "CET": "Europe/Paris", "CEST": "Europe/Paris", "EET": "Europe/Athens", "EEST": "Europe/Athens",
    "JST": "Asia/Tokyo", "KST": "Asia/Seoul", "SGT": "Asia/Singapore", "HKT": "Asia/Hong_Kong",
    "AEST": "Australia/Sydney", "AEDT": "Australia/Sydney", "NZST": "Pacific/Auckland",
    "NZDT": "Pacific/Auckland",
}


def zone_of(token, default):
    m = re.fullmatch(r"GMT([-+])(\d{1,2})(?::?(\d{2}))?", token)
    if m:
        delta = timedelta(hours=int(m[2]), minutes=int(m[3] or 0))
        return timezone(-delta if m[1] == "-" else delta)
    name = ZONE_ABBREVIATIONS.get(token)
    return ZoneInfo(name) if name else default


def parse_title(title, tz):
    """Return (start, has_time, name, strong) from a file title; start is a datetime or date.

    `strong` means the title format itself says this is a meeting artifact (Gemini
    notes, Meet recordings and chats, Zoom cloud recordings, meeting notes/summaries).
    A bare date or a recorder timestamp is weak evidence: such a file is filed only
    when it joins a meeting that has strong evidence or an existing folder."""
    # Meet/Gemini: "<meeting> - 2026/10/14 11:01 EDT - Notes by Gemini"; downloads
    # spell it "2026_07_14 11_59 PDT".
    m = re.match(r"(?P<n>.*?) - (?P<d>\d{4}[/_]\d{2}[/_]\d{2}) (?P<h>\d{2})[:_](?P<mi>\d{2}) "
                 r"(?P<z>[A-Z]{2,5}|GMT[-+]\d{1,2}(?::?\d{2})?)(?: - (?P<s>.*))?$", title)
    if m:
        start = datetime.strptime(f"{m['d'].replace('_', '/')} {m['h']}:{m['mi']}", "%Y/%m/%d %H:%M")
        start = start.replace(tzinfo=zone_of(m["z"], tz))
        name = None if m["n"].startswith("Meeting started") else m["n"]
        return start.astimezone(tz), True, name, bool(MEET_SUFFIX.fullmatch(m["s"] or ""))
    m = re.match(rf"Meeting Summary — (?P<n>.*?) — (?P<d>(?:{MONTHS}) \d{{1,2}}, \d{{4}})", title)
    if m:
        return datetime.strptime(m["d"], "%B %d, %Y").date(), False, m["n"], True
    m = re.match(r"Meeting started (?P<d>\d{4}/\d{2}/\d{2}) (?P<t>\d{2}:\d{2}) (?P<z>[A-Z]{2,5}|GMT[-+]\d{1,2}(?::?\d{2})?)", title)
    if m:
        start = datetime.strptime(f"{m['d']} {m['t']}", "%Y/%m/%d %H:%M").replace(tzinfo=zone_of(m["z"], tz))
        return start.astimezone(tz), True, None, True
    m = re.match(r"(?P<code>[a-z]{3}-[a-z]{4}-[a-z]{3}) \((?P<d>\d{4}-\d{2}-\d{2}) (?P<t>\d{2}:\d{2}) GMT(?P<o>[-+]\d+)\)", title)
    if m:
        start = datetime.strptime(f"{m['d']} {m['t']}", "%Y-%m-%d %H:%M").replace(
            tzinfo=timezone(timedelta(hours=int(m["o"]))))
        return start.astimezone(tz), True, None, True
    m = re.match(r"GMT(?P<d>\d{8})-(?P<t>\d{6})_", title)  # Zoom: UTC start time
    if m:
        start = datetime.strptime(m["d"] + m["t"], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return start.astimezone(tz), True, None, True
    m = re.match(r"GMT(?P<d>\d{8})[-_](?P<rest>.*)\.\w+$", title)
    if m:
        notes = "Meeting Notes" in m["rest"]
        rest = re.sub(r"^Meeting Notes-\s*", "", m["rest"]).replace("-", " ")
        return datetime.strptime(m["d"], "%Y%m%d").date(), False, rest, notes
    m = re.match(r"(?P<d>20\d{6})-(?P<rest>.*)\.\w+$", title)
    if m:
        return datetime.strptime(m["d"], "%Y%m%d").date(), False, m["rest"].replace("-", " "), False
    m = re.match(r"[0-9a-f-]{36}-(?P<e>\d{10,13})(?: \(\d+\))?\.\w+$", title)
    if m:
        epoch = int(m["e"])
        return datetime.fromtimestamp(epoch / 1000 if epoch > 1e11 else epoch, tz), True, None, False
    m = re.search(rf"(?:{MONTHS}) \d{{1,2}}, \d{{4}}", title)
    if m:
        notes = bool(re.search(r"meeting (summary|notes)", title, re.I))
        return datetime.strptime(m.group(0), "%B %d, %Y").date(), False, None, notes
    m = re.search(r"\d{4}-\d{2}-\d{2}", title)
    if m:
        notes = bool(re.search(r"meeting (summary|notes)", title, re.I))
        return datetime.strptime(m.group(0), "%Y-%m-%d").date(), False, None, notes
    return None, False, None, False


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


def norm(name):
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def names_compatible(name, names, strict=False):
    """Two real meeting names that differ mean two meetings, even at the same time.

    `strict` is for files with no meeting-specific title: a named one (say a screen
    recording) joins only a meeting with a matching real name, never an unnamed one."""
    if MEET_CODE.fullmatch(name or "") and any(MEET_CODE.fullmatch(n) and n != name for n in names):
        return False  # two Meet codes are two calls
    if is_placeholder(name):
        return True
    real = [n for n in names if not is_placeholder(n)]
    if not real:
        return not strict
    return any(norm(name) == norm(n) or norm(name) in norm(n) or norm(n) in norm(name)
                           for n in real)


def plan(files, folders, tz, allow_weak=False):
    items, unplaced = [], []
    for f in files:
        f = dict(f, title=html.unescape(f.get("title") or ""))
        start, has_time, name, strong = parse_title(f["title"], tz)
        # A Google Doc with Meet's timestamp is Gemini notes someone renamed.
        if (not strong and f.get("mimeType") == "application/vnd.google-apps.document"
                and re.search(r" - \d{4}/\d{2}/\d{2} \d{2}:\d{2} E[DS]T - ", f["title"])):
            strong = True
        if start is None:
            unplaced.append({"id": f["id"], "title": f["title"], "why": "no date or time in the title"})
            continue
        name = name or parent_name(f)
        if not name:
            code = MEET_CODE.match(f["title"])
            name = code.group(0) if code else "Meeting"
        items.append({"f": f, "start": start, "has_time": has_time, "name": clean_name(name),
                      "kind": kind_of(f), "strong": strong or allow_weak})

    groups = []
    for folder in folders:
        parsed = parse_folder(html.unescape(folder["title"]), tz)
        if parsed:
            day, start, name = parsed
            groups.append({"day": day, "start": start, "names": {name}, "items": [],
                           "folder": folder["title"], "folder_id": folder["id"]})

    items.sort(key=lambda i: str(i["start"]))
    for it in items:
        day = str(it["start"])[:10]
        # Join the closest compatible meeting that day: within GROUP_MINUTES when both
        # have a time, otherwise by name.
        target, best = None, None
        for g in groups:
            if g["day"] != day:
                continue
            if it["has_time"] and g["start"] is not None:
                gap = abs((it["start"] - g["start"]).total_seconds())
                if gap <= GROUP_MINUTES * 60 and names_compatible(it["name"], g["names"],
                                                                  strict=not it["strong"]):
                    if best is None or gap < best:
                        target, best = g, gap
            elif (target is None and not is_placeholder(it["name"])
                  and norm(it["name"]) in {norm(n) for n in g["names"]}):
                target = g
        if target is None:
            target = {"day": day, "start": it["start"] if it["has_time"] else None,
                      "names": set(), "items": [], "folder": None, "folder_id": None}
            groups.append(target)
        target["items"].append(it)
        target["names"].add(it["name"])
        if target["start"] is None and it["has_time"]:
            target["start"] = it["start"]  # a date-only folder keeps its name, but gains a time

    out = []
    for g in sorted(groups, key=lambda g: (g["day"], str(g["start"]))):
        if not g["items"]:
            continue
        # Only file a meeting the titles vouch for, or one that already has a folder.
        # Screen captures, voice memos and other dated media stay where they are.
        if g["folder_id"] is None and not any(i["strong"] for i in g["items"]):
            unplaced.extend({"id": i["f"]["id"], "title": i["f"]["title"],
                             "why": "no sign this is a meeting file"} for i in g["items"])
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
    ap.add_argument("--allow-weak", action="store_true",
                    help="also file dated files with no meeting-specific title (one-off clean-ups of a known meetings folder)")
    args = ap.parse_args()
    data = json.load(sys.stdin)
    json.dump(plan(data.get("files", []), data.get("folders", []), ZoneInfo(args.timezone),
                   args.allow_weak),
              sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
