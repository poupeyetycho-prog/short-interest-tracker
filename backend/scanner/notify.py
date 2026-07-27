"""Push delivery via ntfy.sh — free, no account, works to a phone."""
import requests

from analysis.squeeze_rules import TIER_META, Signal, format_message
from config import NTFY_SERVER, NTFY_TOPIC


def enabled() -> bool:
    return bool(NTFY_TOPIC)


def push(sig: Signal, catalyst: str | None = None, click_url: str | None = None) -> bool:
    """Send one alert. Returns True when delivered."""
    if not enabled():
        return False
    meta = TIER_META[sig.tier]
    if not meta["push"]:
        return False  # 'watch' tier is in-app only by design

    title, body = format_message(sig, catalyst)
    headers = {
        "Title": title,
        "Priority": meta["priority"],
        "Tags": "chart_with_upwards_trend" if sig.pct_change >= 0 else "chart",
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
    except requests.RequestException as e:
        print(f"[notify] push error for {sig.symbol}: {type(e).__name__}: {str(e)[:160]}")
        return False


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
