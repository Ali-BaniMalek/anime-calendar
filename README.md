# Anime release calendar

- `shows.json`: one entry per show for the current season. This is the only file edited by hand, by the weekly refresh or by the automatic refresh.
- `build_ics.py`: turns `shows.json` into `anime-releases.ics` (`python3 build_ics.py`), then prints the coming week and a list of warnings about anything in `shows.json` that looks wrong. The same `shows.json` always builds the same file.
- `anime-releases.ics`: the feed Ali subscribes to. GitHub Pages serves it from `main`: https://ali-banimalek.github.io/anime-calendar/anime-releases.ics
- `auto_refresh.py`: logs new episodes by itself, every hour, on GitHub (see Automatic refresh). `test_auto_refresh.py` holds its tests (`python3 -m unittest -q`), and `.github/workflows/refresh.yml` runs both.

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
- `pending`: show is approved but its premiere day or broadcast time isn't announced yet; left out of the feed. `pending_note` says what is still unknown, and its `slot` is a placeholder (the build warns once that date has passed).
- `release_name`: the name the uploader files the show under ("Kusuriya no Hitorigoto" in `[SubsPlease] Kusuriya no Hitorigoto - 55 (1080p)`). The automatic refresh writes it with the first episode it logs and afterwards only logs episodes posted under that name. If the uploader renames the show, correct it here.
- `manual`: set `"manual": true` to keep the automatic refresh away from a show (odd numbering, two uploads a week, anything it gets wrong). The weekly refresh then does that show by hand.
- `updated`: the day `shows.json` last changed. The feed's timestamps come from it, so set it whenever you change the file.

## Before episode 1
Once MAL shows a show's premiere day and broadcast time (the "Aired" and "Broadcast" lines), turn `pending` off so the premiere is on the calendar in advance:
- `slot`: episode 1 on the premiere day, at the broadcast time converted from JST to UTC (JST is UTC+9). If MAL's background says it streams early (Overgeared, Tensei shitara Ken deshita II), use the streaming day instead.
- `window`: from the broadcast time to 2 hours after, `duration_minutes` 120. SubsPlease and Erai-raws usually post 0 to 90 minutes after the broadcast.
- Until episode 1 is logged, its events say "Expected ... Estimated from the announced broadcast; episode 1 is not out yet". After that the weekly refresh measures the real window as usual (with fewer than 3 posts, use the ones there are).
- A Netflix drop of a whole season (`per_drop`) works the same way: the slot is the announced day, and the window is replaced by the real post time once it is out.

## Long runners
Shows marked `long_runner` (One Piece) stay in `shows.json` permanently, whether or not they're on the season's watchlist. During a hiatus they're `pending` (hidden from the feed); each refresh checks Nyaa and news for the return, then sets `slot` and turns `pending` off. Keep `horizon` about 12 episodes ahead.

