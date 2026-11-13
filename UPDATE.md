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

1. Read `data/events.json`.
2. For each listing (events and programs), open its `url` and the organizer's own calendar or social page, and check:
   - Is it still running? Same day, time, place and cost?
   - New dates posted? For `confirmed`, add them to `dates`. For `regular`, nothing to add unless a special date was posted.
   - Cancellations or holiday skips? Add them to `except`.
   - Changes to time, venue, cost or how to join? Update the fields.
   - If it's verified, set `lastChecked` to today.
3. If a listing **can't be verified**:
   - First miss: leave it, but if its next date is within 7 days and there's real doubt, set `hold: true` with a reason.
   - Two weekly misses in a row, or the organizer says it ended: set `hold: true`, `holdReason`, `holdSince`.
   - Held for 8+ weeks with no sign of life: delete the listing.
   - A held listing that shows new activity: remove `hold` and set `lastChecked`.
4. **Read visitor reports.** List open GitHub issues (`gh issue list --repo stephen-olson/same-time-next-week --state open`). For each issue labeled `problem`, check the organizer's page and fix the listing if the report is right. For each issue labeled `suggestion`, check it against the rules above. Don't comment on, label or close issues: the owner does that.
   For each issue labeled `volunteer-submission` (posted by organizations), verify before suggesting it: the organization has a public website; the opportunity appears on that website or its own sign-up page; nonprofits show up in the IRS Tax Exempt Organization Search (apps.irs.gov/app/eos); the location is public or the organization's facility; nothing asks volunteers to pay beyond a stated background-check fee. If any check fails, don't suggest it. Never contact anyone yourself.
5. **Don't add new listings automatically.** If you find a strong candidate that meets every rule, add it to `data/candidates.json` (same fields, plus a `whyItQualifies` note) for the owner to review.
6. Keep text written for visitors: plain, short, no mention of how the information was found.
7. Rebuild: `python3 -I build.py` (the site address and form links come from `config.json`). It must print a `built ...` line with no error. Always rebuild weekly, even if nothing changed, because the six-week window moves with the build date.
8. Publish: commit `data/` and `docs/` with the message `Weekly listing check YYYY-MM-DD` and push.
9. Write a short summary: listings updated, put on hold, removed, new dates added, and candidates suggested.
