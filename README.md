# Anime release calendar

- `shows.json`: one entry per show for the current season. This is the only file edited by hand or by the weekly refresh.
- `build_ics.py`: turns `shows.json` into `anime-releases.ics` (`python3 build_ics.py`).
- `anime-releases.ics`: the feed Ali subscribes to (once hosted).

## Rules
- Title format (Ali, 8 Nov 2026), the same as his watchlist and the NAS Seasonal folders: `<series title> - Season N` for season 2 and later, nothing added for season 1, `- Part N` / `- Season N Part N` for split cours, and long runners plain (One Piece). Bleach keeps MAL's cour name (Kashin-tan).
  - Series title = MAL's main title of the series' first season, romaji, never an English localization and never MAL's per-season title ("3rd Season", "II", "2nd Season").
  - Korean originals keep their official English name: Solo Leveling, Tomb Raider King, Overgeared.
  - `title` is what the calendar shows; `mal_title` keeps MAL's exact entry name for lookups. Event name: `<title> - Episode NN`, last one gets ` (Final)`.
  - New shows must follow this before they go in; check against the existing titles.
- Episode numbers follow MAL's season numbering; `file_offset` maps to the uploader's number (SubsPlease Kusuriya 49 = S3 ep 1, offset 48).
- One event per episode, no repeating events. Event = the window in which the uploader usually posts: from the earliest to the latest of the last 3 regular posts, rounded out to 5 minutes (ignore a premiere or a one-off late post more than 3h off). Re-derive it every refresh so it stays tight; the slot's start time is the window start.
- Times are stored in UTC (Apple shows them in the device time zone); descriptions use `display_tz` (UAE, Asia/Dubai). `window` and `slot` are UTC.
- Time = when the uploader Ali downloads from posts it on Nyaa (SubsPlease by default; ASW for One Piece; Erai-raws AVC for Netflix shows).

## Fields
- `released`: real Nyaa pubDate per MAL episode (UTC). Wins over the projection.
- `slot`: next expected episode and its expected UTC start; later episodes are +7 days (or `per_drop` per week for batch drops).
- `skip`: dates of break weeks; each pushes the remaining episodes back a week.
- `total_episodes`: MAL's count, or null. Null means the list runs to `horizon` and says the count is unconfirmed.
- `pending`: show is on the watchlist but hasn't started; left out of the feed.

## Long runners
Shows marked `long_runner` (One Piece) stay in `shows.json` permanently, whether or not they're on the season's watchlist. During a hiatus they're `pending` (hidden from the feed); each refresh checks Nyaa and news for the return, then sets `slot` and turns `pending` off. Keep `horizon` about 12 episodes ahead.

## Weekly refresh
Add `&s=id&o=desc` to Nyaa RSS URLs: without it WebFetch can return a cached, week-old feed.

For each show: check Nyaa RSS (`nyaa_query`) for new episodes, add them to `released`, move `slot` to the next episode with the observed time, add `skip` for any missed week, update `total_episodes` from MAL, flip `pending` off when episode 1 appears. Finished shows stay until the season after next, so past episodes remain visible. Rebuild and publish.

## New season
The seasonal watchlist reminder (20 Mar/Jun/Sep/Dec) drafts the next season's list with uploaders. Each approved show becomes a `shows.json` entry (MAL id, uploader, `pending: true`); the refresh fills in times once episode 1 is out.
