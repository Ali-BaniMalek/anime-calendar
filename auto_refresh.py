#!/usr/bin/env python3
"""Log new episodes into shows.json by itself, between the weekly refreshes.

GitHub runs this several times an hour (.github/workflows/refresh.yml; GitHub
skips some scheduled runs, so nothing here depends on a run happening at a
particular time). It does the
mechanical part of README's "Weekly refresh" and nothing that needs judgment:

  1. For each airing show whose next episode is due, read the show's Nyaa RSS
     feed and log the exact post time of every new single episode ("released").
  2. Move "slot" to the next episode and re-derive "window" from the last 3
     regular posts (README rule).
  3. An episode more than LATE_HOURS late is taken as a break week: its date
     goes into "skip", so the rest of the season moves back a week. If the
     episode then turns up the same week, the skip is taken out again.
  4. When MAL gets an episode count for a show that had none, set
     "total_episodes" and drop "horizon".

It never touches: pending shows (premiere not announced), dropped shows,
whole-season drops ("per_drop"), shows marked "manual", titles, uploaders,
queries or notes. A release is only logged when it is the next episode in
line, under the same release name as before, and posted after the previous
one. Anything else is left for the weekly refresh, and build_ics.py's
warnings say what is waiting.

Usage: python3 auto_refresh.py [--dry-run] [--all] [--now 2026-11-14T12:00:00Z]
                               [--feeds DIR] [--notes FILE] [shows.json]
  --dry-run   print what would change, write nothing
  --all       read the feed of every airing show, not only the ones that are due
  --feeds     read feeds from DIR/<mal_id>.xml (and DIR/mal-<mal_id>.html)
              instead of the web: for tests
  --notes     also write the changes to FILE, one per line (for the commit message)
"""
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import build_ics
from build_ics import episodes, parse

HERE = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (compatible; release-calendar-refresh)"
PAUSE = 3              # seconds between requests; Nyaa refuses quick ones
LATE_HOURS = 36        # an episode this late is a break week
MAX_SKIPS = 3          # break weeks in a row added without a person looking
REGULAR_MINUTES = 180  # a post further than this from the usual time is a one-off

# "[Group] Release name - 07 (1080p) [hash].mkv", "... - 07v2 [1080p ...]",
# "... - 12 END [1080p ...]", "... - 03 (REPACK) [1080p ...]"
TITLE = re.compile(
    r"^\[(?P<group>[^\]]+)\]\s*(?P<name>.+)\s+-\s+(?P<num>\d{1,4})(?:v\d+)?"
    r"(?:\s+END)?(?:\s+\((?:REPACK|V\d+)\))?\s*(?:[\[(]|$)", re.I)
MAL_FIELD = re.compile(r'<span class="dark_text">\s*([^<:]+?)\s*:\s*</span>(.*?)</div>', re.S)

# build_ics warnings a change may leave behind: they describe the week, not a mistake.
SOFT_WARNINGS = ("was due", "MAL has no count", "reached the horizon",
                 "next episode is projected", "title is not in")


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- the web

