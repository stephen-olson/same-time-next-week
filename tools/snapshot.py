#!/usr/bin/env python3
"""Save the date and time lines from every organizer page the weekly check looks at.

The weekly listing check runs in a cloud session that can't open most websites.
A GitHub Action (.github/workflows/page-snapshots.yml) runs this script on Monday
mornings and saves the results on the `snapshots` branch, where the check reads them.

Only short excerpts are kept: lines that mention a date, time, price or the listing's
name, plus any events the page lists in its structured data.

Usage: python3 -I tools/snapshot.py OUT_DIR
"""
import concurrent.futures
import datetime
import hashlib
import html.parser
import json
import pathlib
import re
import ssl
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
MAX_BYTES = 4_000_000       # stop reading a page after this much
MAX_EXCERPT = 8_000         # characters of excerpt kept per page
MAX_LINE = 300              # characters kept per line
MAX_URLS_PER_LISTING = 4

MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
KEY = re.compile(
    rf"\b{MONTH}\.?\s+\d{{1,2}}\b"                       # Nov 19
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"                 # 11/19
    r"|\b20\d\d-\d\d-\d\d\b"                             # 2026-11-19
    r"|\b(?:mon|tues|wednes|thurs|fri|satur|sun)days?\b" # Thursdays
    rf"|\b(?:mon|tue|wed|thu|fri|sat|sun)[.,]?\s+(?:\d|{MONTH}\b)"  # Thu, Nov 19
    r"|\b\d{1,2}(?::\d\d)?\s*(?:am|pm|a\.m\.|p\.m\.)"     # 7:30pm
    r"|\$\s?\d"                                          # $15
    r"|\b(?:free|cancel\w*|postpone\w*|resched\w*|closed|hiatus|no longer|weekly|monthly|every)\b",
    re.I)
URL_RE = re.compile(r"https?://[^\s)\]'\"<>,;]+", re.I)
BARE_RE = re.compile(
    r"(?<![\w@/.:-])((?:[a-z0-9-]+\.)+(?:com|org|net|gov|edu|us|ag|io|co|info|church)(?:/[^\s)\]'\"<>,;:]*)?)",
    re.I)
STOP = {
    "with", "night", "nights", "the", "and", "for", "from", "all", "you", "our", "new", "fun",
    "day", "days", "age", "ages", "its", "your", "social", "class", "classes",
    "weekly", "monthly", "open", "free", "durham", "raleigh", "carrboro", "chapel", "hill",
    "cary", "event", "events", "meetup", "group", "club", "downtown", "center", "centre",
    "north", "south", "east", "west", "street", "park", "beginner", "beginners", "intro",
}

README = """# Page copies for the weekly listing check

Every Monday morning a GitHub Action (`.github/workflows/page-snapshots.yml` on `main`)
opens each organizer page linked from `data/events.json` and saves the lines that mention
dates, times, prices or the listing's name. The weekly check runs in a cloud session that
can't open most websites, so it reads these instead.

- `index.json`: every page, when it was fetched, its HTTP status and its excerpt file.
- `pages/*.txt`: the excerpts.

This branch is replaced every week. Nothing here appears on the site.
"""


