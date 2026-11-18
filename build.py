#!/usr/bin/env python3
"""Build the Same Time Next Week website from data/events.json.

Writes to --out (default: docs/):
  index.html                 the whole site (data inlined)
  cal/<feed>.ics             calendar subscription feeds
  manifest.webmanifest, icon.svg, icon-180.png, icon-512.png, .nojekyll

Date rules:
  - "confirmed" events show only the dates in their "dates" list.
  - "regular" events show their weekly/monthly pattern from a month ago until
    HORIZON_DAYS after the build date (skipping major holidays), plus any
    posted "dates". If the weekly check stops running, listings run out
    instead of going stale.

Usage:
  python3 -I build.py [--today YYYY-MM-DD] [--out DIR] [--site-url URL]
                      [--report-url URL] [--preview FILE]
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HORIZON_DAYS = 42
PAST_DAYS = 31
DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
CATEGORIES = {"music", "dance", "art", "fitness", "trivia", "games", "comedy", "books", "learning", "social", "volunteer"}
FEEDS = {
    "durham": ("Same Time Next Week: Durham", lambda e: e["city"] == "durham"),
    "raleigh": ("Same Time Next Week: Raleigh", lambda e: e["city"] == "raleigh"),
    "chapelhill": ("Same Time Next Week: Chapel Hill & Carrboro", lambda e: e["city"] == "chapelhill"),
    "all": ("Same Time Next Week: all areas", lambda e: True),
    "durham-volunteer": ("Same Time Next Week: Durham volunteering", lambda e: e["city"] == "durham" and e.get("philanthropy")),
    "raleigh-volunteer": ("Same Time Next Week: Raleigh volunteering", lambda e: e["city"] == "raleigh" and e.get("philanthropy")),
    "chapelhill-volunteer": ("Same Time Next Week: Chapel Hill & Carrboro volunteering",
                             lambda e: e["city"] == "chapelhill" and e.get("philanthropy")),
}
CITIES = ("durham", "raleigh", "chapelhill")  # chapelhill = Chapel Hill & Carrboro
VTIMEZONE = [
    "BEGIN:VTIMEZONE", "TZID:America/New_York",
    "BEGIN:DAYLIGHT", "TZOFFSETFROM:-0500", "TZOFFSETTO:-0400", "TZNAME:EDT",
    "DTSTART:19700308T020000", "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU", "END:DAYLIGHT",
    "BEGIN:STANDARD", "TZOFFSETFROM:-0400", "TZOFFSETTO:-0500", "TZNAME:EST",
    "DTSTART:19701101T020000", "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", "END:STANDARD",
    "END:VTIMEZONE",
]


def d(s):
    return dt.date.fromisoformat(s)


def nth_weekday(year, month, weekday, n):
    if n > 0:
        first = dt.date(year, month, 1)
        day = first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
        return day if day.month == month else None
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


def holidays(years):
    """date -> (label, skip_regular_events)"""
    out = {}
    for y in years:
        out[dt.date(y, 1, 1)] = ("New Year's Day", True)
        out[nth_weekday(y, 1, 0, 3)] = ("MLK Day", False)
        out[nth_weekday(y, 2, 0, 3)] = ("Presidents' Day", False)
        out[nth_weekday(y, 5, 0, -1)] = ("Memorial Day", False)
        out[dt.date(y, 7, 4)] = ("Independence Day", True)
        out[nth_weekday(y, 9, 0, 1)] = ("Labor Day", False)
        tg = nth_weekday(y, 11, 3, 4)
        out[tg] = ("Thanksgiving", True)
        out[tg + dt.timedelta(days=1)] = ("Day after Thanksgiving", False)
        out[dt.date(y, 12, 24)] = ("Christmas Eve", True)
        out[dt.date(y, 12, 25)] = ("Christmas Day", True)
        out[dt.date(y, 12, 31)] = ("New Year's Eve", True)
    return out


def as_list(x):
    return x if isinstance(x, list) else [x]


def pattern_dates(rec, start, end):
    out = set()
    if rec["type"] == "weekly":
        wds = {DAYS[x[:3].lower()] for x in rec["days"]}
        cur = start
        while cur <= end:
            if cur.weekday() in wds:
                out.add(cur)
            cur += dt.timedelta(days=1)
    elif rec["type"] == "monthly":
        wds = [DAYS[x[:3].lower()] for x in as_list(rec.get("day", rec.get("days")))]
        y, m = start.year, start.month
        while dt.date(y, m, 1) <= end:
            for w in wds:
                for n in as_list(rec["nth"]):
                    x = nth_weekday(y, m, w, n)
                    if x and start <= x <= end:
                        out.add(x)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return sorted(out)


def occurrences(e, today, hol):
    if e.get("kind") == "program":
        return []
    lo = today - dt.timedelta(days=PAST_DAYS)
    out = {d(x) for x in e.get("dates", []) if d(x) >= lo}
    rec = e.get("recurrence")
    if e.get("tier") == "regular" and rec:
        start = max(lo, d(rec["from"])) if rec.get("from") else lo
        end = today + dt.timedelta(days=HORIZON_DAYS)
        if rec.get("until"):
            end = min(end, d(rec["until"]))
        for x in pattern_dates(rec, start, end):
            if not hol.get(x, ("", False))[1]:
                out.add(x)
    for x in e.get("except", []):
        out.discard(d(x))
    return sorted(out)


def join_list(xs):
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def ordinal(n):
    if n == -1:
        return "last"
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def fmt_date(x):
    return f"{MON[x.month - 1]} {x.day}"


def rtext(e, occ, today):
    if e.get("kind") == "program":
        return e.get("schedule") or "Join any time"
    if e.get("schedule"):
        return e["schedule"]
    rec = e.get("recurrence")
    if e.get("tier") == "regular" and rec:
        if rec["type"] == "weekly":
            idx = sorted({DAYS[x[:3].lower()] for x in rec["days"]})
            t = ("Every day" if len(idx) == 7 else "Every weekday" if idx == [0, 1, 2, 3, 4]
                 else "Every " + join_list([DAY_NAMES[i] for i in idx]))
        else:
            nths = sorted(as_list(rec["nth"]), key=lambda n: 9 if n == -1 else n)
            wds = [DAY_NAMES[DAYS[x[:3].lower()]] for x in as_list(rec.get("day", rec.get("days")))]
            t = f"{join_list([ordinal(n) for n in nths]).capitalize()} {join_list(wds)} of each month"
        if rec.get("until"):
            t += f", through {fmt_date(d(rec['until']))}"
        return t
    future = [x for x in occ if x >= today]
    if not future:
        return "No upcoming dates posted"
    names = [fmt_date(x) for x in future[:4]]
    if len(future) == 1:
        return "One date: " + names[0]
    return join_list(names) if len(future) <= 4 else ", ".join(names) + f" and {len(future) - 4} more"


def cost_info(c):
    c = (c or "").strip()
    low = c.lower()
    free = low.startswith("free") and "non-member" not in low
    if free:
        return True, "Free"
    if not c or low in ("not listed", "check the website") or low.startswith(("no price", "no fee", "not posted", "not listed")):
        return False, ""
    s = re.split(r"\s*[\(;]", c)[0].strip()
    if len(s) > 28:  # keep the first clause ("$349 for 9 weeks") rather than cutting mid-word
        s = re.split(r"\.\s|,\s|\s/\s|\sor\s", s)[0].strip().rstrip(".,")
    if len(s) > 28:
        s = s[:28].rsplit(" ", 1)[0].rstrip(",.;") + "…"
    return False, s


def validate(events):
    seen = set()
    for e in events:
        where = f"{e.get('id')} ({e.get('title')})"
        assert e.get("id") and e["id"] not in seen, f"duplicate or missing id: {where}"
        seen.add(e["id"])
        assert re.fullmatch(r"[a-z0-9-]+", e["id"]), f"bad id: {where}"
        assert e.get("city") in CITIES, f"bad city: {where}"
        assert e.get("kind") in ("event", "program"), f"bad kind: {where}"
        assert e.get("category") in CATEGORIES, f"bad category: {where}"
        assert e.get("title"), f"missing title: {where}"
        if e["kind"] == "event":
            assert e.get("entry") in ("show", "signup"), f"bad entry: {where}"
            assert e.get("tier") in ("confirmed", "regular"), f"bad tier: {where}"
            if e["tier"] == "regular":
                assert e.get("recurrence", {}).get("type") in ("weekly", "monthly"), f"regular needs a pattern: {where}"
            else:
                assert e.get("dates"), f"confirmed needs dates: {where}"
        for k in ("start", "end"):
            if e.get(k):
                assert re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", e[k]), f"bad {k}: {where}"
        if e.get("url"):
            assert re.match(r"https?://", e["url"]), f"bad url: {where}"
        if e.get("geo") is not None:
            g = e["geo"]
            assert (isinstance(g, list) and len(g) == 2 and all(isinstance(x, (int, float)) for x in g)
                    and 33 < g[0] < 37 and -85 < g[1] < -75), f"bad geo (want [lat, lon] in NC): {where}"


# ---------- calendar feeds ----------

def ics_quote(s):
    """A double-quoted iCalendar parameter value (quotes aren't allowed inside)."""
    return '"' + str(s).replace('"', "'") + '"'


def travel_lines(e, alerts=True):
    """Map pin, travel time and leave-now alerts.

    Apple Calendar reads X-APPLE-* and times the alerts from your travel time: 30 minutes before
    you need to leave, then when it's time to leave. Other calendars ignore those parts and use
    the plain offsets after the colon: 1 hour and 30 minutes before the start.
    The whole-city subscription feeds get the map pin only (alerts=False): nobody wants two
    alerts for every event in a city. Events people add one by one get the alerts (template.html).
    """
    lines = []
    loc = ", ".join(x for x in [e.get("venue"), e.get("address")] if x)
    if e.get("geo") and e.get("address"):
        lat, lon = e["geo"]
        lines.append(f"X-APPLE-STRUCTURED-LOCATION;VALUE=URI;X-ADDRESS={ics_quote(e['address'])};X-APPLE-RADIUS=70;"
                     f"X-TITLE={ics_quote(e.get('venue') or e['address'])}:geo:{lat},{lon}")
    if not alerts:
        return lines
    if loc and not e.get("noMap"):
        lines.append("X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:AUTOMATIC")
    if e.get("start"):
        name = e.get("short") or e["title"]
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_esc('Leave in 30 minutes: ' + name)}",
                  "TRIGGER;X-APPLE-RELATED-TRAVEL=-PT30M:-PT1H", "END:VALARM",
                  "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_esc('Time to leave: ' + name)}",
                  "TRIGGER;X-APPLE-RELATED-TRAVEL=PT0S:-PT30M", "END:VALARM"]
    return lines



