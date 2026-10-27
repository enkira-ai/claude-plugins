#!/usr/bin/env python3
"""Collect the raw facts for a daily brief and print them as one JSON document.

One config can hold several profiles (one per recipient); each run collects for
one profile.

Sources:
  * GitHub (via the `gh` CLI): PRs awaiting the user's review, the user's own open
    PRs with CI/review state, assigned issues, recent mentions, the user's recent
    activity (commits, merged PRs, closed issues), and every issue/PR created or
    merged in the watched repos since the last brief.
  * For each repo in the profile's `digest_repos`: every commit that landed on
    its default branch since the head the last sent brief reported, the files
    each one changed, and the text of the design documents that changed (new
    documents as they stand at the head, edited ones as one diff over the range)
    — the repo's daily progress and design digest, which PR lists miss when
    work lands directly.
  * Optional per profile: `trackers` (an umbrella issue's sub-issue tree, e.g. a
    refactor's epics and their children, with what closed or opened since the
    last brief), `topics` (issues and PRs anywhere in the org that mention the
    person's subjects, kept only from repos the person can read), and
    `agent_state_repos` (the `.planning/STATE.md` that GSD-style agent sessions
    keep, on the default branch and the branches the person pushed lately —
    where their agent sessions stopped, for people whose sessions don't run on
    this machine).
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
  collect.py --profile NAME --mark-meetings-reported ID,ID   # meeting folders this brief covered
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
    "schedule_timezone": "",      # zone the schedule times are in; empty → timezone
    "days": [],                   # weekdays to send on (["Mon", "Thu"]); empty → every day
    "max_lookback_hours": 36,     # cap for --since auto (a `days` profile defaults to its longest gap)
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
    # Repo digest: daily progress and design changes pushed to these repos
    "digest_repos": [],           # "owner/name" or bare "name"; empty → no digest section
    "digest_doc_chars": 4000,     # per design document: its text if new, its diff if edited
    "digest_total_chars": 40000,  # all design documents together, per repo
    # Progress of a tracked effort, the person's subjects, and their agent sessions
    "trackers": [],               # [{"name": …, "repo": "panbot", "issue": 1258}] umbrella issues
    "topics": [],                 # [{"name": "Menu V5", "keywords": ["Menu V5", "menu-v5"]}]
    "agent_state_repos": [],      # repos whose .planning/STATE.md records their agent sessions
}

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

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
        cfg["digest_repos"] = [r if "/" in r else f"{cfg['org']}/{r}" for r in cfg["digest_repos"]]
        cfg["agent_state_repos"] = [r if "/" in r else f"{cfg['org']}/{r}"
                                    for r in cfg["agent_state_repos"]]
        cfg["schedule_timezone"] = cfg["schedule_timezone"] or cfg["timezone"]
        days = []
        for d in cfg["days"]:
            key = str(d).strip()[:3].title()
            if key not in WEEKDAYS:
                sys.exit(f"profile {cfg['name']!r}: unknown day {d!r} (use {', '.join(WEEKDAYS)})")
            days.append(key)
        cfg["days"] = sorted(set(days), key=WEEKDAYS.index)
        # A profile sent on some weekdays only must look back over its longest gap
        # (Thu → Mon is four days), or --since auto would drop the start of it.
        if cfg["days"] and "max_lookback_hours" not in entry and "max_lookback_hours" not in shared:
            idx = [WEEKDAYS.index(d) for d in cfg["days"]]
            gaps = [(idx[(i + 1) % len(idx)] - idx[i]) % 7 or 7 for i in range(len(idx))]
            cfg["max_lookback_hours"] = max(36, 24 * max(gaps) + 12)
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


def gh_raw(args, errors, label):
    """Plain-text output of a gh call (e.g. a file's raw contents), or None."""
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as exc:
        errors.append(f"{label}: {exc}")
        return None
    if out.returncode != 0:
        errors.append(f"{label}: {out.stderr.strip()[:300]}")
        return None
    return out.stdout


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


# ---------------------------------------------------------------- repo digest

# Documents carry the design: plans, requirements, roadmaps, ADRs, specs and agent
# instructions. Everything else is summarized from its path and size.
DESIGN_PATH = re.compile(r"\.(md|mdx|rst|adoc)$", re.I)
DIGEST_MAX_COMMITS = 100        # commits read in detail (files), newest first
DIGEST_MAX_LISTED = 1000        # commits listed at all; beyond this they're counted, not listed
# A commit touching this many files is an import or a mass move (e.g. vendored
# docs); its files are listed, but their text doesn't spend the digest's budget.
DIGEST_BULK_FILES = 40
DIGEST_MAX_FILES = 150


def collect_repo_digest(repo, since, cfg, errors, prev_head=None):
    """Collect one repo's digest; `complete` says whether the whole range was read,
    so a failed read never moves the checkpoint past work nobody reported."""
    own = []
    try:
        out = _repo_digest(repo, since, cfg, own, prev_head)
    finally:
        errors.extend(own)
    if out is not None:
        # A design document that couldn't be read is reported, but doesn't hold
        # the range back: its commits and files were still collected.
        out["complete"] = bool(out.get("head")) and all(e.startswith("digest file ") for e in own)
    return out


def _repo_digest(repo, since, cfg, errors, prev_head):
    """What landed on `repo`'s default branch since the last brief: the commits,
    the files they changed, and the design documents' text, for a progress digest.

    The window is the range from the head the last sent brief reported
    (`prev_head`) to the branch's head now, so a commit counts when it lands,
    whatever its date. Without a recorded head (the first digest, or history
    rewritten past it), the range starts at the branch as it stood at `since`."""
    out_since = iso(since)
    meta = gh_json(["api", f"repos/{repo}"], errors, f"digest {repo}")
    if not meta:
        return None
    branch = meta.get("default_branch") or "main"
    out = {"repo": repo, "url": meta.get("html_url"), "description": meta.get("description"),
           "default_branch": branch, "head": None, "base": None, "base_from": None,
           "window_start": out_since, "checkpoint_reset": None,
           "commits": [], "commits_total": 0, "omitted_commits": 0,
           "files": [], "files_changed": 0, "design_docs": []}
    tip = gh_json(["api", f"repos/{repo}/commits/{branch}"], errors, f"digest head {repo}")
    head = (tip or {}).get("sha")
    if not head:
        return out
    out["head"] = head
    if prev_head == head:
        out["base"], out["base_from"] = head, "last brief"
        return out

    def compare(base, errs, page=1):
        # The first page also carries the range's files; later pages only commits.
        return gh_json(["api", f"repos/{repo}/compare/{base}...{head}?per_page=100&page={page}"],
                       errs, f"digest compare {repo}") or None

    cmp = None
    if prev_head:
        # A saved head that can no longer be compared (history rewritten, branch
        # recreated) is expected to fail: note it and fall back, so a successful
        # fallback can become the new checkpoint instead of failing forever.
        probe = []
        cmp = compare(prev_head, probe)
        if cmp and cmp.get("status") in ("ahead", "identical"):
            out["base"], out["base_from"] = prev_head, "last brief"
        elif cmp and (cmp.get("merge_base_commit") or {}).get("sha"):
            # History was rewritten past the last brief's head: start where the two meet.
            out["base"], out["base_from"] = cmp["merge_base_commit"]["sha"], "merge base with last brief"
            out["checkpoint_reset"] = f"history rewritten past {prev_head[:7]}"
            cmp = compare(out["base"], errors)
        elif probe and not all(re.search(r"HTTP (404|422)\b", e) for e in probe):
            # A transient failure (5xx, rate limit, timeout) says nothing about the
            # checkpoint: digest the window anyway, but keep the checkpoint for a retry.
            errors.extend(probe)
            cmp = None
        else:
            # Confirmed gone: the saved commit no longer exists or shares no history.
            out["checkpoint_reset"] = (f"saved head {prev_head[:7]} can't be compared"
                                       + (f" ({probe[0].split(': ', 1)[-1][:120]})" if probe else ""))
            cmp = None
    seen = {head: tip}
    if not out["base"]:
        # Walk the branch's first parents back to the commit it pointed at when
        # the window opened; a merged branch's own older commits never qualify.
        sha = head
        for _ in range(DIGEST_MAX_LISTED):
            c = seen.get(sha) or gh_json(["api", f"repos/{repo}/commits/{sha}"], errors,
                                         f"digest commit {repo}@{sha[:7]}")
            if not c:
                break
            seen[sha] = c
            if (parse_ts(((c.get("commit") or {}).get("committer") or {}).get("date")) or since) < since:
                out["base"], out["base_from"] = sha, "branch at window start"
                break
            parents = c.get("parents") or []
            if not parents:
                out["base_from"] = "repository created in window"
                break
            sha = parents[0]["sha"]
        else:
            errors.append(f"digest base {repo}: more than {DIGEST_MAX_LISTED} commits since "
                          f"{out_since}; window start not reached")
            return out
        if out["base"]:
            cmp = compare(out["base"], errors)

    # List every commit in the range (paginated); only the newest are read in detail.
    if cmp:
        # Pages run oldest first, so past the cap read the last pages: the newest
        # commits (the head included) are the ones listed, the oldest are counted.
        total = cmp.get("total_commits") or 0
        last = max(1, -(-total // 100))
        first = max(0, total - DIGEST_MAX_LISTED) // 100 + 1  # page of the oldest commit kept
        listed = list(cmp.get("commits") or []) if first == 1 else []
        for page in range(max(first, 2), last + 1):
            more = (compare(out["base"], errors, page) or {}).get("commits") or []
            if not more:
                break
            listed += more
        listed = listed[-DIGEST_MAX_LISTED:][::-1]
    else:  # the repository was created in the window: everything reachable is new
        listed, page = [], 0
        while len(listed) < DIGEST_MAX_LISTED:
            page += 1
            more = gh_json(["api", f"repos/{repo}/commits?sha={head}&per_page=100&page={page}"],
                           errors, f"digest commits {repo}") or []
            listed += more
            if len(more) < 100:
                break
        total = len(listed)
    out["commits_total"] = max(total, len(listed))
    # Past DIGEST_MAX_LISTED the oldest are counted, not listed; the brief says so.
    out["omitted_commits"] = out["commits_total"] - len(listed)
    if not listed:
        return out
    summaries, listed = listed[DIGEST_MAX_COMMITS:], listed[:DIGEST_MAX_COMMITS]

    with ThreadPoolExecutor(max_workers=6) as pool:
        details = list(pool.map(
            lambda c: seen.get(c["sha"]) or gh_json(["api", f"repos/{repo}/commits/{c['sha']}"],
                                                    errors, f"digest commit {repo}@{c['sha'][:7]}") or c,
            listed))

    files = {}
    for d in reversed(details):  # oldest first: `status` keeps the first change, `removed` the last
        commit = d.get("commit") or {}
        message = commit.get("message") or ""
        subject, _, body = message.partition("\n")
        changed = d.get("files") or []
        bulk = len(changed) >= DIGEST_BULK_FILES
        out["commits"].append({
            "sha": (d.get("sha") or "")[:7], "url": d.get("html_url"),
            "author": (d.get("author") or {}).get("login") or (commit.get("author") or {}).get("name"),
            "date": (commit.get("committer") or {}).get("date"),
            "subject": subject[:200], "body": trim(body, 800),
            "additions": (d.get("stats") or {}).get("additions"),
            "deletions": (d.get("stats") or {}).get("deletions"),
            "files": [f.get("filename") for f in changed[:20]],
            "files_changed": len(changed), "bulk": bulk,
        })
        for f in changed:
            path = f.get("filename")
            entry = files.setdefault(path, {"path": path, "status": f.get("status"),
                                            "additions": 0, "deletions": 0, "commits": 0,
                                            "only_bulk": True,
                                            "design": bool(DESIGN_PATH.search(path or ""))})
            entry["additions"] += f.get("additions") or 0
            entry["deletions"] += f.get("deletions") or 0
            entry["commits"] += 1
            entry["only_bulk"] = entry["only_bulk"] and bulk
            # A file deleted and restored in the window exists at the head.
            entry["removed"] = f.get("status") == "removed"
            if f.get("previous_filename"):
                entry["previous_path"] = f["previous_filename"]
    out["commits"].reverse()  # newest first, like the brief reads
    for c in summaries:  # older commits beyond the detailed ones: what and who, no files
        commit = c.get("commit") or {}
        out["commits"].append({
            "sha": (c.get("sha") or "")[:7], "url": c.get("html_url"),
            "author": (c.get("author") or {}).get("login") or (commit.get("author") or {}).get("name"),
            "date": (commit.get("committer") or {}).get("date"),
            "subject": (commit.get("message") or "").split("\n")[0][:200], "detailed": False})
    for e in files.values():
        if e.pop("removed"):
            e["status"] = "removed"
        elif e["status"] == "removed":  # existed before the window, deleted, then restored
            e["status"] = "modified"

    # The range's own file list is the net change from base to head, which beats
    # replaying commits; it holds at most 300 files and leaves out large patches.
    cmp_files = {f.get("filename"): f for f in (cmp or {}).get("files") or []}
    complete = cmp is not None and len(cmp_files) < 300
    for path, e in files.items():
        if path in cmp_files:
            e["status"] = cmp_files[path].get("status") or e["status"]
        elif complete:
            e["status"] = "unchanged"  # changed and changed back within the window
    patches = {k: f.get("patch") for k, f in cmp_files.items()}

    # The budget goes first to the documents worked on most, then to those
    # nearest the root (plans and briefs before deep reference material).
    ranked = sorted(files.values(), key=lambda e: (
        not e["design"], e["only_bulk"], -e["commits"], e["path"].count("/"), e["path"]))
    out["files_changed"] = len(ranked)
    out["files"] = ranked[:DIGEST_MAX_FILES]

    # Design text: a new document as it stands at the head; an edited one as one
    # diff across the range, or whole at the head when the range left it out.
    budget = cfg["digest_total_chars"]
    for e in out["files"]:
        if (not e["design"] or e["only_bulk"] or e["status"] in ("removed", "unchanged")
                or budget <= 0):
            continue
        limit = min(cfg["digest_doc_chars"], budget)
        text, kind = (patches.get(e["path"]), "diff") if e["status"] != "added" else (None, "text")
        if not text:
            text = gh_raw(["api", "-H", "Accept: application/vnd.github.raw+json",
                           f"repos/{repo}/contents/{e['path']}?ref={head}"],
                          errors, f"digest file {repo}:{e['path']}")
            kind = "text"
        if not text:
            continue
        doc = {"path": e["path"], "status": e["status"], "kind": kind, "content": trim(text, limit)}
        budget -= len(doc["content"])
        out["design_docs"].append(doc)
    return out


def digest_heads(cfg):
    """Per repo, where this profile's next digest starts: {"head": SHA} the last
    sent brief reported in full, or {"since": ISO} when no digest of it has yet
    been read in full (the window start to keep until one is)."""
    try:
        raw = json.loads((profile_dir(cfg) / "digest_heads.json").read_text())
    except (OSError, ValueError):
        return {}
    return {repo: v if isinstance(v, dict) else {"head": v} for repo, v in raw.items()}


def record_digest_heads(cfg):
    """On --mark-sent, move each repo's checkpoint to the head the sent brief read
    in full. An incomplete read keeps the old checkpoint; with none yet, it keeps
    the window start, so the next brief covers the same work again."""
    try:
        report = json.loads((profile_dir(cfg) / "last_collect.json").read_text())
    except (OSError, ValueError):
        return
    marks = digest_heads(cfg)
    for repo, d in (report.get("repo_digests") or {}).items():
        if d.get("head") and d.get("complete"):
            marks[repo] = {"head": d["head"]}
        elif not (marks.get(repo) or {}).get("head") and d.get("window_start"):
            prior = (marks.get(repo) or {}).get("since")
            marks[repo] = {"since": min(filter(None, (prior, d["window_start"])))}
    if marks:
        (profile_dir(cfg) / "digest_heads.json").write_text(json.dumps(marks, indent=2) + "\n")


def collect_digests(cfg, since, errors):
    if not cfg["digest_repos"]:
        return None
    with ThreadPoolExecutor(max_workers=3) as pool:
        marks = digest_heads(cfg)

        def one(repo):
            mark = marks.get(repo) or {}
            start = min(since, parse_ts(mark.get("since")) or since)
            return collect_repo_digest(repo, start, cfg, errors, mark.get("head"))
        found = list(pool.map(one, cfg["digest_repos"]))
    return {d["repo"]: d for d in found if d}


# ------------------------------------------------- trackers, topics, agent state

TRACKER_MAX_OPEN = 15       # open children listed per epic; the rest are counted
TOPIC_MAX_PAGES = 10        # the search API returns at most 1000 results


def gh_api_list(path, errors, label):
    """One page (100) of a REST list endpoint; `truncated` when it may have more."""
    items = gh_json(["api", f"{path}{'&' if '?' in path else '?'}per_page=100"], errors, label)
    return (items if isinstance(items, list) else []), len(items or []) >= 100


def slim_issue_rest(it):
    return {"repo": "/".join((it.get("repository_url") or "").split("/")[-2:]) or None,
            "number": it.get("number"), "title": it.get("title"), "url": it.get("html_url"),
            "state": it.get("state"), "state_reason": it.get("state_reason"),
            "created": it.get("created_at"), "updated": it.get("updated_at"),
            "closed": it.get("closed_at"),
            "assignees": [a.get("login") for a in it.get("assignees") or []],
            "labels": [l.get("name") for l in it.get("labels") or []],
            "is_pr": bool(it.get("pull_request")),
            "sub_issues": it.get("sub_issues_summary")}


def collect_tracker(tracker, since, cfg, errors):
    """An umbrella issue, its sub-issues (the epics) and theirs (the work items),
    with what closed or opened since the last brief."""
    repo = tracker.get("repo") or ""
    repo = repo if "/" in repo else f"{cfg['org']}/{repo}"
    num = tracker.get("issue")
    label = f"tracker {repo}#{num}"
    root = gh_json(["api", f"repos/{repo}/issues/{num}"], errors, label)
    if not root:
        return None
    epics, truncated = gh_api_list(f"repos/{repo}/issues/{num}/sub_issues", errors, label)

    def epic(it):
        e = slim_issue_rest(it)
        # A sub-issue can live in another repository; read its children there.
        own = e["repo"] or repo
        kids, more = gh_api_list(f"repos/{own}/issues/{e['number']}/sub_issues", errors,
                                 f"{label} → {own}#{e['number']}")
        kids = [slim_issue_rest(k) for k in kids]
        e["children_truncated"] = more
        e["closed_since"] = [k for k in kids if k["state"] == "closed"
                             and (parse_ts(k["closed"]) or since) >= since and k["closed"]]
        e["opened_since"] = [k for k in kids if k["created"] and parse_ts(k["created"]) >= since]
        open_kids = sorted((k for k in kids if k["state"] == "open"),
                           key=lambda k: k["updated"] or "", reverse=True)
        e["open_children"] = open_kids[:TRACKER_MAX_OPEN]
        e["open_children_omitted"] = max(0, len(open_kids) - TRACKER_MAX_OPEN)
        e["closed_children"] = sum(1 for k in kids if k["state"] == "closed")
        return e

    with ThreadPoolExecutor(max_workers=4) as pool:
        tree = list(pool.map(epic, epics))
    r = slim_issue_rest(root)
    return {"name": tracker.get("name") or r["title"], "repo": repo, "root": r,
            "epics": tree, "epics_truncated": truncated,
            "closed_since": [e for e in tree if e["state"] == "closed" and e["closed"]
                             and parse_ts(e["closed"]) >= since],
            "opened_since": [e for e in tree if e["created"] and parse_ts(e["created"]) >= since]}


def collect_trackers(cfg, since, errors):
    if not cfg["trackers"]:
        return None
    found = [collect_tracker(t, since, cfg, errors) for t in cfg["trackers"]]
    return [t for t in found if t]


def readable_repos(user, repos, errors):
    """The repos `user` can read, from the collaborator-permission endpoint; a repo
    whose permission can't be read is treated as unreadable."""
    def perm(repo):
        try:
            out = subprocess.run(["gh", "api", f"repos/{repo}/collaborators/{user}/permission",
                                  "-q", ".permission"], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"permission {repo}: {exc}")
            return repo, False
        if out.returncode != 0:
            errors.append(f"permission {repo}: {out.stderr.strip()[:200]}")
            return repo, False
        return repo, out.stdout.strip() in ("admin", "maintain", "write", "triage", "read")
    with ThreadPoolExecutor(max_workers=6) as pool:
        return {r for r, ok in pool.map(perm, sorted(repos)) if ok}


def collect_topics(cfg, since, errors):
    """Issues and PRs anywhere in the org, updated since the last brief, that
    mention one of the person's topics. Items from repos the person can't read
    are dropped, so a brief never leaks a repo they have no access to."""
    if not cfg["topics"]:
        return None
    day = since.strftime("%Y-%m-%d")
    excluded = {r.lower() for r in cfg["exclude_repos"]}

    def search(topic):
        # `gh search issues` quotes an OR query as one phrase, so call the API.
        # Read every page (the search API stops at 1000 results), so the window
        # never advances past matches that weren't read.
        words = [w.replace('"', "") for w in topic.get("keywords") or [topic.get("name")] if w][:6]
        query = f"org:{cfg['org']} updated:>={day} (" + " OR ".join(f'"{w}"' for w in words) + ")"
        items, total, ok = [], 0, True
        for page in range(1, TOPIC_MAX_PAGES + 1):
            errs = []
            found = gh_json(["api", "-X", "GET", "search/issues", "-f", f"q={query}",
                             "-f", "sort=updated", "-f", "per_page=100", "-f", f"page={page}"],
                            errs, f"topic {topic.get('name')} page {page}")
            errors.extend(errs)
            if errs or not isinstance(found, dict):
                ok = False
                break
            total = found.get("total_count") or 0
            items.extend(found.get("items") or [])
            if len(items) >= total or not found.get("items"):
                break
        complete = ok and len(items) >= total
        return topic, items, complete, total

    def repo_name(i):
        return "/".join((i.get("repository_url") or "").split("/")[-2:])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(search, cfg["topics"]))
    repos = {repo_name(i) for _, items, _, _ in results for i in items}
    repos = {r for r in repos if r and r.lower() not in excluded}
    readable = readable_repos(cfg["github_user"], repos, errors)
    out = {}
    for topic, items, complete, total in results:
        kept = []
        for i in items:
            repo = repo_name(i)
            if repo not in readable or (parse_ts(i.get("updated_at")) or since) < since:
                continue
            s = slim_issue_rest(i)
            s.update({"repo": repo, "author": (i.get("user") or {}).get("login"),
                      "body": trim(i.get("body"), 500),
                      "new": bool(parse_ts(i.get("created_at")) and parse_ts(i["created_at"]) >= since),
                      "closed_since": bool(parse_ts(i.get("closed_at"))
                                           and parse_ts(i["closed_at"]) >= since)})
            kept.append(s)
        out[topic.get("name") or ", ".join(topic.get("keywords") or [])] = {
            "keywords": topic.get("keywords") or [], "items": kept,
            "complete": complete, "matches": total,
            "dropped_unreadable": sum(1 for i in items if repo_name(i) not in readable)}
    return out


STATE_FIELDS = ("status", "stopped_at", "last_updated", "last_activity", "last_activity_desc",
                "milestone", "milestone_name", "current_phase", "current_phase_name")


def parse_state_md(text):
    """The front matter fields and the 'Current Position' section of a GSD STATE.md."""
    fields, body = {}, text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            km = re.match(r"^([a-z_]+):\s*(.*)$", line)
            if km and km.group(1) in STATE_FIELDS:
                fields[km.group(1)] = trim(km.group(2).strip().strip('"'), 600)
        prog = re.search(r"^progress:\n((?:[ \t]+.*\n?)+)", m.group(1), re.M)
        if prog:
            fields["progress"] = {k: v.strip() for k, v in
                                  re.findall(r"^\s+([a-z_]+):\s*(.*)$", prog.group(1), re.M)}
    pos = re.search(r"^## Current Position\s*\n(.*?)(?=^## |\Z)", body, re.S | re.M)
    if pos:
        fields["current_position"] = trim(pos.group(1), 800)
    return fields


def collect_agent_state(cfg, since, errors):
    """Where the person's agent sessions stopped, read from the STATE.md their
    GSD-style sessions keep: on the default branch, and on each branch they
    pushed in the last month (newest first, at most five per repo)."""
    if not cfg["agent_state_repos"]:
        return None
    user = cfg["github_user"]

    def one(repo):
        meta = gh_json(["api", f"repos/{repo}"], errors, f"agent state {repo}")
        if not meta:
            return None
        default = meta.get("default_branch") or "main"
        acts, _ = gh_api_list(f"repos/{repo}/activity?actor={user}&time_period=month",
                              errors, f"agent state {repo} activity")
        refs, deleted = {}, set()
        for a in acts:  # newest first
            ref = (a.get("ref") or "").removeprefix("refs/heads/")
            if not ref or ref == (a.get("ref") or ""):
                continue
            if a.get("activity_type") == "branch_deletion":
                deleted.add(ref)
            elif ref not in deleted and ref not in refs:
                refs[ref] = a.get("timestamp")
        branches = [(default, refs.pop(default, None))] + list(refs.items())[:5]
        seen, found = set(), []
        for ref, pushed in branches:
            commit = gh_json(["api", f"repos/{repo}/commits/{ref}"], [], "")
            text = gh_raw(["api", "-H", "Accept: application/vnd.github.raw+json",
                           f"repos/{repo}/contents/.planning/STATE.md?ref={ref}"], [], "")
            entry = {"ref": ref, "default": ref == default, "last_push_by_user": pushed,
                     "last_commit": {
                         "sha": (commit.get("sha") or "")[:7] if commit else None,
                         "date": ((commit or {}).get("commit") or {}).get("committer", {}).get("date"),
                         "author": ((commit or {}).get("author") or {}).get("login"),
                         "message": (((commit or {}).get("commit") or {}).get("message") or "")
                         .split("\n")[0][:200],
                         "url": (commit or {}).get("html_url")}}
            if text:
                key = text.strip()
                entry["state"] = parse_state_md(text) if key not in seen else "same as above"
                entry["state_url"] = f"https://github.com/{repo}/blob/{ref}/.planning/STATE.md"
                seen.add(key)
            found.append(entry)
        return {"repo": repo, "url": meta.get("html_url"), "default_branch": default,
                "branches": found,
                "has_state": any("state" in b for b in found)}

    with ThreadPoolExecutor(max_workers=3) as pool:
        return [r for r in pool.map(one, cfg["agent_state_repos"]) if r]


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
    record_digest_heads(cfg)
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


def reported_meetings(cfg):
    path = profile_dir(cfg) / "reported_meetings.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return []


def mark_meetings_reported(cfg, ids):
    """Remember which meeting folders this profile was told about (newest 300)."""
    seen = [i for i in reported_meetings(cfg) if i not in ids] + ids
    d = profile_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    (d / "reported_meetings.json").write_text(json.dumps(seen[-300:]))
    print(f"recorded {len(ids)} reported meeting folder(s) for profile {cfg['name']}")


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
            "already_reported": reported_meetings(cfg),
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
        # A first brief covers a day, or the whole gap for a profile sent on some days only.
        return now - timedelta(hours=cfg["max_lookback_hours"] if cfg["days"] else 24)
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
    ap.add_argument("--mark-meetings-reported", metavar="IDS",
                    help="comma-separated meeting folder IDs this profile's brief covered")
    ap.add_argument("--show-config", action="store_true")
    args = ap.parse_args()

    profiles = load_profiles(args.config)
    if args.list_profiles:
        print(json.dumps([{k: p[k] for k in ("name", "github_user", "email_to", "slack_user",
                                              "timezone", "schedule", "schedule_timezone",
                                              "days", "local_sessions")}
                          for p in profiles.values()], indent=2))
        return
    cfg = pick_profile(profiles, args.profile)
    if args.mark_sent or args.mark_meetings_reported is not None:
        if args.mark_meetings_reported:
            mark_meetings_reported(cfg, [i for i in args.mark_meetings_reported.split(",") if i])
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
    with ThreadPoolExecutor(max_workers=6) as pool:
        gh_future = pool.submit(collect_github, cfg, since, errors)
        digest_future = pool.submit(collect_digests, cfg, since, errors)
        tracker_future = pool.submit(collect_trackers, cfg, since, errors)
        topics_future = pool.submit(collect_topics, cfg, since, errors)
        state_future = pool.submit(collect_agent_state, cfg, since, errors)
        sessions_future = (pool.submit(collect_sessions, cfg, since, errors)
                           if cfg["local_sessions"] else None)
        github = gh_future.result()
        digests = digest_future.result()
        trackers = tracker_future.result()
        topics = topics_future.result()
        agent_state = state_future.result()
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
        "repo_digests": digests,
        "trackers": trackers,
        "topics": topics,
        "agent_state": agent_state,
        "context": build_context(cfg, since),
        "errors": errors,
    }
    profile_dir(cfg).mkdir(parents=True, exist_ok=True)
    (profile_dir(cfg) / "last_collect.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
