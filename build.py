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
CATEGORIES = {"music", "dance", "art", "fitness", "games", "learning", "social", "volunteer"}
FEEDS = {
    "durham": ("Same Time Next Week: Durham", lambda e: e["city"] == "durham"),
    "raleigh": ("Same Time Next Week: Raleigh", lambda e: e["city"] == "raleigh"),
    "all": ("Same Time Next Week: Durham and Raleigh", lambda e: True),
    "durham-volunteer": ("Same Time Next Week: Durham volunteering", lambda e: e["city"] == "durham" and e.get("philanthropy")),
    "raleigh-volunteer": ("Same Time Next Week: Raleigh volunteering", lambda e: e["city"] == "raleigh" and e.get("philanthropy")),
}
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
    if not c or low in ("not listed", "check the website"):
        return False, ""
    s = re.split(r"\s*[\(;]", c)[0].strip()
    return False, s if len(s) <= 28 else s[:26].rstrip() + "…"


def validate(events):
    seen = set()
    for e in events:
        where = f"{e.get('id')} ({e.get('title')})"
        assert e.get("id") and e["id"] not in seen, f"duplicate or missing id: {where}"
        seen.add(e["id"])
        assert re.fullmatch(r"[a-z0-9-]+", e["id"]), f"bad id: {where}"
        assert e.get("city") in ("durham", "raleigh"), f"bad city: {where}"
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


# ---------- calendar feeds ----------

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
    lines.append("END:VEVENT")
    return lines


def write_feeds(events, out, today, stamp):
    (out / "cal").mkdir(parents=True, exist_ok=True)
    since = today - dt.timedelta(days=7)
    for name, (title, keep) in FEEDS.items():
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Same Time Next Week//EN", "CALSCALE:GREGORIAN",
                 "METHOD:PUBLISH", f"X-WR-CALNAME:{ics_esc(title)}", "X-WR-TIMEZONE:America/New_York",
                 "X-WR-CALDESC:Social events in Durham and Raleigh\\, NC. Every listing is re-checked weekly.",
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
    def mix(a, b, t):
        return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(4))
    ink, dot, hi, clear = (44, 76, 156, 255), (244, 246, 241, 255), (108, 207, 152, 255), (0, 0, 0, 0)
    s = size / 32.0
    radius = 8 * s
    centers = [(cx * s, cy * s) for cy in (9, 16, 23) for cx in (9, 16, 23)]
    r = 2.6 * s
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            dx = max(radius - px, 0, px - (size - radius))
            dy = max(radius - py, 0, py - (size - radius))
            edge = radius - (dx * dx + dy * dy) ** 0.5 if (dx or dy) else min(px, py, size - px, size - py) + radius
            a = max(0.0, min(1.0, edge + 0.5))
            col = mix(clear, ink, a)
            for i, (cx, cy) in enumerate(centers):
                t = max(0.0, min(1.0, r - ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5 + 0.5))
                if t > 0:
                    col = mix(col, hi if i == 4 else dot, t)
            row += bytes(col)
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


ICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#2C4C9C"/>'
            + "".join(f'<circle cx="{cx}" cy="{cy}" r="2.6" fill="{"#6CCF98" if (cx, cy) == (16, 16) else "#F4F6F1"}"/>'
                      for cy in (9, 16, 23) for cx in (9, 16, 23)) + "</svg>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--out", default=str(ROOT / "docs"))
    ap.add_argument("--site-url", default="")
    ap.add_argument("--report-url", default="")
    ap.add_argument("--suggest-url", default="")
    ap.add_argument("--preview", default="")
    args = ap.parse_args()

    today = d(args.today)
    out = Path(args.out)
    cfg_path = ROOT / "config.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    site_url = args.site_url or cfg.get("siteUrl", "")
    report_url = args.report_url or cfg.get("reportUrl", "")
    suggest_url = args.suggest_url or cfg.get("suggestUrl", "")
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
        if e["kind"] == "program":
            continue  # join-first programs stay in the data but are not shown
        free, short_cost = cost_info(e.get("cost"))
        c = {k: v for k, v in e.items() if not k.startswith("_") and k not in
             ("recurrence", "dates", "except", "schedule", "tier", "hold", "holdReason", "holdSince", "evidence")}
        c.update(occ=[x.isoformat() for x in occ], rtext=rtext(e, occ, today), free=free, costShort=short_cost)
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
        "preview": False,
        "holidays": hol_labels,
        "events": client,
    }

    template = (ROOT / "template.html").read_text()
    head, body = template.split("<!--BODY-->", 1)

    def page(preview):
        blob = json.dumps(dict(data, preview=preview), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        return body.replace("__DATA__", blob)

    extra_head = (
        '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<link rel="manifest" href="manifest.webmanifest">\n<link rel="icon" href="icon.svg" type="image/svg+xml">\n'
        '<link rel="apple-touch-icon" href="icon-180.png">\n'
        '<meta name="theme-color" content="#F4F6F1" media="(prefers-color-scheme: light)">\n'
        '<meta name="theme-color" content="#101411" media="(prefers-color-scheme: dark)">\n'
        '<meta name="apple-mobile-web-app-title" content="Same Time Next Week">\n'
        '<meta property="og:type" content="website">\n<meta property="og:site_name" content="Same Time Next Week">\n'
        '<meta property="og:title" content="Same Time Next Week: recurring things to do with people in Durham and Raleigh">\n'
        '<meta property="og:description" content="Jams, dances, run clubs, game nights and volunteer shifts that happen every week or month. Just show up, and keep coming back. Checked weekly.">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
    )
    if site_url:
        extra_head += (f'<meta property="og:url" content="{site_url}">\n'
                       f'<meta property="og:image" content="{site_url}og-card.png">\n'
                       '<meta property="og:image:width" content="1200">\n<meta property="og:image:height" content="630">\n'
                       '<meta property="og:image:alt" content="Same Time Next Week: recurring things to do with people in Durham and Raleigh">\n')
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(f'<!doctype html>\n<html lang="en">\n<head>\n{extra_head}{head}</head>\n<body>\n{page(False)}</body>\n</html>\n')
    write_feeds(events, out, today, stamp)
    (out / "manifest.webmanifest").write_text(json.dumps({
        "name": "Same Time Next Week", "short_name": "Same Time", "start_url": "./", "display": "standalone",
        "background_color": "#F4F6F1", "theme_color": "#F4F6F1",
        "icons": [{"src": "icon-180.png", "sizes": "180x180", "type": "image/png"},
                  {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
                  {"src": "icon.svg", "sizes": "any", "type": "image/svg+xml"}],
    }, indent=1))
    (out / "icon.svg").write_text(ICON_SVG)
    for size in (180, 512):
        p = out / f"icon-{size}.png"
        if not p.exists():
            p.write_bytes(png(size))
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
