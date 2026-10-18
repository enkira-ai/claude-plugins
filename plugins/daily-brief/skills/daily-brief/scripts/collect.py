#!/usr/bin/env python3
"""Collect the raw facts for a daily brief and print them as one JSON document.

One config can hold several profiles (one per recipient); each run collects for
one profile.

Sources:
  * GitHub (via the `gh` CLI): PRs awaiting the user's review, the user's own open
    PRs with CI/review state, assigned issues, recent mentions, the user's recent
    activity (commits, merged PRs, closed issues), and every issue/PR created or
    merged in the watched repos since the last brief.
  * The windows and identities the skill needs to read Google Calendar, Slack and
    Gmail through the claude.ai connectors (`context`). Those reads happen in the
    skill, because the connectors are not reachable from this script.
  * Local Claude Code transcripts (~/.claude/projects/*/*.jsonl), only for a profile
    with `local_sessions: true`: the user's sessions active since the last brief —
    "where I stopped".

The script only gathers facts. Ranking, urgency calls and prose are the skill's job.

Usage:
  collect.py --profile NAME [--since ISO8601|auto] [--config PATH] [--skip-if-sent-within H]
  collect.py --profile NAME --mark-sent   # record now as this profile's last-brief time
  collect.py --list-profiles              # names, recipients and schedules (JSON)
  collect.py --profile NAME --show-config # print one profile's resolved config
--profile may be omitted when the config has a single profile.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

CONFIG_PATH = Path(os.environ.get(
    "DAILY_BRIEF_CONFIG", Path.home() / ".config" / "daily-brief" / "config.json"))
STATE_DIR = Path(os.environ.get(
    "DAILY_BRIEF_STATE", Path.home() / ".local" / "state" / "daily-brief"))
PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Shared defaults; every key can be overridden per profile.
DEFAULT_CONFIG = {
    "github_user": "",            # empty → `gh api user`
    "org": "enkira-ai",
    "repos": [],                  # "owner/name" or bare "name" (prefixed with org)
    "exclude_repos": [],          # dropped from every org-wide search (reviews, PRs, activity…)
    "git_identities": [],         # extra git user.name/email values that count as "me"
    "local_sessions": False,      # summarize this machine's Claude sessions for this user
    "email_from": "",
    "email_to": "",
    "slack_user": "",             # Slack user/channel ID for the DM; empty → no Slack
    "timezone": "UTC",
    "schedule": ["09:00", "21:00"],
    "max_lookback_hours": 36,     # cap for --since auto when the last brief is old
    "body_chars": 1500,
    "recent_sessions_floor": 3,   # always include this many latest sessions
    # Calendar / Slack / Gmail (read by the skill through the connectors)
    "owner": False,               # the connector account's owner: own DMs, whole mailbox, all meetings
    "aliases": [],                # every address the person is invited/cc'd as; email_to is added
    "slack_member_id": "",        # their Slack user ID, for DMs and mentions
    "calendar_id": "",            # shared calendar to read meetings from (e.g. admin@novaserve.ai)
    "slack_channels": [],         # [{"name": "technology", "id": "C…"}] summarized for everyone
    "evening_after_hour": 15,     # a run at/after this local hour previews tomorrow's meetings
    "meetings_folder_id": "",     # Drive folder holding one folder per meeting; empty → no recordings section
    "meetings_timezone": "",      # zone of the meeting folders' names; empty → the shared top-level timezone
}

NOISE_PREFIXES = ("<local-command", "<command-name>", "<command-message>",
                  "<system-reminder>", "Caveat:", "[Request interrupted")


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def load_profiles(path):
    """Return {name: resolved profile}. A config without `profiles` is one profile
    that owns this machine's sessions (the original single-user format)."""
    if not path.exists():
        sys.exit(f"No config at {path}. Run the daily-brief setup first.")
    raw = json.loads(path.read_text())
    shared = {k: v for k, v in raw.items() if k != "profiles"}
    entries = raw.get("profiles") or [{"local_sessions": True, **shared}]
    profiles = {}
    for entry in entries:
        cfg = {**DEFAULT_CONFIG, **shared, **entry}
        if not cfg["github_user"]:
            cfg["github_user"] = gh_text(["api", "user", "-q", ".login"]) or ""
        cfg["name"] = entry.get("name") or cfg["github_user"]
        # One zone for meeting-folder names, whichever profile happens to file them.
        cfg["meetings_timezone"] = (cfg["meetings_timezone"]
                                    or shared.get("timezone") or DEFAULT_CONFIG["timezone"])
        cfg["repos"] = [r if "/" in r else f"{cfg['org']}/{r}" for r in cfg["repos"]]
        cfg["exclude_repos"] = [r if "/" in r else f"{cfg['org']}/{r}" for r in cfg["exclude_repos"]]
        profiles[cfg["name"]] = cfg
    return profiles