class Web:
    """Reads Nyaa feeds and MAL pages, one request at a time."""

    def __init__(self, feeds_dir=None):
        self.dir = Path(feeds_dir) if feeds_dir else None
        self.calls = 0

    def _get(self, url):
        for attempt in range(2):
            time.sleep(PAUSE if attempt == 0 else 20)
            self.calls += 1
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=40) as r:
                    if r.status == 200:
                        return r.read().decode("utf-8", errors="replace")
            except Exception as e:  # network trouble is normal; the next run tries again
                print(f"  could not read {url.split('?')[0]}: {e}")
        return None

    def feed(self, show):
        """[(title, posted_utc)] for the show's Nyaa search, or None when it can't be read."""
        if self.dir:
            self.calls += 1
            p = self.dir / f"{show['mal_id']}.xml"
            text = p.read_text(encoding="utf-8") if p.exists() else None
        else:
            q = urllib.parse.quote_plus(show["nyaa_query"])
            text = self._get(f"https://nyaa.si/?page=rss&q={q}&s=id&o=desc")
        if text is None:
            return None
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            print("  the feed is not valid XML")
            return None
        if root.find("channel") is None:
            print("  the answer is not a feed")
            return None
        items = []
        for item in root.iter("item"):
            title, pub = item.findtext("title"), item.findtext("pubDate")
            if not title or not pub:
                continue
            try:
                dt = parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                continue
            if dt.tzinfo is None:  # "-0000" comes back without a zone; it is UTC
                dt = dt.replace(tzinfo=timezone.utc)
            items.append((title.strip(), dt.astimezone(timezone.utc)))
        return items

    def mal(self, mal_id):
        """{"episodes": int or None, "status": text} from the show's MAL page, or None."""
        if self.dir:
            self.calls += 1
            p = self.dir / f"mal-{mal_id}.html"
            text = p.read_text(encoding="utf-8") if p.exists() else None
        else:
            text = self._get(f"https://myanimelist.net/anime/{mal_id}")
        if not text:
            return None
        fields = {}
        for m in MAL_FIELD.finditer(text):
            value = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2))).strip()
            fields.setdefault(m.group(1).strip(), value)
        if "Status" not in fields:
            return None
        eps = re.match(r"^\d{1,4}$", fields.get("Episodes", ""))
        return {"episodes": int(eps.group(0)) if eps else None, "status": fields["Status"]}


# ---------------------------------------------------------------- reading a feed

def singles(items, show, after, now):
    """{file number: {release name, lowercase: (first post time, release name)}}

    Single episodes from the show's uploader, posted between after and now.
    Batches, ".5" recaps and specials don't match the pattern. A v2 or REPACK
    of the same number keeps the first post's time."""
    uploader = show["uploader"].lower()
    out = {}
    for title, posted in items:
        if posted < after or posted > now + timedelta(minutes=5):
            continue
        if re.search(r"\bbatch\b", title, re.I):
            continue
        m = TITLE.match(title)
        if not m or m.group("group").lower() != uploader:
            continue
        name = re.sub(r"\s+", " ", m.group("name")).strip()
        names = out.setdefault(int(m.group("num")), {})
        if name.lower() not in names or posted < names[name.lower()][0]:
            names[name.lower()] = (posted, name)
    return out


def log_releases(show, items, now):
    """Add the new episodes that are next in line. Returns [(episode, time)]."""
    released = show.setdefault("released", {})
    offset = show.get("file_offset", 0)
    last_ep = max((int(k) for k in released), default=None)
    expect = last_ep + 1 if last_ep is not None else show.get("first_episode", 1)
    if last_ep is not None:
        after = parse(released[str(last_ep)])
    else:
        # Nothing logged yet: only a post from around the announced premiere counts,
        # so last season's episode 1 under the same query is never taken.
        after = parse(show["slot"]["utc"]) - timedelta(days=4)
    last = show.get("total_episodes")
    found = singles(items, show, after, now)
    name = show.get("release_name")
    new = []
    while not (last and expect > last):
        names = found.get(expect + offset, {})
        if not names:
            break
        if name:
            hit = names.get(name.lower())
        else:
            hit = next(iter(names.values())) if len(names) == 1 else None
        if not hit:
            print(f"  episode {expect}: posted as {sorted(n for _, n in names.values())}, "
                  f"expected {name or 'one release name'}: left for the weekly refresh")
            break
        posted, hit_name = hit
        if posted < after:
            break
        name = hit_name
        released[str(expect)] = iso(posted)
        new.append((expect, posted))
        after, expect = posted, expect + 1
    if new:
        show["release_name"] = name
    return new


# ---------------------------------------------------------------- window and slot

def minute_of_day(dt):
    return dt.hour * 60 + dt.minute + dt.second / 60


def apart(a, b):
    """Minutes between two times of day, the short way round the clock."""
    d = abs(a - b) % 1440
    return min(d, 1440 - d)


