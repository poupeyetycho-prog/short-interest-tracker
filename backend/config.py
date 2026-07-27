"""Central configuration for the short-interest app backend."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")
DB_URL = f"sqlite:///{DB_PATH}"

# FINRA publishes bi-monthly consolidated short-interest files at this CDN.
# Pattern: shrt<YYYYMMDD>.csv where the date is the settlement date.
FINRA_CDN_BASE = "https://cdn.finra.org/equity/otcmarket/biweekly"

# marketClassCode values we treat as "exchange-listed" (NYSE + Nasdaq family).
# Excluded: OTC (over-the-counter), ARCA / BZX (ETF venues).
EXCHANGE_LISTED_CLASSES = {"NYSE", "NNM", "SC", "AMEX"}

# Human-readable exchange names.
EXCHANGE_NAMES = {
    "NYSE": "NYSE",
    "NNM": "Nasdaq",
    "SC": "Nasdaq",
    "AMEX": "NYSE American",
    "ARCA": "NYSE Arca",
    "BZX": "Cboe BZX",
    "OTC": "OTC",
}

# Enrichment (yfinance) throttling.
ENRICH_SLEEP_SECONDS = float(os.environ.get("ENRICH_SLEEP_SECONDS", "0.4"))
ENRICH_TTL_HOURS = 24  # re-fetch fundamentals older than this

# Candle cache TTL.
CANDLE_TTL_HOURS = 12

def _env(name: str, default: str = "") -> str:
    """Read an env var, treating an EMPTY value as unset.

    CI passes unset secrets through as empty strings (`FOO: ${{ secrets.FOO }}`
    with no such secret yields ""), and `os.environ.get(name, default)` returns
    that "" rather than the default because the key exists. That silently broke
    two things in Actions: the ntfy base URL became "" so every push URL lost its
    scheme, and the SEC User-Agent became "" so EDGAR returned 403.
    Also strips whitespace — `gh secret set` via a pipe can capture a newline.
    """
    return (os.environ.get(name) or default).strip()


# --- Phase 2: research sources -------------------------------------------------
# SEC requires a descriptive User-Agent naming a real contact, or it returns 403.
# Set SEC_USER_AGENT to "your-app your@email.com" — deliberately NOT hardcoded so
# a personal address never ends up in a public repo.
SEC_USER_AGENT = _env("SEC_USER_AGENT", "short-interest-tracker contact@example.com")
REDDIT_CLIENT_ID = _env("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = _env("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = _env("REDDIT_USER_AGENT", "short-interest-tracker/0.1")

# Automated X/Twitter reading requires the paid official API. Left disabled; the
# UI ships a compliant deep-link button instead of a scraper.
X_API_BEARER = os.environ.get("X_API_BEARER", "")

# --- Phase 2: synthesis --------------------------------------------------------
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _env("ANTHROPIC_MODEL", "claude-opus-5")
ANALYSIS_TTL_HOURS = 6

# --- Phase 2: alerts -----------------------------------------------------------
NTFY_TOPIC = _env("NTFY_TOPIC")
NTFY_SERVER = _env("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

# Structural gate — only these stocks can ever alert (the real noise filter).
GATE_MIN_SHORT_PCT_FLOAT = float(os.environ.get("GATE_MIN_SHORT_PCT_FLOAT", "15"))
GATE_MIN_DAYS_TO_COVER = float(os.environ.get("GATE_MIN_DAYS_TO_COVER", "3"))
WATCHLIST_MAX = int(os.environ.get("WATCHLIST_MAX", "50"))

# Thresholds derived from the 205-event / 72,893 ticker-day study (see plan A2-A4b).
# Cumulative move vs previous close; volume never gates, it only raises tier.
ALERT_WATCH_PCT = 5.0        # in-app only
ALERT_WATCH_RVOL = 1.5
ALERT_HEADSUP_PCT = 10.0     # primary push  (93.7% recall, ~5/day, ~10.4% precision)
ALERT_URGENT_PCT = 20.0      # high priority (47.8% recall, ~23.4% precision)
ALERT_URGENT_RVOL = 3.0
ALERT_CONFIRMED_PCT = 10.0   # post-close confirmation — the quality signal
ALERT_BUILDING_PCT = 15.0    # multi-day simmer (SLS-style precursor)

DISCLAIMER = (
    "Short-interest figures are official FINRA data, published twice a month with a "
    "reporting lag of roughly two weeks. The short % of float updates only on each "
    "bi-monthly settlement date; prices, volume and float update daily. "
    "This tool is for informational purposes only and is not investment advice."
)
