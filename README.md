# Anime release calendar

- `shows.json`: one entry per show for the current season. This is the only file edited by hand or by the weekly refresh.
- `build_ics.py`: turns `shows.json` into `anime-releases.ics` (`python3 build_ics.py`), then prints the coming week and a list of warnings about anything in `shows.json` that looks wrong.
- `anime-releases.ics`: the feed Ali subscribes to. GitHub Pages serves it from `main`: https://ali-banimalek.github.io/anime-calendar/anime-releases.ics

## Rules
- Title format (Ali, 8 Nov 2026), the same as his watchlist and the NAS Seasonal folders: `<series title> - Season N` for season 2 and later, nothing added for season 1, `- Part N` / `- Season N Part N` for split cours, and long runners plain (One Piece). Bleach keeps MAL's cour name (Kashin-tan).
  - Series title = MAL's main title of the series' first season, romaji, never an English localization and never MAL's per-season title ("3rd Season", "II", "2nd Season").
  - Korean originals keep their official English name: Solo Leveling, Tomb Raider King, Overgeared.
  - `title` is what the calendar shows; `mal_title` keeps MAL's exact entry name for lookups. Event name: `<title> - Episode NN`, last one gets ` (Final)`.
  - New shows must follow this before they go in; check against the existing titles.
- Episode numbers follow MAL's season numbering; `file_offset` maps to the uploader's number (SubsPlease Kusuriya 49 = S3 ep 1, offset 48).
- One event per episode, no repeating events. Event = the window in which the uploader usually posts: from the earliest to the latest of the last 3 regular posts, rounded out to 5 minutes. Not regular: a premiere that came at an odd time, and any post more than 3 hours off the show's usual (median) time this season; mention that post in `note` instead of widening the window. Re-derive it every refresh so it stays tight; the slot's start time is the window start and `duration_minutes` is the window's length.
- Times are stored in UTC (Apple shows them in the device time zone); descriptions use `display_tz` (UAE, Asia/Dubai). `window` and `slot` are UTC.
- Time = when the uploader Ali downloads from posts it on Nyaa (SubsPlease by default; ASW for One Piece; Erai-raws AVC for Netflix shows).

## Fields
- `released`: real Nyaa pubDate per MAL episode (UTC). Wins over the projection.
- `slot`: next expected episode and its expected UTC start; later episodes are +7 days (or `per_drop` per week for batch drops).
- `skip`: dates of break weeks (the day the episode would have come). A break on or after the slot's date pushes that episode and the rest back a week. Earlier ones stay as a record and change nothing, because the slot was already set after them.
- `total_episodes`: MAL's count, or null. Null means the list runs to `horizon` and says the count is unconfirmed.
- `pending`: show is on the watchlist but hasn't started; left out of the feed.

## Long runners
Shows marked `long_runner` (One Piece) stay in `shows.json` permanently, whether or not they're on the season's watchlist. During a hiatus they're `pending` (hidden from the feed); each refresh checks Nyaa and news for the return, then sets `slot` and turns `pending` off. Keep `horizon` about 12 episodes ahead.

## Weekly refresh
Mondays. Sources are each show's Nyaa RSS feed (`https://nyaa.si/?page=rss&q=<nyaa_query>&s=id&o=desc`; without `&s=id&o=desc` WebFetch can return a cached, week-old feed) and its MAL page. From a cloud session both only work through WebFetch, and Nyaa refuses parallel requests: fetch the feeds one at a time and retry a refused one once at the end.

1. **Log releases.** For every show that isn't finished, add each new episode to `released` with the exact pubDate (UTC). Count single episodes only: skip `[Batch]` items, `.5` recaps and specials, and for a `v2` keep the first post's time. File number minus `file_offset` is the MAL episode.
2. **Move the slot** to the next unreleased episode: 7 days after the last release, at the window start.
3. **Break weeks.** If an episode didn't come in its week, add that date to `skip` and leave it there. Then look ahead: check the show's MAL forum and news for a break announced for the coming week and add its date to `skip` before it happens. Netflix shows and the last week of December are the usual ones.
4. **Re-derive the window** from the last 3 regular posts (rule above) and set `duration_minutes` to match.
5. **Check MAL** for every show. When MAL gets an episode count, set `total_episodes` and drop `horizon`. While it has none, keep `horizon` more than 2 episodes ahead of the last release, or set it to the finale once that is announced. Flip `pending` off when episode 1 appears.
6. **Long runners** on hiatus: check Nyaa and news for the return (see above).
7. **Build and check.** Set `updated` and run `python3 build_ics.py`. It should end with `0 warning(s)`; a warning may stay only when something real explains it, such as an episode that is late today. Read the "Next 7 days" list it prints: every airing show should be there once, on its usual day.
8. **Publish.** Commit `shows.json` and `anime-releases.ics` to `main` and push, then copy the changed files to the project mirror (`/mnt/project-files/calendar/`).

Finished shows stay until the season after next, so past episodes remain visible.

## New season
The seasonal watchlist reminder (20 Mar/Jun/Sep/Dec) drafts the next season's list with uploaders. Each approved show becomes a `shows.json` entry (MAL id, uploader, `pending: true`); the refresh fills in times once episode 1 is out.
