"""Retail sentiment: StockTwits (free, no auth) + Reddit (free, non-commercial).

StockTwits is the more useful of the two here because each message can carry an
explicit Bullish/Bearish tag (~30-50% of messages are labelled).
"""
import time
from datetime import datetime, timezone

import requests

from config import REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) short-interest-app"
_ST = "https://api.stocktwits.com/api/2/streams/symbol/{sym}.json"
_SUBS = ["wallstreetbets", "shortsqueeze", "stocks", "investing", "pennystocks"]

_reddit_token = {"value": None, "expires": 0}


def stocktwits(symbol: str) -> dict:
    """Message volume and bullish/bearish split for a ticker."""
    try:
        r = requests.get(_ST.format(sym=symbol.upper()),
                         headers={"User-Agent": _UA}, timeout=30)
        if r.status_code != 200:
            return {"available": False, "reason": f"HTTP {r.status_code}"}
        msgs = r.json().get("messages") or []
    except Exception as e:
        return {"available": False, "reason": str(e)[:120]}

    bull = bear = 0
    recent = []
    for m in msgs:
        sent = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
        if sent == "Bullish":
            bull += 1
        elif sent == "Bearish":
            bear += 1
        if len(recent) < 8:
            recent.append({
                "body": (m.get("body") or "")[:220],
                "created": m.get("created_at"),
                "sentiment": sent,
            })
    labelled = bull + bear
    return {
        "available": True,
        "messages": len(msgs),
        "bullish": bull,
        "bearish": bear,
        "bull_ratio": round(bull / labelled, 3) if labelled else None,
        "labelled_share": round(labelled / len(msgs), 3) if msgs else None,
        "recent": recent,
    }


def _reddit_auth() -> str | None:
    """Client-credentials token; returns None when the app isn't configured."""
    if not (REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET):
        return None
    if _reddit_token["value"] and time.time() < _reddit_token["expires"]:
        return _reddit_token["value"]
    try:
        r = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": REDDIT_USER_AGENT},
            timeout=30,
        )
        r.raise_for_status()
        j = r.json()
        _reddit_token["value"] = j["access_token"]
        _reddit_token["expires"] = time.time() + j.get("expires_in", 3600) - 60
        return _reddit_token["value"]
    except Exception:
        return None


def reddit(symbol: str, limit: int = 25) -> dict:
    """Recent Reddit posts mentioning the ticker across finance subs.

    Degrades gracefully: without app credentials it reports unavailable rather
    than scraping, since Reddit's free tier requires a registered app.
    """
    token = _reddit_auth()
    if not token:
        return {
            "available": False,
            "reason": "Reddit app credentials not configured "
                      "(set REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET).",
        }
    q = f"{symbol.upper()}"
    posts = []
    try:
        for sub in _SUBS:
            r = requests.get(
                f"https://oauth.reddit.com/r/{sub}/search",
                params={"q": q, "restrict_sr": 1, "sort": "new", "limit": 10, "t": "month"},
                headers={"Authorization": f"Bearer {token}", "User-Agent": REDDIT_USER_AGENT},
                timeout=30,
            )
            if r.status_code != 200:
                continue
            for c in (r.json().get("data") or {}).get("children") or []:
                d = c.get("data") or {}
                posts.append({
                    "subreddit": sub,
                    "title": (d.get("title") or "")[:200],
                    "score": d.get("score"),
                    "comments": d.get("num_comments"),
                    "created": datetime.fromtimestamp(
                        d.get("created_utc") or 0, tz=timezone.utc
                    ).isoformat(),
                    "url": "https://reddit.com" + (d.get("permalink") or ""),
                })
    except Exception as e:
        return {"available": False, "reason": str(e)[:120]}

    posts.sort(key=lambda p: p["created"], reverse=True)
    return {
        "available": True,
        "post_count": len(posts),
        "total_score": sum(p["score"] or 0 for p in posts),
        "posts": posts[:limit],
    }


def x_search_url(symbol: str) -> str:
    """Compliant deep link — the user reads X themselves in their own browser.

    Automated reading of X requires the paid official API; scraping violates its
    ToS, so no scraper exists in this codebase.
    """
    return f"https://x.com/search?q=%24{symbol.upper()}&f=live"


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "GME"
    st = stocktwits(sym)
    print("StockTwits:", {k: v for k, v in st.items() if k != "recent"})
    print("Reddit:", reddit(sym).get("available"), reddit(sym).get("reason", ""))
    print("X link:", x_search_url(sym))
