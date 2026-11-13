# Weekly listing check

This is the playbook for the automated weekly check. It keeps the site honest: only list things that are really happening.

Run it once a week (Monday morning). It takes one pass over `data/events.json`, then rebuilds the site and publishes it.

## The rules every listing must meet

A listing stays on the site only if all of these are true:

1. **Established host.** A venue, nonprofit, shop, city program, or a group with a long track record. Meetup groups count only with 6+ months of regular events and steady turnout (10+ people at recent events).
2. **It repeats**, weekly or monthly. One-off events are allowed only when they're built for meeting people (holiday volunteer drives, cleanups, one-day workshops).
3. **Proof it's happening.** The organizer's own page, calendar or social account shows either the specific date, or a stated weekly/monthly schedule with activity in the last 30 days. Listings that only appear on aggregators (Eventbrite search pages, tourism calendars, magazine roundups) don't count on their own.
4. **Built for newcomers.** A lesson, rotating partners, a host who seats new people, or a shared task.

Calendar listings must be things you can **show up to on a date**:
- `"entry": "show"`: just show up, no paperwork.
- `"entry": "signup"`: a quick sign-up or ticket for that date (most volunteer shifts, one-day workshops).

Anything that needs joining first (memberships like Toastmasters, applications, orientations, leagues) is a **program** (`"kind": "program"`). Programs stay in the data but are not shown on the site.

**Classes and workshops** (pottery, drawing, painting, printmaking, sewing, improv) are listed as `"entry": "signup"` events:
- Price cap: about $50 per session on average with materials included, or up to about $100 for a one-day workshop.
- One-day workshops show on their dates. Multi-week classes show only on their **first session date**, with `"multi": true` and the full schedule in `"schedule"` (days, times, number of weeks, end date, when registration opens).
- Remove a class once it's sold out with no waitlist, or once its first session has passed.
- Beginner-friendly only. Leave out advanced-only sessions.

## Fields that matter

- `tier: "confirmed"`: shows only the dates in `dates` (dates the organizer has posted).
- `tier: "regular"`: shows the `recurrence` pattern about six weeks ahead of the build date, skipping major holidays, plus anything in `dates`. Use only when the organizer states the schedule and was active in the last 30 days.
- `except`: dates that are cancelled or skipped.
- `hold: true` (+ `holdReason`, `holdSince`): hides a listing without deleting it.
- `lastChecked`: the date you last verified it.
- Never change an `id`. People's saved plans and shared links depend on it.

## Steps

0. **Check how you'll read organizer pages.** Fetch two listing URLs from `data/events.json`. If both fail with a network error (for example `403`, `host_not_allowed`, `ENOTFOUND` or a timeout), this run can't open websites directly. Use the page copies instead:
   - Every Monday morning a GitHub Action (`.github/workflows/page-snapshots.yml`) opens each organizer page and saves its lines with dates, times, prices and the listing's name on the `snapshots` branch. Run `git fetch -q origin snapshots`, then `git show origin/snapshots:index.json`. It lists each page, its HTTP status and its file. Read a file with `git show origin/snapshots:pages/<file>`.
   - Use the copies only if `fetchedAt` is from the last 2 days. Combine them with web search, which works from the cloud.
   - If there are no recent copies, that's a setup problem, not a listing problem. Don't put anything on hold and don't change any `lastChecked`. Skip to step 7, rebuild and publish, and put "Couldn't open web pages this week" at the top of your summary.
   - A page that returned `403` or a network error, or a copy with no dates, tells you nothing about the listing: check it with web search before counting a miss. A `404` or `410` means the page is gone, so look for the organizer's new page.
1. Read `data/events.json`.
2. For each listing (events and programs), open its `url` and the organizer's own calendar or social page (or read their page copies from step 0), and check:
   - Is it still running? Same day, time, place and cost?
   - New dates posted? For `confirmed`, add them to `dates`. For `regular`, nothing to add unless a special date was posted.
   - Cancellations or holiday skips? Add them to `except`.
   - Changes to time, venue, cost or how to join? Update the fields.
   - If it's verified, set `lastChecked` to today.
3. If a listing **can't be verified** (a miss). Its `lastChecked` date tells you whether last week was a miss too:
   - First miss (`lastChecked` is 10 days old or less): leave it, but if its next date is within 7 days and there's real doubt, set `hold: true` with a reason.
   - Two weekly misses in a row (`lastChecked` is more than 10 days old), or the organizer says it ended: set `hold: true`, `holdReason`, `holdSince`.
   - Held for 8+ weeks with no sign of life: delete the listing.
   - A held listing that shows new activity: remove `hold` and set `lastChecked`.
4. **Read visitor reports.** List open GitHub issues with the REST API: `gh api "repos/stephen-olson/same-time-next-week/issues?state=open&per_page=100"` (skip items that have a `pull_request` field; `gh issue` commands don't work in cloud runs). For each issue labeled `problem`, check the organizer's page and fix the listing if the report is right. For each issue labeled `suggestion`, check it against the rules above. Don't comment on, label or close issues: the owner does that.
   For each issue labeled `volunteer-submission` (posted by organizations), verify before suggesting it: the organization has a public website; the opportunity appears on that website or its own sign-up page; nonprofits show up in the IRS Tax Exempt Organization Search (apps.irs.gov/app/eos); the location is public or the organization's facility; nothing asks volunteers to pay beyond a stated background-check fee. If any check fails, don't suggest it. Never contact anyone yourself.
5. **Don't add new listings automatically.** If you find a strong candidate that meets every rule, add it to `data/candidates.json` (same fields, plus a `whyItQualifies` note) for the owner to review.
6. Keep text written for visitors: plain, short, no mention of how the information was found.
7. Rebuild: `python3 -I build.py` (the site address and form links come from `config.json`). It must print a `built ...` line with no error. Always rebuild weekly, even if nothing changed, because the six-week window moves with the build date.
8. Publish: first set the commit identity so the owner's email stays private: `git config user.name "Stephen Olson"` and `git config user.email "stephen-olson@users.noreply.github.com"`. Then commit `data/` and `docs/` on `main` with the message `Weekly listing check YYYY-MM-DD` and push to `main`.
9. Write a short summary: listings updated, put on hold, removed, new dates added, and candidates suggested.