def pick_profile(profiles, name):
    if name:
        if name not in profiles:
            sys.exit(f"Unknown profile {name!r}. Profiles: {', '.join(profiles)}")
        return profiles[name]
    if len(profiles) > 1:
        sys.exit(f"--profile is required. Profiles: {', '.join(profiles)}")
    return next(iter(profiles.values()))


# --------------------------------------------------------------------------- gh

def gh_text(args):
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def gh_json(args, errors, label):
    # GitHub's search API allows 30 requests a minute; a run that briefs two
    # profiles back to back can hit it, so wait out the window and retry.
    for attempt in range(4):
        try:
            out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=90)
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{label}: {exc}")
            return []
        if out.returncode == 0 or "rate limit" not in out.stderr.lower() or attempt == 3:
            break
        time.sleep(20 * (attempt + 1))
    if out.returncode != 0:
        errors.append(f"{label}: {out.stderr.strip()[:300]}")
        return []
    try:
        return json.loads(out.stdout or "[]")
    except json.JSONDecodeError:
        errors.append(f"{label}: unparseable gh output")
        return []


def trim(text, limit):
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


def slim_item(item, body_chars):
    """Flatten gh's nested JSON into what the brief needs."""
    out = {
        "repo": (item.get("repository") or {}).get("nameWithOwner") or item.get("_repo"),
        "number": item.get("number"),
        "title": item.get("title"),
        "url": item.get("url"),
        "author": (item.get("author") or {}).get("login"),
        "state": item.get("state"),
        "created": item.get("createdAt"),
        "updated": item.get("updatedAt"),
        "closed": item.get("closedAt"),
        "labels": [l.get("name") for l in item.get("labels") or []],
    }
    for key in ("isDraft", "reviewDecision", "mergeable", "headRefName", "commentsCount"):
        if key in item:
            out[key] = item[key]
    if "assignees" in item:
        out["assignees"] = [a.get("login") for a in item["assignees"] or []]
    if "statusCheckRollup" in item:
        out["ci"] = summarize_ci(item["statusCheckRollup"])
    if "body" in item:
        out["body"] = trim(item["body"], body_chars)
    return out


def merged_item(item, repo):
    return {"repo": repo, "number": item.get("number"), "title": item.get("title"),
            "url": item.get("url"), "author": (item.get("author") or {}).get("login"),
            "merged": item.get("mergedAt"),
            "labels": [l.get("name") for l in item.get("labels") or []],
            "body": trim(item.get("body"), 600)}


def slim_commit(c):
    url = c.get("url") or ""
    m = re.match(r"https://github.com/([^/]+/[^/]+)/commit/", url)
    commit = c.get("commit") or {}
    return {"repo": m.group(1) if m else None, "sha": (c.get("sha") or "")[:7], "url": url,
            "message": (commit.get("message") or "").split("\n")[0][:200],
            "date": (commit.get("author") or {}).get("date")}


def summarize_ci(checks):
    counts = {"pass": 0, "fail": 0, "pending": 0}
    failing = []
    for c in checks or []:
        verdict = (c.get("conclusion") or c.get("state") or "").upper()
        status = (c.get("status") or "").upper()
        if verdict in ("SUCCESS", "SKIPPED", "NEUTRAL"):
            counts["pass"] += 1
        elif verdict in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED"):
            counts["fail"] += 1
            failing.append(c.get("name") or c.get("context"))
        elif status in ("IN_PROGRESS", "QUEUED", "PENDING") or verdict in ("PENDING", "EXPECTED", ""):
            counts["pending"] += 1
    counts["failing_checks"] = sorted({f for f in failing if f})
    return counts


