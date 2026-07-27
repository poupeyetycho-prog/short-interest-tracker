"""Attach a catalyst LABEL to an alert — deliberately never a filter.

Recall stays at 93.7% because real squeezes driven by a large buyer, or by the
squeeze feeding itself, have no published catalyst and must not be suppressed.
The precision benefit is delivered where it matters: triaging the notification.

    HTZ +14% 📰 Q3 earnings beat      vs      HTZ +14% — no news found
"""
from datetime import date, timedelta

from sources import edgar, news

_HOT_FORMS = {"8-K", "424B5", "S-1", "S-3", "NT 10-K", "NT 10-Q"}


def find(symbol: str, hours: int = 48) -> str | None:
    """Best-effort catalyst label. Returns None when nothing is found — which is
    a perfectly valid, informative outcome, not a failure."""
    # A very recent material filing is the strongest signal available.
    try:
        since = (date.today() - timedelta(days=3)).isoformat()
        for f in edgar.filings(symbol, since=since, forms=_HOT_FORMS, limit=5):
            meaning = f.get("meaning") or f["form"]
            return f"{f['form']} filed {f['filed']} — {meaning}"
    except Exception:
        pass

    try:
        head = news.find_catalyst(symbol, hours=hours)
        if head:
            return head["title"][:140]
    except Exception:
        pass
    return None
