"""Market-data client for fundamentals and candles.

Uses Yahoo Finance's public JSON endpoints directly via a browser-impersonating
curl_cffi session. yfinance's bundled session gets 429-throttled on the
`quoteSummary` endpoint; fetching a single crumb+cookie and reusing it across
symbols (with throttling) is far more reliable.
"""
import threading
import time

from curl_cffi import requests as creq
from tenacity import retry, stop_after_attempt, wait_exponential

_QUOTE_HOST = "https://query2.finance.yahoo.com"
_CHART_HOST = "https://query1.finance.yahoo.com"

# Intervals Yahoo serves intraday (bar times are unix seconds, not calendar days).
INTRADAY_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "1h"}

# Canonical range tokens -> days of history. Legacy short month aliases are kept
# because the Phase 1 frontend sent "1m"/"3m"/"6m" meaning *months*.
_RANGE_DAYS = {
    "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
    "1y": 365, "2y": 730, "5y": 1825, "max": 36500,
}
_RANGE_ALIASES = {"1m": "1mo", "3m": "3mo", "6m": "6mo"}

# Hard limits Yahoo enforces per interval (verified live during planning):
# 1m -> 7d, 2m/5m/15m/30m -> 60d, 1h -> 730d, 1d -> years.
_INTERVAL_MAX_DAYS = {
    "1m": 7, "2m": 60, "5m": 60, "15m": 60, "30m": 60,
    "60m": 730, "1h": 730, "1d": 36500, "1wk": 36500, "1mo": 36500,
}


def resolve_range(range_: str, interval: str) -> str:
    """Clamp a requested range to the largest one legal for the interval.

    Asking for 1m candles over 1y returns an *empty* chart from Yahoo rather than
    an error, so clamping (1m+1y -> 1m+7d) is what keeps the UI from silently
    showing nothing.
    """
    token = _RANGE_ALIASES.get(range_, range_)
    if token not in _RANGE_DAYS:
        token = "1y"
    wanted = _RANGE_DAYS[token]
    allowed = _INTERVAL_MAX_DAYS.get(interval, 36500)
    if wanted <= allowed:
        return token
    # pick the largest canonical range that fits
    best = min(_RANGE_DAYS, key=lambda k: abs(_RANGE_DAYS[k] - allowed))
    for name, days in sorted(_RANGE_DAYS.items(), key=lambda kv: kv[1]):
        if days <= allowed:
            best = name
    return best


class _YahooClient:
    """Holds a curl_cffi session + a Yahoo crumb, refreshing the crumb on demand."""

    def __init__(self):
        self._lock = threading.Lock()
        self._session = None
        self._crumb = None

    def _ensure(self, force=False):
        with self._lock:
            if self._session is None or force:
                self._session = creq.Session(impersonate="chrome", timeout=30)
                # Seed cookies, then fetch a crumb tied to those cookies.
                try:
                    self._session.get("https://finance.yahoo.com")
                except Exception:
                    pass
                r = self._session.get(f"{_QUOTE_HOST}/v1/test/getcrumb")
                self._crumb = r.text.strip()
                if not self._crumb or len(self._crumb) > 40:
                    raise RuntimeError("Failed to obtain Yahoo crumb")
            return self._session, self._crumb

    def quote_summary(self, symbol: str, modules: str) -> dict:
        session, crumb = self._ensure()
        url = f"{_QUOTE_HOST}/v10/finance/quoteSummary/{symbol}"
        params = {"modules": modules, "crumb": crumb}
        r = session.get(url, params=params)
        if r.status_code in (401, 403) or (r.status_code == 429 and "crumb" in r.text.lower()):
            # Stale crumb -> refresh once and retry.
            session, crumb = self._ensure(force=True)
            params["crumb"] = crumb
            r = session.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        result = (data.get("quoteSummary") or {}).get("result") or []
        return result[0] if result else {}

    def chart(self, symbol: str, range_yf: str, interval: str) -> dict:
        session, _ = self._ensure()
        url = f"{_CHART_HOST}/v8/finance/chart/{symbol}"
        params = {"range": range_yf, "interval": interval, "includePrePost": "false"}
        r = session.get(url, params=params)
        r.raise_for_status()
        result = (r.json().get("chart") or {}).get("result") or []
        return result[0] if result else {}