def regular_posts(show):
    """(usual time of day, [post times within REGULAR_MINUTES of it]), oldest first.

    The usual time is the median post time; when two are equally central, the later post wins."""
    times = [parse(v) for _, v in sorted(show.get("released", {}).items(), key=lambda kv: int(kv[0]))]
    if not times:
        return None, []
    mins = [minute_of_day(t) for t in times]
    usual = min(reversed(mins), key=lambda c: sum(apart(c, m) for m in mins))
    return usual, [t for t in times if apart(minute_of_day(t), usual) <= REGULAR_MINUTES]


def derive_window(show):
    """("HH:MM-HH:MM", minutes) from the last 3 regular posts, rounded out to 5 minutes."""
    usual, regular = regular_posts(show)
    if not regular:
        return None
    rel = [((minute_of_day(t) - usual + 720) % 1440) - 720 for t in regular[-3:]]
    start = math.floor((usual + min(rel)) / 5) * 5
    end = math.ceil((usual + max(rel)) / 5) * 5
    if end <= start:
        end = start + 5
    text = "%02d:%02d-%02d:%02d" % ((start // 60) % 24, start % 60, (end // 60) % 24, end % 60)
    return text, end - start


def move_slot(show):
    """Point "slot" at the next unreleased episode: the show's usual weekday, at the window start."""
    released = show["released"]
    last_ep = max(int(k) for k in released)
    total = show.get("total_episodes")
    if total and last_ep >= total:
        return  # finished: nothing left to project
    last_dt = parse(released[str(last_ep)])
    hh, mm = map(int, show["window"].split("-")[0].split(":"))
    start_min = hh * 60 + mm
    _, regular = regular_posts(show)
    # The weekday of the window start each regular post belongs to (the day
    # before the post, when the window crosses midnight UTC).
    days = [(t - timedelta(minutes=(minute_of_day(t) - start_min) % 1440)).weekday()
            for t in regular[-3:]]
    weekday = max(set(days), key=lambda d: (days.count(d), max(i for i, x in enumerate(days) if x == d)))
    # 7 days on from an on-time post; after a late or early one, back to the usual weekday.
    for k in range(2, 9):
        day = (last_dt + timedelta(days=k)).date()
        if day.weekday() == weekday:
            break
    start = datetime(day.year, day.month, day.day, hh, mm, tzinfo=timezone.utc)
    show["slot"] = {"episode": last_ep + 1, "utc": iso(start)}
    if not total and show.get("horizon", 12) - last_ep <= 2:
        show["horizon"] = last_ep + 3  # README: keep the list more than 2 episodes ahead


def next_due(show):
    """(episode, expected start) of the next unreleased episode, or None when the show is finished."""
    return next(((ep, dt) for ep, dt, done in episodes(show) if not done), None)


def drop_false_breaks(show, new, before):
    """A skip added for an episode that then came the same week was a late episode, not a break."""
    if not show.get("skip"):
        return
    first_new = new[0][1].date()
    keep = [s for s in show["skip"]
            if not (before < parse(s).date() <= first_new and (first_new - parse(s).date()).days < 6)]
    if len(keep) != len(show["skip"]):
        show["skip"] = keep
        if not keep:
            del show["skip"]


# ---------------------------------------------------------------- one show

def refresh_show(show, web, now, everything=False):
    """Bring one show up to date. Returns a list of plain sentences on what changed."""
    if (show.get("pending") or show.get("dropped") or show.get("manual")
            or show.get("per_drop", 1) != 1):
        return []
    nxt = next_due(show)
    if nxt is None:
        return []
    late_by = now - (nxt[1] + timedelta(minutes=show.get("duration_minutes", 30)))
    very_late = late_by >= timedelta(hours=LATE_HOURS)
    if nxt[1] > now and not everything:
        return []  # not due yet
    print(f"{show['title']}: episode {nxt[0]} expected {nxt[1]:%a %d %b %H:%M} UTC")
    items = web.feed(show)
    if items is None:
        return []
    title, notes = show["title"], []
    released = show.get("released", {})
    before = parse(released[max(released, key=int)]).date() if released else parse(show["slot"]["utc"]).date()

    new = log_releases(show, items, now)
    if new:
        for ep, posted in new:
            notes.append(f"{title}: episode {ep} out {posted:%a %d %b %H:%M} UTC")
        drop_false_breaks(show, new, before)
        window = derive_window(show)
        if window:
            show["window"], show["duration_minutes"] = window
        if not show.get("total_episodes"):
            notes += mal_count(show, web)
        move_slot(show)
        return notes

    # Nothing new. Late enough to call it a break week?
    if not very_late or not released or nxt[1] > now:
        return notes
    recent = [s for s in show.get("skip", []) if parse(s).date() > before]
    if len(recent) >= MAX_SKIPS:
        return notes  # a long gap: the build's warning stays until someone looks
    if not show.get("total_episodes"):
        notes += mal_count(show, web)
        if next_due(show) is None:
            return notes  # MAL says the last one out was the finale
    day = nxt[1].date().isoformat()
    if day not in show.get("skip", []):
        show["skip"] = sorted(show.get("skip", []) + [day])
        notes.append(f"{title}: episode {nxt[0]} did not come on {nxt[1]:%a %d %b}, "
                     "counted as a break week")
    return notes


def mal_count(show, web):
    """Set total_episodes once MAL has a count that fits what has been released."""
    info = web.mal(show["mal_id"])
    if not info or not info["episodes"]:
        return []
    last_ep = max((int(k) for k in show.get("released", {})), default=0)
    if info["episodes"] < last_ep:
        return []  # MAL counts differently from our numbering: needs a person
    show["total_episodes"] = info["episodes"]
    show.pop("horizon", None)
    return [f"{show['title']}: MAL now lists {info['episodes']} episodes"]


# ---------------------------------------------------------------- all shows

def hard_warnings(show, now):
    """The build warnings for one show that mean the entry itself is wrong."""
    prefix = len(show["title"]) + 2
    return {w[prefix:] for w in build_ics.check({"shows": [show]}, now)
            if not any(soft in w[prefix:] for soft in SOFT_WARNINGS)}


def refresh(data, web, now, everything=False):
    """Refresh every show in data (in place). Returns the list of changes."""
    changes = []
    for show in data["shows"]:
        saved = json.dumps(show)
        try:
            notes = refresh_show(show, web, now, everything)
            extra = hard_warnings(show, now) - hard_warnings(json.loads(saved), now) if notes else None
        except Exception as e:  # one odd show must not stop the others
            print(f"  {show['title']}: left alone after an error: {e!r}")
            notes, extra = None, None
        if extra:
            print(f"  {show['title']}: change dropped, it would add a warning: {sorted(extra)}")
        if notes is None or extra:
            show.clear()
            show.update(json.loads(saved))
            continue
        changes += notes
    if changes:
        data["updated"] = now.strftime("%Y-%m-%d")
    return changes


def main(argv):
    args = argv[1:]
    dry = "--dry-run" in args
    everything = "--all" in args
    now, feeds, notes_file, src = datetime.now(timezone.utc), None, None, HERE / "shows.json"
    rest = [a for a in args if a not in ("--dry-run", "--all")]
    while rest:
        a = rest.pop(0)
        if a == "--now":
            now = parse(rest.pop(0))
        elif a == "--feeds":
            feeds = rest.pop(0)
        elif a == "--notes":
            notes_file = Path(rest.pop(0))
        else:
            src = Path(a)
    raw = src.read_text(encoding="utf-8")
    data = json.loads(raw)
    web = Web(feeds)
    changes = refresh(data, web, now, everything)
    print(f"\n{len(changes)} change(s), {web.calls} request(s)")
    for line in changes:
        print(f"  {line}")
    if notes_file:
        notes_file.write_text("".join(line + "\n" for line in changes), encoding="utf-8")
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if changes and not dry and text != raw:
        src.write_text(text, encoding="utf-8")
    return changes


if __name__ == "__main__":
    main(sys.argv)
