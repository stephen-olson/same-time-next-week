# Same Time Next Week

Things to do with people in Durham and Raleigh, NC: jams, dances, classes, run clubs, game nights and volunteer shifts that repeat, so you keep seeing the same faces.

## What's here

| Path | What it is |
| --- | --- |
| `data/events.json` | Every listing. This is the only file you edit by hand. |
| `template.html` | The page design and app code. |
| `build.py` | Builds the site into `docs/`. |
| `docs/` | The published website (GitHub Pages serves this folder). |
| `docs/cal/*.ics` | Calendar subscription feeds for Apple, Google and Outlook. |
| `UPDATE.md` | The weekly listing check: rules and steps. |

## Build

```bash
python3 -I build.py --site-url "https://YOUR-SITE-ADDRESS/"
```

Add `--report-url` with a form or email link to show a "Suggest a listing or report a problem" link in the footer.

## How listings work

- Calendar events are things you can show up to on a date. They're marked **Just show up** or **Sign up first**.
- Things that need joining first (memberships, applications, multi-week classes, leagues) live in **Join anytime**.
- Weekly and monthly events are shown about six weeks ahead of the last build. If the weekly check stops running, listings run out rather than going stale.

See `UPDATE.md` for the full quality rules.