_client = _YahooClient()


def _raw(node, key):
    """Yahoo wraps numbers as {'raw': x, 'fmt': ...}; unwrap safely."""
    v = (node or {}).get(key)
    if isinstance(v, dict):
        v = v.get("raw")
    return v


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.6, max=8), reraise=True)
def get_fundamentals(symbol: str) -> dict:
    """Return float shares, shares outstanding, market cap, last price and volume.
    Missing values come back as None (common for illiquid names)."""
    node = _client.quote_summary(symbol, "defaultKeyStatistics,price,summaryDetail")
    ks = node.get("defaultKeyStatistics", {})
    price = node.get("price", {})
    detail = node.get("summaryDetail", {})

    last_close = _raw(price, "regularMarketPrice") or _raw(detail, "previousClose")
    last_volume = _raw(price, "regularMarketVolume") or _raw(detail, "volume") or _raw(detail, "averageVolume")
    market_cap = _raw(price, "marketCap") or _raw(detail, "marketCap")
    float_shares = _raw(ks, "floatShares")
    shares_out = _raw(ks, "sharesOutstanding") or _raw(price, "sharesOutstanding")

    dollar_volume = float(last_close) * float(last_volume) if (last_close and last_volume) else None

    return {
        "float_shares": _as_int(float_shares),
        "shares_outstanding": _as_int(shares_out),
        "market_cap": _as_float(market_cap),
        "last_close": _as_float(last_close),
        "last_volume": _as_int(last_volume),
        "dollar_volume": _as_float(dollar_volume),
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.6, max=8), reraise=True)
def get_candles(symbol: str, range_: str = "1y", interval: str = "1d") -> list[dict]:
    """Return [{time, open, high, low, close, volume}].

    `time` is 'YYYY-MM-DD' for daily+ bars and a unix timestamp (seconds) for
    intraday bars — the two forms lightweight-charts expects.
    """
    from datetime import datetime, timezone

    yf_range = resolve_range(range_, interval)
    result = _client.chart(symbol, yf_range, interval)
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens, highs = quote.get("open") or [], quote.get("high") or []
    lows, closes = quote.get("low") or [], quote.get("close") or []
    volumes = quote.get("volume") or []
    intraday = interval in INTRADAY_INTERVALS

    candles = []
    for i, ts in enumerate(timestamps):
        o, h, l, c = _at(opens, i), _at(highs, i), _at(lows, i), _at(closes, i)
        if None in (o, h, l, c):
            continue
        when = int(ts) if intraday else datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        candles.append({
            "time": when,
            "open": round(float(o), 4),
            "high": round(float(h), 4),
            "low": round(float(l), 4),
            "close": round(float(c), 4),
            "volume": _as_int(_at(volumes, i)) or 0,
        })
    return candles


def get_quote(symbol: str) -> dict:
    """Light-weight live quote for the scanner: last price, previous close, volume.

    Uses the chart endpoint's `meta` block (no crumb required), which is far
    cheaper and more reliable than quoteSummary for high-frequency polling.
    """
    result = _client.chart(symbol, "1d", "5m")
    meta = result.get("meta") or {}
    return {
        "symbol": symbol,
        "price": _as_float(meta.get("regularMarketPrice")),
        "prev_close": _as_float(meta.get("chartPreviousClose") or meta.get("previousClose")),
        "volume": _as_int(meta.get("regularMarketVolume")),
    }


def _at(arr, i):
    v = arr[i] if i < len(arr) else None
    return None if (v is None or (isinstance(v, float) and v != v)) else v


def _as_int(v):
    try:
        if v is None or (isinstance(v, float) and v != v):
            return None
        return int(v)
    except (ValueError, TypeError):
        return None


def _as_float(v):
    try:
        if v is None or (isinstance(v, float) and v != v):
            return None
        return float(v)
    except (ValueError, TypeError):
        return None
