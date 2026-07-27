"""Push delivery via ntfy.sh — free, no account, works to a phone."""
import requests

from analysis.squeeze_rules import TIER_META, Signal, format_message
from config import NTFY_SERVER, NTFY_TOPIC


def enabled() -> bool:
    return bool(NTFY_TOPIC)


def describe_target() -> str:
    """A fingerprint of the push target for logs — never the topic itself, since
    on the public ntfy.sh server the topic name is the only access control."""
    if not NTFY_TOPIC:
        return "ntfy: DISABLED (NTFY_TOPIC unset)"
    clean = all(c.isalnum() or c in "-_" for c in NTFY_TOPIC)
    return (f"ntfy: server={NTFY_SERVER} topic_len={len(NTFY_TOPIC)} "
            f"charset_ok={clean}")


def push(sig: Signal, catalyst: str | None = None, click_url: str | None = None) -> bool:
    """Send one alert. Returns True when delivered."""
    if not enabled():
        return False
    meta = TIER_META[sig.tier]
    if not meta["push"]:
        return False  # 'watch' tier is in-app only by design

    title, body = format_message(sig, catalyst)
    headers = {
        "Title": _header_safe(title),
        "Priority": meta["priority"],
        # ntfy renders these shortcodes as emoji. Raw emoji here would raise
        # UnicodeEncodeError, since HTTP headers are latin-1.
        "Tags": meta["tag"],
    }
    if click_url:
        headers["Click"] = click_url
    url = f"{NTFY_SERVER}/{NTFY_TOPIC}"
    try:
        r = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=20)
        if r.status_code >= 300:
            # Log loudly — a silently swallowed failure here once hid an empty
            # NTFY_SERVER (so the URL had no scheme) for an entire session.
            print(f"[notify] push failed {r.status_code} for {sig.symbol}: {r.text[:120]}")
            return False
        return True
    except Exception as e:
        # Deliberately broad: a UnicodeEncodeError from an unencodable header is
        # NOT a RequestException, and once crashed an entire scan mid-run. One
        # bad alert must never take down the other 49 tickers.
        print(f"[notify] push error for {sig.symbol}: {type(e).__name__}: {str(e)[:160]}")
        return False


def _header_safe(value: str) -> str:
    """HTTP headers must be latin-1; drop anything that isn't."""
    return value.encode("latin-1", errors="ignore").decode("latin-1").strip() or "Alert"


def push_digest(title: str, lines: list[str]) -> bool:
    """One daily summary push (continuation / building tiers)."""
    if not enabled() or not lines:
        return False
    try:
        r = requests.post(f"{NTFY_SERVER}/{NTFY_TOPIC}",
                          data="\n".join(lines).encode("utf-8"),
                          headers={"Title": title, "Priority": "low", "Tags": "chart"},
                          timeout=20)
        return r.status_code < 300
    except requests.RequestException:
        return False