def collect_github(cfg, since, errors):
    user, org, n = cfg["github_user"], cfg["org"], cfg["body_chars"]
    day = since.strftime("%Y-%m-%d")
    search_fields = "number,title,url,repository,author,createdAt,updatedAt,labels,body,isDraft,commentsCount"
    pr_fields = ("number,title,url,author,createdAt,updatedAt,labels,body,isDraft,state,"
                 "reviewDecision,headRefName")

    jobs = {
        "review_requested": ["search", "prs", f"--review-requested={user}", "--state=open",
                             f"--owner={org}", "--limit=50", "--json", search_fields],
        "assigned_issues": ["search", "issues", f"--assignee={user}", "--state=open",
                            f"--owner={org}", "--limit=50", "--json",
                            "number,title,url,repository,author,createdAt,updatedAt,labels,body"],
        "mentions": ["search", "issues", f"--mentions={user}", "--include-prs",
                     f"--updated=>={day}", f"--owner={org}", "--limit=30", "--json",
                     "number,title,url,repository,author,createdAt,updatedAt,labels,state,isPullRequest"],
        "my_open_prs_all": ["search", "prs", f"--author={user}", "--state=open",
                            f"--owner={org}", "--limit=50", "--json",
                            "number,title,url,repository,createdAt,updatedAt,isDraft"],
    }
    jobs.update({
        "commits": ["search", "commits", f"--author={user}", f"--owner={org}",
                    f"--author-date=>={day}", "--sort=author-date", "--limit=50",
                    "--json", "sha,commit,url"],
        "merged_prs": ["search", "prs", f"--author={user}", f"--owner={org}",
                       f"--merged-at=>={day}", "--limit=30", "--json",
                       "number,title,url,repository,createdAt,updatedAt,closedAt,labels"],
        "closed_issues": ["search", "issues", f"--assignee={user}", f"--owner={org}",
                          f"--closed=>={day}", "--limit=30", "--json",
                          "number,title,url,repository,createdAt,updatedAt,closedAt,labels,state"],
    })
    for repo in cfg["repos"]:
        jobs[f"new_prs:{repo}"] = ["pr", "list", "-R", repo, "--state=all", "--limit=50",
                                   "--search", f"created:>={day}", "--json", pr_fields]
        jobs[f"new_issues:{repo}"] = ["issue", "list", "-R", repo, "--state=all", "--limit=50",
                                      "--search", f"created:>={day}", "--json",
                                      "number,title,url,author,createdAt,updatedAt,labels,body,state,assignees"]
        jobs[f"merged:{repo}"] = ["pr", "list", "-R", repo, "--state=merged", "--limit=50",
                                  "--search", f"merged:>={day}", "--json",
                                  "number,title,url,author,mergedAt,labels,body"]
        jobs[f"my_prs:{repo}"] = ["pr", "list", "-R", repo, "--author", user, "--state=open",
                                  "--limit=30", "--json",
                                  "number,title,url,createdAt,updatedAt,isDraft,reviewDecision,"
                                  "mergeable,statusCheckRollup,headRefName"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {k: pool.submit(gh_json, v, errors, k) for k, v in jobs.items()}
        raw = {k: f.result() for k, f in futures.items()}

    # Org-wide searches also hit repos the team has parked; drop those everywhere.
    excluded = {r.lower() for r in cfg["exclude_repos"]}

    def repo_of(item):
        name = (item.get("repository") or {}).get("nameWithOwner")
        if not name:
            m = re.match(r"https://github.com/([^/]+/[^/]+)/", item.get("url") or "")
            name = m.group(1) if m else ""
        return name.lower()

    for key in ("review_requested", "assigned_issues", "mentions", "my_open_prs_all",
                "commits", "merged_prs", "closed_issues"):
        raw[key] = [i for i in raw[key] if repo_of(i) not in excluded]

    def tag(items, repo):
        for it in items:
            it["_repo"] = repo
        return items

    # gh's date qualifiers (`created:>=DATE`, `--merged-at`, `--closed`, …) are
    # day-granular, so a search also returns what happened earlier that day, which
    # the previous brief already reported. Keep only items whose `field` is at or
    # after `since`; an item without a timestamp is kept rather than lost.
    def since_last(items, field):
        return [i for i in items if (parse_ts(i.get(field)) or since) >= since]

    def fresh(item):
        return bool(since_last([item], "created"))

    out = {
        "review_requested": [slim_item(i, n) for i in raw["review_requested"]],
        "assigned_issues": [slim_item(i, n) for i in raw["assigned_issues"]],
        "mentions": since_last([slim_item(i, n) for i in raw["mentions"]], "updated"),
        "my_open_prs": [],
        "new_in_watched_repos": {},
        "activity": {
            "commits": since_last([slim_commit(c) for c in raw["commits"]], "date"),
            "merged_prs": since_last([slim_item(i, n) for i in raw["merged_prs"]], "closed"),
            "closed_issues": since_last([slim_item(i, n) for i in raw["closed_issues"]], "closed"),
        },
    }

    # Review requests drive the urgency ranking, so give each one size, CI, review
    # state and the issues it closes (whose descriptions often carry the urgency).
    def enrich(pr):
        detail = gh_json(["pr", "view", str(pr["number"]), "-R", pr["repo"], "--json",
                          "additions,deletions,changedFiles,reviewDecision,mergeable,"
                          "statusCheckRollup,closingIssuesReferences,latestReviews"],
                         errors, f"pr view {pr['repo']}#{pr['number']}")
        if not detail:
            return pr
        pr.update({k: detail.get(k) for k in
                   ("additions", "deletions", "changedFiles", "reviewDecision", "mergeable")})
        pr["ci"] = summarize_ci(detail.get("statusCheckRollup"))
        pr["latest_reviews"] = [
            {"by": (r.get("author") or {}).get("login"), "state": r.get("state"),
             "at": r.get("submittedAt")} for r in detail.get("latestReviews") or []]
        pr["closes_issues"] = []
        for ref in detail.get("closingIssuesReferences") or []:
            repo = (ref.get("repository") or {}).get("nameWithOwner") or pr["repo"]
            issue = gh_json(["issue", "view", str(ref["number"]), "-R", repo, "--json",
                             "number,title,url,labels,body,createdAt"],
                            errors, f"issue view {repo}#{ref['number']}")
            if issue:
                issue["_repo"] = repo
                pr["closes_issues"].append(slim_item(issue, n // 2))
        return pr

    with ThreadPoolExecutor(max_workers=6) as pool:
        out["review_requested"] = list(pool.map(enrich, out["review_requested"]))

    seen_mine = set()
    for repo in cfg["repos"]:
        mine = [slim_item(i, n) for i in tag(raw[f"my_prs:{repo}"], repo)]
        out["my_open_prs"].extend(mine)
        seen_mine.update((repo, p["number"]) for p in mine)
        out["new_in_watched_repos"][repo] = {
            "prs": [p for p in (slim_item(i, n) for i in tag(raw[f"new_prs:{repo}"], repo)) if fresh(p)],
            "issues": [p for p in (slim_item(i, n) for i in tag(raw[f"new_issues:{repo}"], repo)) if fresh(p)],
            "merged": since_last([merged_item(i, repo) for i in raw[f"merged:{repo}"]], "merged"),
        }
    # Open PRs of mine outside the watched repos (no CI detail, but don't lose them).
    for item in raw["my_open_prs_all"]:
        s = slim_item(item, n)
        if (s["repo"], s["number"]) not in seen_mine:
            s["outside_watched_repos"] = True
            out["my_open_prs"].append(s)
    return out


# ------------------------------------------------------------------- sessions

def norm_identity(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def git_identity(cwd, cache):
    if cwd in cache:
        return cache[cwd]
    ids = set()
    if cwd and Path(cwd).is_dir():
        for key in ("user.name", "user.email"):
            try:
                r = subprocess.run(["git", "-C", cwd, "config", key],
                                   capture_output=True, text=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if r.returncode == 0 and r.stdout.strip():
                val = r.stdout.strip()
                ids.add(norm_identity(val))
                if "@" in val:
                    local = val.split("@")[0]
                    ids.add(norm_identity(local.split("+")[-1]))  # 123+login@users.noreply…
    cache[cwd] = ids
    return ids


def message_text(msg):
    content = (msg or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content
                         if isinstance(p, dict) and p.get("type") == "text")
    return ""


def is_real_prompt(entry, text):
    if entry.get("isMeta") or entry.get("isSidechain"):
        return False
    text = text.strip()
    return bool(text) and not text.startswith(NOISE_PREFIXES)


def scan_session(path, since):
    info = {"session_id": path.stem, "file": str(path), "title": None, "cwd": None,
            "branch": None, "first_ts": None, "last_ts": None, "prompts_since": 0,
            "last_user_prompt": None, "last_assistant_text": None}
    with open(path, errors="replace") as fh:
        for line in fh:
            # Cheap pre-filter: transcripts can be hundreds of MB of tool output.
            if '"custom-title"' in line:
                try:
                    info["title"] = json.loads(line).get("customTitle") or info["title"]
                except json.JSONDecodeError:
                    pass
                continue
            if '"type":"user"' not in line and '"type":"assistant"' not in line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("isSidechain"):
                continue
            ts = parse_ts(e.get("timestamp"))
            if ts:
                info["first_ts"] = info["first_ts"] or e["timestamp"]
                info["last_ts"] = e["timestamp"]
            info["cwd"] = e.get("cwd") or info["cwd"]
            info["branch"] = e.get("gitBranch") or info["branch"]
            text = message_text(e.get("message"))
            if e.get("type") == "user" and is_real_prompt(e, text):
                info["last_user_prompt"] = trim(text, 600)
                if ts and ts >= since:
                    info["prompts_since"] += 1
            elif e.get("type") == "assistant" and text.strip():
                info["last_assistant_text"] = text.strip()
    info["last_assistant_text"] = trim(info["last_assistant_text"], 1500)
    return info


def collect_sessions(cfg, since, errors):
    if not PROJECTS_DIR.is_dir():
        errors.append(f"sessions: {PROJECTS_DIR} not found")
        return []
    mine = {norm_identity(cfg["github_user"])} | {norm_identity(i) for i in cfg["git_identities"]}
    mine.discard("")
    cutoff = since.timestamp()
    files = []
    for path in PROJECTS_DIR.glob("*/*.jsonl"):
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            continue
    files.sort(reverse=True)
    # Everything touched since the last brief, plus the most recent few regardless —
    # so a quiet stretch still says where work stopped.
    candidates = [p for m, p in files if m >= cutoff] or []
    candidates += [p for _, p in files[:cfg["recent_sessions_floor"] * 3] if p not in candidates]
    cache, sessions, older = {}, [], 0
    for path in candidates:
        try:
            s = scan_session(path, since)
        except OSError as exc:
            errors.append(f"sessions: {path.name}: {exc}")
            continue
        if not s["last_ts"]:
            continue
        s["active_since_last_brief"] = parse_ts(s["last_ts"]) >= since
        if not s["active_since_last_brief"]:
            if older >= cfg["recent_sessions_floor"]:
                continue
        # The brief's own runs are not "work".
        if s["last_user_prompt"] and "daily-brief" in s["last_user_prompt"]:
            continue
        ids = git_identity(s["cwd"], cache)
        if ids:
            if not ids & mine:
                continue
            s["identity"] = "verified"
        else:
            s["identity"] = "unverified (cwd gone or not a git repo)"
        if not s["active_since_last_brief"]:
            older += 1
        sessions.append(s)
    sessions.sort(key=lambda s: s["last_ts"], reverse=True)
    return sessions


# ---------------------------------------------------------------------- state

def profile_dir(cfg):
    return STATE_DIR / "profiles" / re.sub(r"[^A-Za-z0-9_.-]", "_", cfg["name"])


def last_sent(cfg):
    f = profile_dir(cfg) / "last_sent"
    if not f.exists() and cfg["local_sessions"]:
        f = STATE_DIR / "last_sent"  # pre-profiles location
    return parse_ts(f.read_text().strip()) if f.exists() else None


def mark_sent(cfg):
    d = profile_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    (d / "last_sent").write_text(iso(now_utc()) + "\n")
    print(f"recorded last_sent={iso(now_utc())} for profile {cfg['name']}")


def folder_days(since, zone):
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(zone)
    except Exception:
        tz = timezone.utc
    first = since.astimezone(tz).date() - timedelta(days=1)
    last = now_utc().astimezone(tz).date()
    return [(first + timedelta(days=d)).isoformat() for d in range((last - first).days + 1)]


def build_context(cfg, since):
    """Windows and identities for the connector reads the skill performs."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(cfg["timezone"])
    except Exception:  # unknown zone or no tzdata: fall back to UTC
        tz = timezone.utc
    now = now_utc().astimezone(tz)
    # Twice-daily profiles get tomorrow's meetings in the evening run; a profile
    # with one send a day always gets that day's remaining meetings.
    tomorrow = len(cfg["schedule"]) > 1 and now.hour >= cfg["evening_after_hour"]
    day = now.date() + timedelta(days=1) if tomorrow else now.date()
    start = datetime.combine(day, dtime.min, tz) if tomorrow else now
    end = datetime.combine(day + timedelta(days=1), dtime.min, tz)
    aliases = sorted({a.lower() for a in [cfg["email_to"], *cfg["aliases"]] if a})
    return {
        "meetings": {
            "calendar_id": cfg["calendar_id"],
            "day": day.isoformat(),
            "label": "tomorrow" if tomorrow else "today",
            # Calendar's list_events wants local times without an offset, plus timeZone.
            "start_local": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "end_local": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "timezone": cfg["timezone"],
            "attendee_emails": aliases,
            "all_events": cfg["owner"],
        },
        "slack": {
            "channels": cfg["slack_channels"],
            "member_id": cfg["slack_member_id"],
            "own_dms": cfg["owner"],
            "after_unix": str(int(since.timestamp())),
            "after_date": (since.astimezone(tz).date() - timedelta(days=1)).isoformat(),
        },
        "email": {
            "mailbox": cfg["email_from"],
            "addresses": aliases,
            "whole_mailbox": cfg["owner"],
            "after_query": f"after:{int(since.timestamp())}",
        },
        # Meeting recordings, transcripts and notes that landed in Drive since the
        # last brief. Meetings that started up to a day before `since` still count:
        # Meet and Gemini often finish writing files an hour or more after the call.
        "recordings": {
            "meetings_folder_id": cfg["meetings_folder_id"],
            "folder_timezone": cfg["meetings_timezone"],
            "calendar_id": cfg["calendar_id"],
            "created_after": iso(since),
            # Every day from the one before `since` through today, in the folders'
            # own zone, so a late file finds its meeting's existing folder.
            "folder_days": folder_days(since, cfg["meetings_timezone"]),
            "events_start_local": (since.astimezone(tz) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
            "events_end_local": now.strftime("%Y-%m-%dT%H:%M:%S"),
            "timezone": cfg["timezone"],
            "attendee_emails": aliases,
            "all_meetings": cfg["owner"],
        },
    }


def resolve_since(arg, cfg):
    now = now_utc()
    floor = now - timedelta(hours=cfg["max_lookback_hours"])
    if arg and arg != "auto":
        ts = parse_ts(arg)
        if not ts:
            sys.exit(f"bad --since value: {arg}")
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    prev = last_sent(cfg)
    if prev is None:
        return now - timedelta(hours=24)
    return max(prev, floor)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile")
    ap.add_argument("--list-profiles", action="store_true")
    ap.add_argument("--skip-if-sent-within", type=float, metavar="HOURS",
                    help="print {\"skip\": true, ...} and exit if this profile was sent this recently")
    ap.add_argument("--since", default="auto")
    ap.add_argument("--config", type=Path, default=CONFIG_PATH)
    ap.add_argument("--mark-sent", action="store_true")
    ap.add_argument("--show-config", action="store_true")
    args = ap.parse_args()

    profiles = load_profiles(args.config)
    if args.list_profiles:
        print(json.dumps([{k: p[k] for k in ("name", "github_user", "email_to", "slack_user",
                                              "timezone", "schedule", "local_sessions")}
                          for p in profiles.values()], indent=2))
        return
    cfg = pick_profile(profiles, args.profile)
    if args.mark_sent:
        mark_sent(cfg)
        return
    if args.show_config:
        print(json.dumps({**cfg, "_path": str(args.config)}, indent=2))
        return
    if args.skip_if_sent_within is not None:
        prev = last_sent(cfg)
        if prev and now_utc() - prev < timedelta(hours=args.skip_if_sent_within):
            print(json.dumps({"skip": True, "profile": cfg["name"], "last_sent": iso(prev)}))
            return
    if not cfg["github_user"]:
        sys.exit("github_user not set and `gh api user` failed — is gh authenticated?")

    since = resolve_since(args.since, cfg)
    errors = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        gh_future = pool.submit(collect_github, cfg, since, errors)
        sessions_future = (pool.submit(collect_sessions, cfg, since, errors)
                           if cfg["local_sessions"] else None)
        github = gh_future.result()
        sessions = sessions_future.result() if sessions_future else None

    report = {
        "generated_at": iso(now_utc()),
        "since": iso(since),
        "profile": cfg["name"],
        "user": cfg["github_user"],
        "email_to": cfg["email_to"],
        "slack_user": cfg["slack_user"],
        "timezone": cfg["timezone"],
        "repos": cfg["repos"],
        "github": github,
        "sessions": sessions,
        "context": build_context(cfg, since),
        "errors": errors,
    }
    profile_dir(cfg).mkdir(parents=True, exist_ok=True)
    (profile_dir(cfg) / "last_collect.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