## Dropped shows
When Ali drops a show, it gets `"dropped": "YYYY-MM-DD"` and disappears from the feed; the entry stays as a record (so it isn't added back) and is pruned with the finished shows. Ali drops a show with the Drop button on his watch checklist page on the NAS, which also marks it Dropped on his MAL list, or by marking it Dropped on MAL himself. The calendar can't see the NAS, so MAL is the link: step 5 checks his Dropped list.

Shows with `"download_only": true` (downloaded and tracked, but not watched, like One Punch Man) are the exception: Ali may mark those Dropped on MAL and still want them, so they're dropped only when the MAL entry also carries the tag `nas-dropped` (set by the Drop button) or when Ali asks.

## Automatic refresh
GitHub runs `auto_refresh.py` every hour (workflow "Refresh the calendar", at 23 minutes past) and commits to `main` as `github-actions[bot]` when something changed. From GitHub's machines Nyaa's RSS and MAL's pages can be read directly. It does the mechanical part of the weekly refresh for the shows that are airing, and only for a show whose next episode is due:

- **Logs a new episode** (step 1) when it is the next one in line, from the show's uploader, under the same release name as before, and posted after the previous one. Then it moves the slot (step 2) to the show's usual weekday and re-derives the window (step 4).
- **Break weeks** (first half of step 3): an episode that is 36 hours late is counted as a break. Its date goes into `skip`, so the rest of the season moves back a week. If the episode turns up within 5 days after all, the skip is removed again. It adds at most 3 breaks in a row; after that the build's warning stays until someone looks.
- **Episode count** (part of step 5): when it logs an episode of a show without a count, and before it adds a break, it reads the show's MAL page. A count that fits sets `total_episodes` and removes `horizon`; without one, `horizon` is kept 3 episodes ahead.

It leaves these alone, and the build's warnings show what is waiting: `pending` and `dropped` shows, whole-season drops (`per_drop`), shows marked `manual`, a premiere whose file number is not the expected one (`first_episode` + `file_offset`), and an episode posted under another release name. It never changes a title, uploader, query, offset or note. A change that would give a show a new build warning about the entry itself is not made.

The same workflow runs the tests first and stops if one fails, and it rebuilds `anime-releases.ics` whenever `shows.json` or a script changes on `main`, so a commit that forgot to rebuild the feed is put right within a minute. Each run's page on GitHub (Actions tab) lists what changed and the build's warnings. To run it by hand: Actions, "Refresh the calendar", Run workflow; tick the box to read every airing show's feed instead of only the ones that are due.

GitHub switches a scheduled workflow off after 60 days without a commit in the repo. The weekly refresh checks that it still runs (step 0).

## Weekly refresh
Mondays. The automatic refresh has usually done steps 1, 2 and 4 and part of 3 and 5 already. The weekly refresh checks that work and does what needs reading and judgment: announced breaks, premieres, renamed or renumbered releases, finales, long runners and the Dropped list.

0. **Start from `main`.** `git pull`, then run `python3 build_ics.py` and read its warnings: they are the list of what the automatic refresh left. Look at the last runs of "Refresh the calendar" on GitHub (Actions): they should be green and less than a few hours old. If the workflow is switched off or failing, say so in the thread and do steps 1, 2 and 4 by hand.

Sources are each show's Nyaa RSS feed (`https://nyaa.si/?page=rss&q=<nyaa_query>&s=id&o=desc`; without `&s=id&o=desc` WebFetch can return a cached, week-old feed) and its MAL page. From a cloud session both only work through WebFetch, and Nyaa refuses parallel requests: fetch the feeds one at a time and retry a refused one once at the end.

1. **Log releases.** For every show that isn't finished, add each new episode to `released` with the exact pubDate (UTC). Count single episodes only: skip `[Batch]` items, `.5` recaps and specials, and for a `v2` keep the first post's time. File number minus `file_offset` is the MAL episode.
2. **Move the slot** to the next unreleased episode: 7 days after the last release, at the window start.
3. **Break weeks.** If an episode didn't come in its week, add that date to `skip` and leave it there. For every skip the automatic refresh added since the last weekly refresh (see `git log -p shows.json`), check that it was a break and not the finale, a hiatus or a renamed release, and correct the entry if it was. Then look ahead: check the show's MAL forum and news for a break announced for the coming week and add its date to `skip` before it happens. Netflix shows and the last week of December are the usual ones.
4. **Re-derive the window** from the last 3 regular posts (rule above) and set `duration_minutes` to match.
5. **Check MAL** for every show. When MAL gets an episode count, set `total_episodes` and drop `horizon`. While it has none, keep `horizon` more than 2 episodes ahead of the last release, or set it to the finale once that is announced. For `pending` shows, check whether MAL now has the premiere day and broadcast time (see Before episode 1), and flip `pending` off when it does or when episode 1 appears. When episode 1 is out, compare its real release name with `nyaa_query` and `file_offset` and fix them if the uploader named or numbered it differently. Then check Ali's Dropped list (`https://myanimelist.net/animelist/<user>/load.json?status=4`) and mark every calendar show whose `mal_id` is on it as `dropped` (see Dropped shows; `download_only` shows need the `nas-dropped` tag).
6. **Long runners** on hiatus: check Nyaa and news for the return (see above).
7. **Build and check.** Set `updated` and run `python3 build_ics.py`. It should end with `0 warning(s)`; a warning may stay only when something real explains it, such as an episode that is late today. Read the "Next 7 days" list it prints: every airing show should be there once, on its usual day.
8. **Publish.** Commit `shows.json` and `anime-releases.ics` to `main` and push. The automatic refresh may have committed in the meantime: `git pull --rebase` first, and if `shows.json` conflicts keep every logged release from both sides and rebuild. A thread that works on its own branch commits `shows.json` and the scripts but not `anime-releases.ics` (the workflow rebuilds it on `main`, and leaving it out avoids conflicts), opens a pull request to `main` and merges it itself. Then copy the changed files to the project mirror (`/mnt/project-files/calendar/`). The mirror is only as fresh as the last copy; anything that needs today's state reads the repo.

Finished shows stay until the season after next, so past episodes remain visible.

## New season
The changeover runs over about three weeks, not one day: the last finales of the old season and the first episodes of the new one overlap.

1. **Watchlist day** (Ali's reminder on 20 Mar/Jun/Sep/Dec). Each show Ali approves becomes a `shows.json` entry: MAL id, `title` in the format above, uploader, `nyaa_query`, `file_offset` if the uploader is likely to continue an earlier part's numbering, `pending: true` and a `pending_note`. Turn it on early once MAL has the premiere day and broadcast time (see Before episode 1). On the same day:
   - **Carry-overs.** For every current show without a MAL episode count, check whether it runs into the new season. A carry-over keeps its entry unchanged.
   - **Sequels.** Open the MAL page of every show that ends this season and follow its "Sequel" link. A new part or season is a separate MAL entry (Kusuriya no Hitorigoto 3rd Season Part 2 in April 2027) and gets its own entry once it is announced.
   - **Prune.** Remove the shows that finished two seasons ago (finished shows stay until the season after next).
   - Long runners stay (One Piece).
2. **Premiere weeks.** The Monday refresh turns each show on when its episode 1 appears and checks its release name (step 5).
3. **After the last finales,** usually in the first week of the new season, check that every old show has its last episode logged and marked `(Final)`.

## Research from a cloud session
From the cloud, `curl` to MAL, Nyaa, Jikan and AniList is blocked; WebFetch reaches MAL, Nyaa RSS and Wikipedia. GitHub's machines (a workflow in this repo) reach Nyaa RSS, MAL pages, MAL's `load.json` lists and `subsplease.org/api/?f=schedule&tz=UTC` directly with `curl` or Python; Jikan times out there and MAL's official API needs a client id.
- MAL's season page (`myanimelist.net/anime/season/<year>/<season>`) is cut off after about 44 entries, and its ONA section is lost. Cross-check with Wikipedia's "<year> in anime" page (loads fully) and `animeschedule.net/seasons/<season>-<year>`. LiveChart loads only partly; AniList and aniSearch fail; MAL's advanced search shows no dates.
- A MAL list can be read newest air date first with `myanimelist.net/animelist/<user>/load.json?status=7&order=14&offset=N`: about 65 entries per response, so step `offset` by 60. Dates there are DD-MM-YY.
- MAL anime pages give the premiere day ("Aired"), the broadcast day and JST time ("Broadcast") and the sequel/prequel links. Streaming services often appear only close to the premiere.
- `subsplease.org/schedule` is built by script and comes back empty.
