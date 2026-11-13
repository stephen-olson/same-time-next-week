# Same Time Next Week

Things to do with people in Durham and Raleigh, NC: jams, dances, classes, run clubs, game nights and volunteer shifts that repeat, so you keep seeing the same faces.

## What's here

| Path | What it is |
| --- | --- |
| `data/events.json` | Every listing. This is the only file you edit by hand. |
| `config.json` | The site address and the links to the suggestion, problem-report and volunteer forms. |
| `template.html` | The page design and app code. |
| `build.py` | Builds the site into `docs/`. |
| `docs/` | The published website (GitHub Pages serves this folder). |
| `docs/cal/*.ics` | Calendar feeds for Apple, Google and Outlook. |
| `UPDATE.md` | The weekly listing check: rules and steps. |
| `tools/snapshot.py` | Saves the date and time lines from each organizer page for the weekly check. |
| `.github/workflows/page-snapshots.yml` | Runs `tools/snapshot.py` every Monday morning and saves the results on the `snapshots` branch. |

## Build

```bash
python3 -I build.py
```

The site address and form links come from `config.json`.

## How it stays up to date

Every Monday:

1. At about 10:17 UTC, a GitHub Action saves the date and time lines from each organizer page on the `snapshots` branch.
2. At about 12:00 UTC (7am Eastern), a scheduled Claude Code cloud session follows `UPDATE.md`. It checks every listing against those page copies and web search, puts anything it can't confirm on hold, rebuilds the site and publishes it.

## How listings work

- Calendar events are things you can show up to on a date. Ones that need a quick sign-up or ticket are marked **Sign up first**.
- Things that need joining first (memberships, applications, leagues) stay in the data but aren't shown. Multi-week classes appear on their first session date.
- Weekly and monthly events are shown about six weeks ahead of the last build. If the weekly check stops running, listings run out rather than going stale.

See `UPDATE.md` for the full quality rules.