def ics_esc(s):
    return str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    b = line.encode("utf-8")
    parts = []
    while len(b) > 75:
        cut = 75
        while cut > 0 and (b[cut] & 0xC0) == 0x80:
            cut -= 1
        parts.append(b[:cut])
        b = b" " + b[cut:]
    parts.append(b)
    return b"\r\n".join(parts).decode("utf-8")


def plus_two(t):
    h, m = map(int, t.split(":"))
    return f"{min(h + 2, 23):02d}:{m:02d}"


def vevent(e, day, stamp):
    ds = day.strftime("%Y%m%d")
    lines = ["BEGIN:VEVENT", f"UID:{e['id']}-{ds}@same-time-next-week", f"DTSTAMP:{stamp}"]
    if e.get("start"):
        end = e.get("end") or plus_two(e["start"])
        end_day = day + dt.timedelta(days=1) if end <= e["start"] else day
        lines += [f"DTSTART;TZID=America/New_York:{ds}T{e['start'].replace(':', '')}00",
                  f"DTEND;TZID=America/New_York:{end_day.strftime('%Y%m%d')}T{end.replace(':', '')}00"]
    else:
        lines += [f"DTSTART;VALUE=DATE:{ds}", f"DTEND;VALUE=DATE:{(day + dt.timedelta(days=1)).strftime('%Y%m%d')}"]
    desc = "\n\n".join(x for x in [
        e.get("description"), e.get("timeNote"),
        f"How to join: {e['howToJoin']}" if e.get("howToJoin") else "",
        f"Before you go: {e['verifyNote']}" if e.get("verifyNote") else "",
        e.get("url"), "Listed on Same Time Next Week.",
    ] if x)
    lines += [f"SUMMARY:{ics_esc(e['title'])}",
              f"LOCATION:{ics_esc(', '.join(x for x in [e.get('venue'), e.get('address')] if x))}",
              f"DESCRIPTION:{ics_esc(desc)}"]
    if e.get("url"):
        lines.append(f"URL:{e['url']}")
    lines += travel_lines(e, alerts=False)  # feeds: map pin only
    lines.append("END:VEVENT")
    return lines