class Page(html.parser.HTMLParser):
    """Pull visible text, the title, descriptions and JSON-LD blocks out of a page."""

    SKIP = {"script", "style", "noscript", "svg", "template"}
    BREAK = {"br", "p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
             "section", "article", "header", "footer", "ul", "ol", "dl", "dt", "dd", "time",
             "table", "main", "aside", "nav", "figure", "figcaption", "blockquote", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.ld, self.meta = [], [], {}
        self.title, self.skip, self.in_title, self.in_ld = "", 0, False, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").lower().strip() == "application/ld+json":
            self.in_ld = True
            self.ld.append("")
            return
        if tag == "meta":
            name = (a.get("property") or a.get("name") or "").lower()
            if name in ("description", "og:description", "og:title") and a.get("content"):
                self.meta.setdefault(name, a["content"])
            return
        if tag == "title":
            self.in_title = True
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BREAK:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "meta":
            self.handle_starttag(tag, attrs)
        elif tag in ("br", "hr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "script" and self.in_ld:
            self.in_ld = False
            return
        if tag == "title":
            self.in_title = False
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BREAK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_ld:
            self.ld[-1] += data
        elif self.in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def ld_events(blobs):
    """One line per event found in the page's JSON-LD structured data."""
    found = []

    def walk(x):
        if isinstance(x, list):
            for item in x:
                walk(item)
        elif isinstance(x, dict):
            types = x.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(isinstance(t, str) and t.endswith("Event") for t in types):
                loc = x.get("location")
                if isinstance(loc, list):
                    loc = loc[0] if loc else None
                place = loc.get("name") if isinstance(loc, dict) else loc if isinstance(loc, str) else ""
                status = str(x.get("eventStatus") or "").rsplit("/", 1)[-1]
                bits = [x.get("name"), x.get("startDate"), x.get("endDate"), place, status]
                found.append(" | ".join(str(b).strip() for b in bits if b))
            for v in x.values():
                if isinstance(v, (list, dict)):
                    walk(v)

    for blob in blobs:
        try:
            walk(json.loads(blob))
        except (ValueError, RecursionError):
            pass
    return list(dict.fromkeys(found))[:60]


def title_words(listings):
    words = set()
    for e in listings:
        text = f"{e.get('title', '')} {e.get('venue', '')}".lower()
        words.update(w for w in re.findall(r"[a-z][a-z'-]{2,}", text) if w not in STOP)
    return words


def excerpt(text, words):
    """Lines naming the listing (with the lines around them) first, then other date/time lines."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    lows = [line.lower() for line in lines]
    # A word that shows up all over the page (like "improv" on an improv theater's
    # site) doesn't point to this listing, so match on the rarer words when there are any.
    counts = {w: sum(1 for low in lows if re.search(rf"\b{re.escape(w)}", low)) for w in words}
    rare = {w for w, c in counts.items() if 0 < c <= 10} or {w for w, c in counts.items() if c}
    named, dated = [], []
    for i, line in enumerate(lines):
        if any(re.search(rf"\b{re.escape(w)}", lows[i]) for w in rare):
            named.extend(range(i - 1, i + 4))
        elif KEY.search(line):
            dated.extend((i - 1, i))
    keep, total = set(), 0
    for i in named + dated:
        if 0 <= i < len(lines) and i not in keep:
            size = min(len(lines[i]), MAX_LINE) + 1
            if total + size > MAX_EXCERPT:
                break
            keep.add(i)
            total += size
    out, last = [], None
    for i in sorted(keep):
        if last is not None and i != last + 1:
            out.append("…")
        line = lines[i]
        out.append(line if len(line) <= MAX_LINE else line[:MAX_LINE] + "…")
        last = i
    return "\n".join(out)


def listing_urls(e):
    found = [e["url"]] if e.get("url") else []
    for field in ("evidence", "verifyNote"):
        s = e.get(field) or ""
        found += [m.group(0) for m in URL_RE.finditer(s)]
        found += ["https://" + m.group(1) for m in BARE_RE.finditer(s)]
    clean = []
    for u in found:
        u = u.rstrip(".,:;)'\"")
        if u not in clean:
            clean.append(u)
    return clean[:MAX_URLS_PER_LISTING]


CTX = ssl.create_default_context()


def fetch(url, tries=2):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=40, context=CTX) as r:
            raw = r.read(MAX_BYTES)
            charset = r.headers.get_content_charset() or "utf-8"
            return {"status": r.status, "finalUrl": r.geturl(),
                    "type": r.headers.get_content_type(),
                    "body": raw.decode(charset, "replace")}
    except urllib.error.HTTPError as err:
        return {"status": err.code, "error": f"HTTP {err.code}"}
    except Exception as err:  # network errors, timeouts, bad TLS: try once more
        if tries > 1:
            return fetch(url, tries - 1)
        return {"status": None, "error": f"{type(err).__name__}: {str(err)[:150]}"}


def render(url, res, listings, fetched_at):
    page = Page()
    try:
        page.feed(res["body"])
        page.close()
    except Exception:  # malformed HTML: keep whatever was parsed
        pass
    events = ld_events(page.ld)
    body = excerpt("".join(page.parts), title_words(listings))
    head = [
        f"URL: {url}",
        f"Fetched: {fetched_at} (HTTP {res['status']}"
        + (f", ended at {res['finalUrl']}" if res["finalUrl"] != url else "") + ")",
        f"For listings: {', '.join(e['id'] for e in listings)}",
    ]
    title = re.sub(r"\s+", " ", page.title).strip() or page.meta.get("og:title", "")
    if title:
        head.append(f"Page title: {title[:200]}")
    desc = page.meta.get("og:description") or page.meta.get("description")
    if desc:
        head.append(f"Description: {re.sub(r'\s+', ' ', desc).strip()[:400]}")
    parts = ["\n".join(head)]
    if events:
        parts.append("Events in the page's structured data (name | start | end | place | status):\n"
                     + "\n".join(f"- {line}" for line in events))
    parts.append("Lines with dates, times, prices or the listing's name:\n"
                 + (body or "(none found; the page may load its calendar with JavaScript)"))
    return "\n\n".join(parts) + "\n", len(body), len(events)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = pathlib.Path(sys.argv[1])
    (out / "pages").mkdir(parents=True, exist_ok=True)
    data = json.loads((ROOT / "data" / "events.json").read_text(encoding="utf-8"))
    events = data["events"] if isinstance(data, dict) else data
    by_url = {}
    for e in events:
        for u in listing_urls(e):
            by_url.setdefault(u, []).append(e)
    fetched_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with concurrent.futures.ThreadPoolExecutor(10) as pool:
        results = dict(zip(by_url, pool.map(fetch, by_url)))

    index = {"fetchedAt": fetched_at, "pages": {}}
    for url, res in results.items():
        listings = by_url[url]
        entry = {"listings": [e["id"] for e in listings], "status": res["status"]}
        if "error" in res:
            entry["error"] = res["error"]
        elif res["type"] not in ("text/html", "application/xhtml+xml", "text/plain"):
            entry["error"] = f"not a web page ({res['type']})"
        else:
            name = "pages/" + hashlib.sha1(url.encode()).hexdigest()[:12] + ".txt"
            text, chars, n_events = render(url, res, listings, fetched_at)
            (out / name).write_text(text, encoding="utf-8")
            entry.update(file=name, excerptChars=chars, structuredEvents=n_events)
            if res["finalUrl"] != url:
                entry["finalUrl"] = res["finalUrl"]
        index["pages"][url] = entry
    (out / "index.json").write_text(json.dumps(index, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "README.md").write_text(README, encoding="utf-8")
    saved = sum(1 for v in index["pages"].values() if "file" in v)
    print(f"saved {saved} of {len(index['pages'])} pages ({fetched_at})")


if __name__ == "__main__":
    main()
