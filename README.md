# Page copies for the weekly listing check

Every Monday morning a GitHub Action (`.github/workflows/page-snapshots.yml` on `main`)
opens each organizer page linked from `data/events.json` and saves the lines that mention
dates, times, prices or the listing's name. The weekly check runs in a cloud session that
can't open most websites, so it reads these instead.

- `index.json`: every page, when it was fetched, its HTTP status and its excerpt file.
- `pages/*.txt`: the excerpts.

This branch is replaced every week. Nothing here appears on the site.
