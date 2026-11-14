#!/usr/bin/env python3
"""Tests for auto_refresh.py. Run: python3 -m unittest -q

They use made-up Nyaa feeds and MAL pages written to a temporary folder, never the web.
"""
import contextlib
import copy
import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import auto_refresh as ar
import build_ics


def utc(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def show(**over):
    """A SubsPlease show: Fridays about 15:02 UTC, four episodes out, file numbers 48 ahead."""
    s = {
        "title": "Test Show - Season 3", "mal_id": 100, "uploader": "SubsPlease",
        "nyaa_query": "[SubsPlease] Test Show 1080p", "file_offset": 48, "total_episodes": 12,
        "window": "15:00-15:05", "duration_minutes": 5,
        "released": {"1": "2026-10-09T15:01:52Z", "2": "2026-10-16T15:01:50Z",
                     "3": "2026-10-23T15:01:57Z", "4": "2026-10-30T15:02:51Z"},
        "slot": {"episode": 5, "utc": "2026-11-06T15:00:00Z"},
    }
    s.update(over)
    return s


def quiet(data, web, now, everything=False):
    """ar.refresh without its progress lines."""
    with contextlib.redirect_stdout(io.StringIO()):
        return ar.refresh(data, web, now, everything)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def feed(self, mal_id, items):
        """items: [(title, "YYYY-MM-DD HH:MM")], any order."""
        body = "".join(
            f"<item><title>{t.replace('&', '&amp;')}</title>"
            f"<pubDate>{format_datetime(utc(when)).replace('+0000', '-0000')}</pubDate></item>"
            for t, when in items)
        (self.dir / f"{mal_id}.xml").write_text(
            f'<?xml version="1.0"?><rss version="2.0"><channel><title>Nyaa</title>{body}</channel></rss>',
            encoding="utf-8")

    def mal(self, mal_id, episodes, status="Currently Airing"):
        (self.dir / f"mal-{mal_id}.html").write_text(
            f'<div class="spaceit_pad"><span class="dark_text">Episodes:</span>\n  {episodes}\n  </div>'
            f'<div class="spaceit_pad"><span class="dark_text">Status:</span>\n  {status}\n  </div>',
            encoding="utf-8")

    def run_at(self, shows, when, everything=False):
        data = {"updated": "2026-01-01", "shows": shows}
        changes = quiet(data, ar.Web(self.dir), utc(when), everything)
        return data, changes

    def no_hard_warnings(self, s, when):
        self.assertEqual(ar.hard_warnings(s, utc(when)), set())


class Logging(Case):
    def test_on_time_episode(self):
        s = show()
        self.feed(100, [("[SubsPlease] Test Show - 53 (1080p) [AAAA1111].mkv", "2026-11-06 15:03"),
                        ("[SubsPlease] Test Show - 52 (1080p) [BBBB2222].mkv", "2026-10-30 15:02")])
        data, changes = self.run_at([s], "2026-11-06 15:23")
        self.assertEqual(s["released"]["5"], "2026-11-06T15:03:00Z")
        self.assertEqual(s["slot"], {"episode": 6, "utc": "2026-11-13T15:00:00Z"})
        self.assertEqual((s["window"], s["duration_minutes"]), ("15:00-15:05", 5))
        self.assertEqual(s["release_name"], "Test Show")
        self.assertEqual(data["updated"], "2026-11-06")
        self.assertEqual(len(changes), 1)
        self.no_hard_warnings(s, "2026-11-06 15:23")
        self.assertEqual(build_ics.check(data, utc("2026-11-06 15:23")), [])

    def test_running_again_changes_nothing(self):
        s = show()
        self.feed(100, [("[SubsPlease] Test Show - 53 (1080p) [AAAA1111].mkv", "2026-11-06 15:03")])
        self.run_at([s], "2026-11-06 15:23")
        after = copy.deepcopy(s)
        data, changes = self.run_at([s], "2026-11-06 16:23")
        self.assertEqual((s, changes), (after, []))
        self.assertEqual(data["updated"], "2026-01-01")

    def test_not_due_is_not_fetched(self):
        s = show()
        web = ar.Web(self.dir)
        quiet({"shows": [s]}, web, utc("2026-11-06 14:23"))
        self.assertEqual(web.calls, 0)

    def test_not_posted_yet(self):
        s = show()
        before = copy.deepcopy(s)
        self.feed(100, [("[SubsPlease] Test Show - 52 (1080p) [BBBB2222].mkv", "2026-10-30 15:02")])
        _, changes = self.run_at([s], "2026-11-06 20:23")
        self.assertEqual((s, changes), (before, []))

    def test_feed_cannot_be_read(self):
        s = show()
        before = copy.deepcopy(s)
        _, changes = self.run_at([s], "2026-11-06 20:23")  # no file: the web answer is missing
        self.assertEqual((s, changes), (before, []))
        (self.dir / "100.xml").write_text("<html><body>Just a moment...</body></html>", encoding="utf-8")
        _, changes = self.run_at([s], "2026-11-08 12:23")  # a page that is not a feed is not "no episode"
        self.assertEqual((s, changes), (before, []))

    def test_two_episodes_at_once(self):
        s = show()
        self.feed(100, [("[SubsPlease] Test Show - 54 (1080p) [C].mkv", "2026-11-13 15:02"),
                        ("[SubsPlease] Test Show - 53 (1080p) [A].mkv", "2026-11-06 15:03")])
        _, changes = self.run_at([s], "2026-11-13 18:00")
        self.assertEqual(sorted(s["released"], key=int)[-2:], ["5", "6"])
        self.assertEqual(s["slot"], {"episode": 7, "utc": "2026-11-20T15:00:00Z"})
        self.assertEqual(len(changes), 2)

    def test_v2_batch_recap_and_other_uploaders_are_ignored(self):
        s = show()
        self.feed(100, [
            ("[SubsPlease] Test Show - 53v2 (1080p) [A2].mkv", "2026-11-06 19:00"),
            ("[SubsPlease] Test Show - 53 (1080p) [A].mkv", "2026-11-06 15:03"),
            ("[SubsPlease] Test Show - 52.5 (1080p) [R].mkv", "2026-11-06 15:04"),
            ("[SubsPlease] Test Show (49-53) (1080p) [Batch]", "2026-11-06 15:10"),
            ("[Erai-raws] Test Show - 53 [1080p CR WEB-DL AVC AAC][MultiSub]", "2026-11-06 14:00"),
            ("[SubsPlease] Test Show - 54 (720p) [X].mkv", "2026-11-06 15:03"),  # the query would not return it; a second episode the same minute is fine
        ])
        self.run_at([s], "2026-11-06 20:00")
        self.assertEqual(s["released"]["5"], "2026-11-06T15:03:00Z")

    def test_erai_raws_names(self):
        s = show(uploader="Erai-raws", nyaa_query="Erai-raws Test Show Season 2 1080p AVC", file_offset=0,
                 total_episodes=5)
        self.feed(100, [
            ("[Erai-raws] Test Show Season 2 - 05 END [1080p NF WEB-DL AVC AAC][MultiSub][ABCD1234]",
             "2026-11-06 15:03"),
            ("[Erai-raws] Test Show Season 2 - 04 (REPACK) [1080p NF WEB-DL AVC AAC][MultiSub][EEEE0000]",
             "2026-11-06 15:20"),
        ])
        _, changes = self.run_at([s], "2026-11-06 20:00")
        self.assertEqual(s["released"]["5"], "2026-11-06T15:03:00Z")
        self.assertEqual(s["release_name"], "Test Show Season 2")
        self.assertEqual(s["slot"]["episode"], 5)  # that was the finale: the slot stays
        self.assertIsNone(ar.next_due(s))

    def test_release_name_with_a_dash(self):
        s = show(file_offset=0)
        self.feed(100, [("[SubsPlease] Tempal - Item no Chikara - 05 (1080p) [A].mkv", "2026-11-06 15:03")])
        self.run_at([s], "2026-11-06 20:00")
        self.assertEqual(s["release_name"], "Tempal - Item no Chikara")

    def test_another_release_name_is_left_alone(self):
        s = show(release_name="Test Show")
        before = copy.deepcopy(s)
        self.feed(100, [("[SubsPlease] Test Show Gaiden - 53 (1080p) [A].mkv", "2026-11-06 15:03")])
        _, changes = self.run_at([s], "2026-11-06 20:00")
        self.assertEqual((s, changes), (before, []))

    def test_two_release_names_for_a_first_log_are_left_alone(self):
        s = show()
        before = copy.deepcopy(s)
        self.feed(100, [("[SubsPlease] Test Show - 53 (1080p) [A].mkv", "2026-11-06 15:03"),
                        ("[SubsPlease] Test Show Gaiden - 53 (1080p) [B].mkv", "2026-11-06 15:33")])
        _, changes = self.run_at([s], "2026-11-06 20:00")
        self.assertEqual((s, changes), (before, []))

    def test_never_past_the_last_episode(self):
        s = show(total_episodes=5, file_offset=0)
        self.feed(100, [("[SubsPlease] Test Show - 05 (1080p) [A].mkv", "2026-11-06 15:03"),
                        ("[SubsPlease] Test Show - 06 (1080p) [B].mkv", "2026-11-13 15:03")])
        self.run_at([s], "2026-11-14 00:00")
        self.assertEqual(max(map(int, s["released"])), 5)

    def test_shows_that_are_not_touched(self):
        for flag in ({"pending": True}, {"dropped": "2026-11-01"}, {"manual": True}, {"per_drop": 12}):
            s = show(**flag)
            before = copy.deepcopy(s)
            self.feed(100, [("[SubsPlease] Test Show - 53 (1080p) [A].mkv", "2026-11-06 15:03")])
            _, changes = self.run_at([s], "2026-11-06 20:00", everything=True)
            self.assertEqual((s, changes), (before, []), flag)


class Premiere(Case):
    def premiere(self, **over):
        return show(file_offset=0, total_episodes=None, horizon=12, released={},
                    window="14:00-16:00", duration_minutes=120,
                    slot={"episode": 1, "utc": "2027-01-04T14:00:00Z"}, **over)

    def test_first_episode(self):
        s = self.premiere()
        self.feed(100, [("[SubsPlease] Test Show - 01 (1080p) [A].mkv", "2027-01-04 14:32"),
                        ("[SubsPlease] Test Show - 01 (1080p) [OLD].mkv", "2023-01-06 15:00")])
        self.mal(100, "Unknown")
        self.run_at([s], "2027-01-04 15:23")
        self.assertEqual(s["released"], {"1": "2027-01-04T14:32:00Z"})
        self.assertEqual(s["slot"], {"episode": 2, "utc": "2027-01-11T14:30:00Z"})
        self.assertEqual((s["window"], s["duration_minutes"]), ("14:30-14:35", 5))
        self.no_hard_warnings(s, "2027-01-04 15:23")

    def test_last_seasons_episode_one_is_not_taken(self):
        s = self.premiere()
        before = copy.deepcopy(s)
        self.feed(100, [("[SubsPlease] Test Show - 01 (1080p) [OLD].mkv", "2023-01-06 15:00")])
        _, changes = self.run_at([s], "2027-01-08 12:00")  # days late, still no skip: nothing is out yet
        self.assertEqual((s, changes), (before, []))

    def test_numbering_that_carries_on_waits_for_a_person(self):
        s = self.premiere()
        before = copy.deepcopy(s)
        self.feed(100, [("[SubsPlease] Test Show - 26 (1080p) [A].mkv", "2027-01-04 14:32")])
        _, changes = self.run_at([s], "2027-01-04 18:00")
        self.assertEqual((s, changes), (before, []))
        self.assertTrue(any("was due" in w for w in build_ics.check({"shows": [s]}, utc("2027-01-06 18:00"))))


class Breaks(Case):
    def test_break_week_then_back(self):
        s = show()
        self.feed(100, [("[SubsPlease] Test Show - 52 (1080p) [B].mkv", "2026-10-30 15:02")])
        # 30 hours late: nothing yet
        _, changes = self.run_at([s], "2026-11-07 21:23")
        self.assertEqual(changes, [])
        # past 36 hours: whichever run comes first counts it, at any hour
        _, changes = self.run_at([s], "2026-11-08 05:23")
        self.assertEqual(s["skip"], ["2026-11-06"])
        self.assertEqual(s["slot"], {"episode": 5, "utc": "2026-11-06T15:00:00Z"})
        self.assertEqual(ar.next_due(s), (5, utc("2026-11-13 15:00")))
        self.assertEqual(len(changes), 1)
        self.assertEqual(build_ics.check({"shows": [s]}, utc("2026-11-08 05:23")), [])
        # the rest of the week it is not fetched at all
        web = ar.Web(self.dir)
        quiet({"shows": [s]}, web, utc("2026-11-12 12:23"))
        self.assertEqual(web.calls, 0)
        # the episode comes a week later: the break stays on record
        self.feed(100, [("[SubsPlease] Test Show - 53 (1080p) [A].mkv", "2026-11-13 15:02")])
        self.run_at([s], "2026-11-13 15:23")
        self.assertEqual(s["skip"], ["2026-11-06"])
        self.assertEqual(s["slot"], {"episode": 6, "utc": "2026-11-20T15:00:00Z"})
        self.assertEqual(build_ics.check({"shows": [s]}, utc("2026-11-13 15:23")), [])

    def test_late_episode_takes_the_break_back(self):
        s = show()
        self.feed(100, [("[SubsPlease] Test Show - 52 (1080p) [B].mkv", "2026-10-30 15:02")])
        self.run_at([s], "2026-11-08 06:23")
        self.assertEqual(s["skip"], ["2026-11-06"])
        # it turns up three days late; --all is how a person would look early
        self.feed(100, [("[SubsPlease] Test Show - 53 (1080p) [A].mkv", "2026-11-09 15:40")])
        self.run_at([s], "2026-11-09 16:23", everything=True)
        self.assertNotIn("skip", s)
        self.assertEqual(s["released"]["5"], "2026-11-09T15:40:00Z")
        self.assertEqual(s["slot"], {"episode": 6, "utc": "2026-11-13T15:00:00Z"})  # back to Friday
        self.no_hard_warnings(s, "2026-11-09 16:23")

    def test_an_announced_break_is_kept(self):
        s = show(skip=["2026-11-13"])  # the weekly refresh read that there is no episode on the 13th
        self.feed(100, [("[SubsPlease] Test Show - 53 (1080p) [A].mkv", "2026-11-06 15:03")])
        self.run_at([s], "2026-11-06 15:23")
        self.assertEqual(s["skip"], ["2026-11-13"])
        self.assertEqual(ar.next_due(s), (6, utc("2026-11-20 15:00")))
        self.assertEqual(build_ics.check({"shows": [s]}, utc("2026-11-06 15:23")), [])

    def test_no_more_than_three_breaks_in_a_row(self):
        s = show()
        self.feed(100, [("[SubsPlease] Test Show - 52 (1080p) [B].mkv", "2026-10-30 15:02")])
        when = utc("2026-11-06 00:23")
        for _ in range(24 * 40):
            when += timedelta(hours=1)
            quiet({"shows": [s]}, ar.Web(self.dir), when)
        self.assertEqual(s["skip"], ["2026-11-06", "2026-11-13", "2026-11-20"])
        self.assertTrue(any("was due" in w for w in build_ics.check({"shows": [s]}, when)))

    def test_mal_is_read_once_per_break_and_not_after_the_third(self):
        s = show(total_episodes=None, horizon=12)
        self.feed(100, [("[SubsPlease] Test Show - 52 (1080p) [B].mkv", "2026-10-30 15:02")])
        self.mal(100, "Unknown")
        when, reads = utc("2026-11-06 00:23"), 0
        for _ in range(24 * 40):
            when += timedelta(hours=1)
            web = ar.Web(self.dir)
            quiet({"shows": [s]}, web, when)
            reads += web.calls - (1 if web.calls else 0)  # calls beyond the feed are MAL pages
        self.assertEqual(len(s["skip"]), 3)
        self.assertEqual(reads, 3)

    def test_late_post_on_the_usual_day_keeps_the_window(self):
        s = show()
        self.feed(100, [("[SubsPlease] Test Show - 53 (1080p) [A].mkv", "2026-11-06 20:48")])
        self.run_at([s], "2026-11-06 21:23")
        self.assertEqual((s["window"], s["duration_minutes"]), ("15:00-15:05", 5))
        self.assertEqual(s["slot"], {"episode": 6, "utc": "2026-11-13T15:00:00Z"})


class Counts(Case):
    def test_mal_count_arrives(self):
        s = show(total_episodes=None, horizon=12)
        self.feed(100, [("[SubsPlease] Test Show - 53 (1080p) [A].mkv", "2026-11-06 15:03")])
        self.mal(100, 13)
        _, changes = self.run_at([s], "2026-11-06 15:23")
        self.assertEqual(s["total_episodes"], 13)
        self.assertNotIn("horizon", s)
        self.assertEqual(len(changes), 2)

    def test_mal_count_that_does_not_fit_is_ignored(self):
        s = show(total_episodes=None, horizon=12)
        self.feed(100, [("[SubsPlease] Test Show - 53 (1080p) [A].mkv", "2026-11-06 15:03")])
        self.mal(100, 3)
        self.run_at([s], "2026-11-06 15:23")
        self.assertIsNone(s["total_episodes"])

    def test_horizon_stays_ahead(self):
        s = show(total_episodes=None, horizon=7)
        self.feed(100, [("[SubsPlease] Test Show - 53 (1080p) [A].mkv", "2026-11-06 15:03")])
        self.mal(100, "Unknown")
        self.run_at([s], "2026-11-06 15:23")
        self.assertEqual(s["horizon"], 8)
        self.assertEqual(build_ics.check({"shows": [s]}, utc("2026-11-06 15:23")), [])

    def test_finale_found_instead_of_a_break(self):
        s = show(total_episodes=None, horizon=7)  # four are out; MAL then says four is all
        self.feed(100, [("[SubsPlease] Test Show - 52 (1080p) [B].mkv", "2026-10-30 15:02")])
        self.mal(100, 4, "Finished Airing")
        _, changes = self.run_at([s], "2026-11-08 06:23")
        self.assertEqual(s["total_episodes"], 4)
        self.assertNotIn("skip", s)
        self.assertIsNone(ar.next_due(s))
        self.assertEqual(build_ics.check({"shows": [s]}, utc("2026-11-08 06:23")), [])


class Windows(Case):
    def test_window_from_last_three_regular_posts(self):
        s = show(released={"1": "2026-10-02T01:40:20Z", "2": "2026-10-08T17:03:59Z",
                           "3": "2026-10-15T15:40:18Z", "4": "2026-10-22T20:48:44Z",
                           "5": "2026-10-29T17:42:58Z", "6": "2026-11-05T15:41:24Z"})
        self.assertEqual(ar.derive_window(s), ("15:40-17:45", 125))

    def test_window_across_midnight(self):
        s = show(file_offset=0, window="23:50-00:10", duration_minutes=20,
                 released={"1": "2026-10-09T23:55:00Z", "2": "2026-10-17T00:05:00Z",
                           "3": "2026-10-23T23:52:00Z"},
                 slot={"episode": 4, "utc": "2026-10-30T23:50:00Z"})
        self.feed(100, [("[SubsPlease] Test Show - 04 (1080p) [A].mkv", "2026-10-31 00:07")])
        self.run_at([s], "2026-10-31 00:23")
        self.assertEqual((s["window"], s["duration_minutes"]), ("23:50-00:10", 20))
        self.assertEqual(s["slot"], {"episode": 5, "utc": "2026-11-06T23:50:00Z"})
        self.assertEqual(build_ics.check({"shows": [s]}, utc("2026-10-31 00:23")), [])


if __name__ == "__main__":
    unittest.main()
