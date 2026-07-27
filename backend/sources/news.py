"""Free per-ticker news via RSS, plus short-seller report detection.

No API keys: Yahoo Finance and Google News both expose per-symbol RSS feeds.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) short-interest-app"

_FEEDS = [
    ("Yahoo Finance", "https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US"),
    ("Google News", "https://news.google.com/rss/search?q={sym}+stock&hl=en-US&gl=US&ceid=US:en"),
]

# Activist short sellers — a published report is very often the entire thesis.
SHORT_SELLERS = [
    "hindenburg", "muddy waters", "citron", "kerrisdale", "culper",
    "scorpion capital", "night market", "grizzly research", "wolfpack",
    "spruce point", "bonitas", "j capital", "blue orca", "fuzzy panda",
]

BEAR_KEYWORDS = [
    "short seller", "short report", "fraud", "investigation", "sec probe",
    "class action", "delisting", "going concern", "bankruptcy", "restatement",
    "dilution", "offering", "downgrade", "guidance cut", "misses", "recall",
    "subpoena", "resigns", "auditor",
]

BULL_KEYWORDS = [
    "beats", "upgrade", "approval", "fda", "contract", "partnership",
    "record revenue", "raises guidance", "acquisition", "buyback", "breakthrough",
]


def _parse_feed(name: str, url: str, limit: int) -> list[dict]:
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=30)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
    except Exception:
        return []
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        when = None
        try:
            when = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat()
        except Exception:
            pass
        items.append({"source": name, "title": title, "url": link, "published": when})
        if len(items) >= limit:
            break
    return items


def headlines(symbol: str, limit: int = 15) -> list[dict]:
    out = []
    for name, tmpl in _FEEDS:
        out.extend(_parse_feed(name, tmpl.format(sym=symbol.upper()), limit))
    # newest first, undated last
    out.sort(key=lambda i: i.get("published") or "", reverse=True)
    return out[: limit * 2]


def classify(items: list[dict]) -> dict:
    """Tag headlines with bear/bull keywords and flag short-seller reports."""
    text = " ".join(i["title"].lower() for i in items)
    firms = sorted({f for f in SHORT_SELLERS if f in text})
    bear = sorted({k for k in BEAR_KEYWORDS if k in text})
    bull = sorted({k for k in BULL_KEYWORDS if k in text})
    return {
        "short_seller_reports": firms,
        "bear_signals": bear,
        "bull_signals": bull,
        "has_short_report": bool(firms),
    }


def find_catalyst(symbol: str, hours: int = 48) -> dict | None:
    """Newest headline within `hours` — used to LABEL an alert, never to gate it."""
    cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
    for i in headlines(symbol, limit=10):
        if not i.get("published"):
            continue
        try:
            ts = datetime.fromisoformat(i["published"]).timestamp()
        except ValueError:
            continue
        if ts >= cutoff:
            return {"title": i["title"], "url": i["url"], "source": i["source"]}
    return None


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "HTZ"
    hs = headlines(sym)
    for h in hs[:8]:
        print(" ", (h.get("published") or "")[:10], h["title"][:90])
    print(classify(hs))
