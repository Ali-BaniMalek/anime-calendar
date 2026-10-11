# Anime release calendar

- `shows.json`: one entry per show for the current season. This is the only file edited by hand or by the weekly refresh.
- `build_ics.py`: turns `shows.json` into `anime-releases.ics` (`python3 build_ics.py`).
- `anime-releases.ics`: the feed Ali subscribes to (once hosted).

## Rules
- Title = MAL main title, verbatim (exceptions in English: Solo Leveling, Tomb Raider King). Event name: `<title> - Episode NN`, last one gets ` (Final)`.
- Episode numbers follow MAL's season numbering; `file_offset` maps to the uploader's number (SubsPlease Kusuriya 49 = S3 ep 1, offset 48).
- One event per episode, no repeating events. Event length = the window in which the uploader usually posts, so it differs per show.
- Time = when the uploader Ali downloads from posts it on Nyaa (SubsPlease by default; ASW for One Piece; Erai-raws AVC for Netflix shows).

## Fields
- `released`: real Nyaa pubDate per MAL episode (UTC). Wins over the projection.
- `slot`: next expected episode and its expected UTC start; later episodes are +7 days (or `per_drop` per week for batch drops).
- `skip`: dates of break weeks; each pushes the remaining episodes back a week.
- `total_episodes`: MAL's count, or null. Null means the list runs to `horizon` and says the count is unconfirmed.
- `pending`: show is on the watchlist but hasn't started; left out of the feed.

## Weekly refresh
For each show: check Nyaa RSS (`nyaa_query`) for new episodes, add them to `released`, move `slot` to the next episode with the observed time, add `skip` for any missed week, update `total_episodes` from MAL, flip `pending` off when episode 1 appears. Finished shows stay until the season after next, so past episodes remain visible. Rebuild and publish.

## New season
The seasonal watchlist reminder (20 Mar/Jun/Sep/Dec) drafts the next season's list with uploaders. Each approved show becomes a `shows.json` entry (MAL id, uploader, `pending: true`); the refresh fills in times once episode 1 is out.
