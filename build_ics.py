#!/usr/bin/env python3
"""Build the anime release calendar (.ics) from shows.json.

One event per episode, no recurring rules. Episodes already out use the real
Nyaa post time from "released"; upcoming ones are projected weekly from the
show's "slot" anchor, shifted by any "skip" weeks. The list ends at MAL's
episode count; when MAL has no count yet, it runs to "horizon" episodes and
says the count is unconfirmed.

A show that is switched on before its first episode (premiere day and
broadcast time announced) has an estimated window, and its events say so.

After writing the feed it prints the coming week and a list of warnings for
anything in shows.json that looks wrong (see check()). A refresh is done only
when that list is empty or every line in it is explained.

Usage: python3 build_ics.py [shows.json] [out.ics]
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "shows.json"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "anime-releases.ics"


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def fmt(dt):
    return dt.strftime("%Y%m%dT%H%M%SZ")


def esc(text):
    return (text.replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def fold(line):
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def episodes(show):
    """Yield (mal_episode, start_utc, released_bool) for one show."""
    released = {int(k): parse(v) for k, v in show.get("released", {}).items()}
    slot = show["slot"]
    anchor_ep, anchor_dt = slot["episode"], parse(slot["utc"])
    per_drop = show.get("per_drop", 1)
    skips = sorted(parse(s) for s in show.get("skip", []))
    last = show.get("total_episodes") or show.get("horizon", 12)
    first = show.get("first_episode", 1)

    for ep in range(first, last + 1):
        if ep in released:
            yield ep, released[ep], True
            continue
        if ep < anchor_ep:
            continue  # aired before tracking began and not logged
        weeks = (ep - anchor_ep) // per_drop
        dt = anchor_dt + timedelta(weeks=weeks)
        for s in skips:  # each skipped week pushes the rest back a week
            # A break dated before the slot is history: the slot was already
            # set after it, so it must not push the episodes again.
            if anchor_dt.date() <= s.date() <= dt.date():
                dt += timedelta(weeks=1)
        yield ep, dt, False


def window_minutes(window):
    """Length of a "HH:MM-HH:MM" window in minutes."""
    (h1, m1), (h2, m2) = (map(int, p.split(":")) for p in window.split("-"))
    return (h2 * 60 + m2 - h1 * 60 - m1) % (24 * 60)


def check(data, now):
    """Return a list of things in shows.json that look wrong."""
    out, seen = [], set()
    for show in data["shows"]:
        title = show["title"]

        def warn(msg):
            out.append(f"{title}: {msg}")

        if show["mal_id"] in seen:
            warn("mal_id is used twice")
        seen.add(show["mal_id"])
        if (re.search(r"\d(st|nd|rd|th) Season| (II|III|IV)$", title)
                or re.search(r"(?<! -) Season \d", title)):
            warn("title is not in the '<series> - Season N' format")

        released = {int(k): parse(v) for k, v in show.get("released", {}).items()}
        eps = sorted(released)
        if show.get("pending"):
            if eps:
                warn("is pending but has released episodes")
            elif parse(show["slot"]["utc"]) < now - timedelta(days=1):
                warn(f"is pending and its placeholder date ({parse(show['slot']['utc']):%a %d %b}) "
                     "has passed: check MAL and Nyaa for the premiere")
            continue
        total = show.get("total_episodes")
        last = total or show.get("horizon", 12)
        window = show.get("window")
        if eps and eps != list(range(eps[0], eps[-1] + 1)):
            warn("gap in the released episode numbers")
        if any(released[a] > released[b] for a, b in zip(eps, eps[1:])):
            warn("released times are out of order")
        if total and eps and eps[-1] > total:
            warn(f"episode {eps[-1]} is past MAL's count of {total}")
        if window and window_minutes(window) != show.get("duration_minutes"):
            warn("duration_minutes does not match the window")
        if eps and eps[-1] >= last:
            if not total:
                warn(f"reached the horizon ({last}) and MAL still has no count: "
                     "confirm the finale or raise the horizon")
            continue  # finished: nothing left to project

        slot_ep, slot_dt = show["slot"]["episode"], parse(show["slot"]["utc"])
        if eps and slot_ep != eps[-1] + 1:
            warn(f"slot is at episode {slot_ep} but the next unreleased one is {eps[-1] + 1}")
        if window and f"{slot_dt:%H:%M}" != window.split("-")[0]:
            warn("slot time is not the window start")
        if not total and last - (eps[-1] if eps else 0) <= 2:
            warn(f"MAL has no count and the list ends at {last}: check for a "
                 "finale date or raise the horizon")
        nxt = next(((ep, dt) for ep, dt, done in episodes(show) if not done), None)
        if nxt is None:
            continue
        if nxt[1] < now - timedelta(days=1):
            warn(f"episode {nxt[0]} was due {nxt[1]:%a %d %b} and is not logged: "
                 "log it, or add the date to skip if it was a break week")
        if eps and show.get("per_drop", 1) == 1:
            prev = released[eps[-1]]
            breaks = sum(1 for s in show.get("skip", [])
                         if prev.date() < parse(s).date() <= nxt[1].date())
            gap = (nxt[1].date() - prev.date()).days
            if abs(gap - 7 * (1 + breaks)) > 1:
                warn(f"next episode is projected {gap} days after the last "
                     f"release ({breaks} break week(s) between them)")
    return out


def upcoming(data, now, days=7):
    """Projected episodes for the coming week, soonest first."""
    rows = []
    for show in data["shows"]:
        if show.get("pending"):
            continue
        for ep, dt, done in episodes(show):
            if not done and now - timedelta(days=1) <= dt < now + timedelta(days=days):
                rows.append((dt, f"{show['title']} - Episode {ep:02d}"))
    return sorted(rows)


def shift_window(window, tz):
    """Turn a "HH:MM-HH:MM" UTC window into the display time zone."""
    out = []
    for part in window.split("-"):
        h, m = map(int, part.split(":"))
        t = datetime(2026, 1, 1, h, m, tzinfo=timezone.utc).astimezone(tz)
        out.append(t.strftime("%H:%M"))
    return "-".join(out)


def build(data):
    tz = ZoneInfo(data.get("display_tz", "UTC"))
    tz_label = data.get("display_tz_label", "UTC")
    now = fmt(datetime.now(timezone.utc))
    name = data.get("calendar_name", "Anime Releases")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Ali Anime//Release Calendar//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(name)}",
        "X-WR-CALDESC:Episode release times from the uploader Ali downloads from (Nyaa)",
        f"X-WR-TIMEZONE:{tz.key}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    for show in data["shows"]:
        if show.get("pending"):
            continue  # season not started yet; the weekly refresh adds it
        title = show["title"]
        total = show.get("total_episodes")
        offset = show.get("file_offset", 0)
        minutes = show.get("duration_minutes", 30)
        for ep, start, done in episodes(show):
            summary = f"{title} - Episode {ep:02d}"
            if total and ep == total:
                summary += " (Final)"
            desc = [f"Uploader: {show['uploader']} (file {ep + offset:02d})"]
            if done:
                desc.append(f"Released {start.astimezone(tz):%a %d %b %H:%M} {tz_label}")
            else:
                window = show.get("window", start.strftime("%H:%M"))
                if show.get("released"):
                    desc.append(f"Usually out {shift_window(window, tz)} {tz_label}, "
                                "from recent Nyaa post times")
                else:
                    # Switched on from an announced premiere, before episode 1:
                    # the time is an estimate, not a measured post time.
                    desc.append(f"Expected {shift_window(window, tz)} {tz_label}. "
                                "Estimated from the announced broadcast; "
                                "episode 1 is not out yet")
            if not total and show.get("first_episode", 1) == 1:
                desc.append("Episode count not on MAL yet; list runs to "
                            f"{show.get('horizon', 12)} until it is")
            if show.get("note"):
                desc.append(show["note"])
            desc.append(f"MAL: https://myanimelist.net/anime/{show['mal_id']}")
            lines += [
                "BEGIN:VEVENT",
                f"UID:mal{show['mal_id']}-ep{ep}@ali-anime-calendar",
                f"DTSTAMP:{now}",
                f"DTSTART:{fmt(start)}",
                f"DTEND:{fmt(start + timedelta(minutes=minutes))}",
                f"SUMMARY:{esc(summary)}",
                f"DESCRIPTION:{esc(chr(10).join(desc))}",
                f"URL:https://myanimelist.net/anime/{show['mal_id']}",
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


if __name__ == "__main__":
    data = json.loads(SRC.read_text(encoding="utf-8"))
    text = build(data)
    OUT.write_text(text, encoding="utf-8", newline="")
    print(f"Wrote {OUT} with {text.count('BEGIN:VEVENT')} events")

    now = datetime.now(timezone.utc)
    tz = ZoneInfo(data.get("display_tz", "UTC"))
    print(f"\nNext 7 days ({data.get('display_tz_label', 'UTC')}):")
    for dt, name in upcoming(data, now):
        print(f"  {dt.astimezone(tz):%a %d %b %H:%M}  {name}")
    problems = check(data, now)
    print(f"\n{len(problems)} warning(s)")
    for line in problems:
        print(f"  WARNING: {line}")
