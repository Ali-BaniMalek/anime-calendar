#!/usr/bin/env python3
"""Build the anime release calendar (.ics) from shows.json.

One event per episode, no recurring rules. Episodes already out use the real
Nyaa post time from "released"; upcoming ones are projected weekly from the
show's "slot" anchor, shifted by any "skip" weeks. The list ends at MAL's
episode count; when MAL has no count yet, it runs to "horizon" episodes and
says the count is unconfirmed.

Usage: python3 build_ics.py [shows.json] [out.ics]
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
            if s.date() <= dt.date():
                dt += timedelta(weeks=1)
        yield ep, dt, False


def build(data):
    now = fmt(datetime.now(timezone.utc))
    name = data.get("calendar_name", "Anime Releases")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//Ali Anime//Release Calendar//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(name)}",
        "X-WR-CALDESC:Episode release times from the uploader Ali downloads from (Nyaa)",
        "X-WR-TIMEZONE:UTC",
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
                desc.append(f"Released {start:%a %d %b %H:%M} UTC")
            else:
                desc.append(f"Expected {show.get('window', start.strftime('%H:%M'))} UTC, "
                            "from recent Nyaa post times")
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
    data = json.loads(SRC.read_text())
    OUT.write_text(build(data), newline="")
    n = sum(1 for _ in OUT.read_text().split("BEGIN:VEVENT")) - 1
    print(f"Wrote {OUT} with {n} events")