def write_feeds(events, out, today, stamp):
    (out / "cal").mkdir(parents=True, exist_ok=True)
    since = today - dt.timedelta(days=7)
    for name, (title, keep) in FEEDS.items():
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Same Time Next Week//EN", "CALSCALE:GREGORIAN",
                 "METHOD:PUBLISH", f"X-WR-CALNAME:{ics_esc(title)}", "X-WR-TIMEZONE:America/New_York",
                 "X-WR-CALDESC:Social events in Durham\\, Raleigh\\, Chapel Hill and Carrboro\\, NC. Every listing is re-checked weekly.",
                 "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H"] + VTIMEZONE
        for e in events:
            if e["kind"] != "event" or not keep(e):
                continue
            for x in e["_occ"]:
                if x >= since:
                    lines += vevent(e, x, stamp)
        lines.append("END:VCALENDAR")
        (out / "cal" / f"{name}.ics").write_text("\r\n".join(fold(l) for l in lines) + "\r\n", encoding="utf-8")


# ---------- icons ----------

def png(size):
    """App icon: a red pushpin holding a paper ticket on cork (drawn with anti-aliased shapes)."""
    s = size / 32.0
    cork, paper, blue, tan, pin, hi = (213, 182, 139), (255, 253, 247), (32, 65, 154), (201, 188, 166), (210, 58, 44), (245, 154, 141)
    # (kind, x, y, w-or-radius, h, corner radius, colour) in a 32-unit box
    shapes = [("rect", 0, 0, 32, 32, 8, cork), ("rect", 8, 10, 16, 16, 1.5, paper), ("rect", 11, 16, 10, 2, 1, blue),
              ("rect", 11, 20, 7, 2, 1, tan), ("circle", 16, 10, 3.6, 0, 0, pin), ("circle", 14.9, 8.9, 1.2, 0, 0, hi)]

    def cover(sh, px, py):
        kind, x, y, w, h, r, _ = sh
        if kind == "circle":
            d = ((px - x * s) ** 2 + (py - y * s) ** 2) ** 0.5 - w * s
        else:
            cx, cy, bx, by, rr = (x + w / 2) * s, (y + h / 2) * s, w / 2 * s, h / 2 * s, r * s
            qx, qy = abs(px - cx) - bx + rr, abs(py - cy) - by + rr
            d = (max(qx, 0) ** 2 + max(qy, 0) ** 2) ** 0.5 + min(max(qx, qy), 0) - rr
        return max(0.0, min(1.0, 0.5 - d))

    rows = []
    for yy in range(size):
        row = bytearray([0])
        for xx in range(size):
            px, py = xx + 0.5, yy + 0.5
            a0 = cover(shapes[0], px, py)
            col = list(shapes[0][6])
            for sh in shapes[1:]:
                c = cover(sh, px, py)
                if c:
                    col = [round(col[i] + (sh[6][i] - col[i]) * c) for i in range(3)]
            row += bytes(col + [round(255 * a0)])
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


ICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#D5B68B"/>'
            '<rect x="8" y="10" width="16" height="16" rx="1.5" fill="#FFFDF7"/><rect x="11" y="16" width="10" height="2" rx="1" fill="#20419A"/>'
            '<rect x="11" y="20" width="7" height="2" rx="1" fill="#C9BCA6"/><circle cx="16" cy="10" r="3.6" fill="#D23A2C"/>'
            '<circle cx="14.9" cy="8.9" r="1.2" fill="#F59A8D"/></svg>')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--out", default=str(ROOT / "docs"))
    ap.add_argument("--site-url", default="")
    ap.add_argument("--report-url", default="")
    ap.add_argument("--suggest-url", default="")
    ap.add_argument("--preview", default="")
    ap.add_argument("--template", default=str(ROOT / "template.html"), help="page design to build from (for trying alternate designs)")
    args = ap.parse_args()

    today = d(args.today)
    out = Path(args.out)
    cfg_path = ROOT / "config.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    site_url = args.site_url or cfg.get("siteUrl", "")
    report_url = args.report_url or cfg.get("reportUrl", "")
    suggest_url = args.suggest_url or cfg.get("suggestUrl", "")
    # Optional visit counter: the site code from goatcounter.com (cookie-free, anonymous counts).
    counter = str(cfg.get("goatcounter") or "").strip().lower()
    if counter and not re.fullmatch(r"[a-z0-9-]+", counter):
        raise SystemExit(f"config.json: goatcounter should be just the site code (letters, numbers, dashes), not {counter!r}")
    events = json.loads((ROOT / "data" / "events.json").read_text())["events"]
    validate(events)
    hol = holidays(range(today.year - 1, today.year + 2))
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    held = [e for e in events if e.get("hold")]
    events = [e for e in events if not e.get("hold")]
    client = []
    for e in events:
        occ = occurrences(e, today, hol)
        e["_occ"] = occ
        if e["kind"] == "program" and e.get("pgroup") != "volunteer":
            continue  # join-first programs other than volunteer roles stay in the data but are not shown
        free, short_cost = cost_info(e.get("cost"))
        c = {k: v for k, v in e.items() if not k.startswith("_") and k not in
             ("recurrence", "dates", "except", "schedule", "tier", "hold", "holdReason", "holdSince", "evidence")}
        c.update(occ=[x.isoformat() for x in occ], rtext=rtext(e, occ, today), free=free, costShort=short_cost)
        town = re.search(r"(?:^|,)\s*([A-Za-z .'-]+?),\s*NC\b", e.get("address") or "")
        if town and not re.search(r"durham|raleigh", town.group(1), re.I):
            c["area"] = town.group(1).strip()
        if e["kind"] == "event" and not occ:
            continue  # nothing to show right now
        client.append(c)

    lo, hi = today - dt.timedelta(days=PAST_DAYS), max([x for e in events for x in e["_occ"]] + [today])
    hol_labels = {k.isoformat(): v[0] for k, v in hol.items() if lo <= k <= hi}
    data = {
        "generated": today.isoformat(),
        "horizonEnd": (today + dt.timedelta(days=HORIZON_DAYS)).isoformat(),
        "siteUrl": site_url,
        "reportUrl": report_url,
        "suggestUrl": suggest_url,
        "volunteerUrl": cfg.get("volunteerUrl", ""),
        "counter": bool(counter),
        "preview": False,
        "holidays": hol_labels,
        "events": client,
    }

    template = Path(args.template).read_text()
    head, body = template.split("<!--BODY-->", 1)

    def page(preview):
        blob = json.dumps(dict(data, preview=preview), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        return body.replace("__DATA__", blob)

    extra_head = (
        '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<link rel="manifest" href="manifest.webmanifest">\n<link rel="icon" href="icon.svg" type="image/svg+xml">\n'
        '<link rel="apple-touch-icon" href="icon-180.png">\n'
        '<meta name="theme-color" content="#D5B68B" media="(prefers-color-scheme: light)">\n'
        '<meta name="theme-color" content="#D5B68B" media="(prefers-color-scheme: dark)">\n'
        '<meta name="apple-mobile-web-app-title" content="Same Time Next Week">\n'
        '<meta property="og:type" content="website">\n<meta property="og:site_name" content="Same Time Next Week">\n'
        '<meta property="og:title" content="Same Time Next Week: recurring things to do with people in Durham, Raleigh and Chapel Hill">\n'
        '<meta property="og:description" content="Jams, dances, run clubs, game nights and volunteer shifts that happen every week or month. Just show up, and keep coming back. Checked weekly.">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
    )
    card = ROOT / "assets" / "og-card.png"
    card_version = hashlib.sha1(card.read_bytes()).hexdigest()[:8] if card.exists() else "1"  # new image, new link, so shared previews refresh
    if site_url:
        extra_head += (f'<link rel="canonical" href="{site_url}">\n'
                       f'<meta property="og:url" content="{site_url}">\n'
                       f'<meta property="og:image" content="{site_url}og-card.png?v={card_version}">\n'
                       '<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">\n'
                       '<meta property="og:image:alt" content="Same Time Next Week: recurring things to do with people in Durham, Raleigh and Chapel Hill">\n')
    if counter:
        extra_head += (f'<script data-goatcounter="https://{counter}.goatcounter.com/count" '
                       'async src="https://gc.zgo.at/count.js"></script>\n')
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(f'<!doctype html>\n<html lang="en">\n<head>\n{extra_head}{head}</head>\n<body>\n{page(False)}</body>\n</html>\n')
    write_feeds(events, out, today, stamp)
    (out / "manifest.webmanifest").write_text(json.dumps({
        "name": "Same Time Next Week", "short_name": "Same Time", "start_url": "./", "display": "standalone",
        "background_color": "#D5B68B", "theme_color": "#D5B68B",
        "icons": [{"src": "icon-180.png", "sizes": "180x180", "type": "image/png"},
                  {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
                  {"src": "icon.svg", "sizes": "any", "type": "image/svg+xml"}],
    }, indent=1))
    (out / "icon.svg").write_text(ICON_SVG)
    for size in (180, 512):
        p = out / f"icon-{size}.png"
        p.write_bytes(png(size))  # always redraw, so icon color changes reach the site
    (out / ".nojekyll").write_text("")
    for asset in sorted((ROOT / "assets").glob("*")) if (ROOT / "assets").is_dir() else []:
        (out / asset.name).write_bytes(asset.read_bytes())
    if args.preview:
        Path(args.preview).write_text(head + page(True))

    shown = [c for c in client if c["kind"] == "event"]
    print(f"built {out} for {today}: {len(shown)} events with dates, "
          f"{sum(len(c['occ']) for c in shown)} dates, {sum(c['kind'] == 'program' for c in client)} programs, "
          f"{len(events) - len(client)} with no dates in range, {len(held)} on hold")


if __name__ == "__main__":
    main()
