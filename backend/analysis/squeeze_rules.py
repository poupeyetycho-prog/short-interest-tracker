"""Alert rules, calibrated on a 205-event / 72,893 ticker-day study (2020-2026).

Two findings from that study drive the design, and both are counter-intuitive:

1. Volume must NEVER be a required condition. 19% of real >=2x squeezes ignited
   on BELOW-average volume (GME 2021-02-22 fired at 0.3x and still ran 8.6x).
   Requiring volume >=3x alongside +10% price drops recall from 93.7% to 30.7%.
   Volume only ever RAISES a tier here.

2. Trigger on cumulative move vs the previous close, not on a single bar.
   On days that reached +10%, the average largest single 5-minute bar was only
   2.82%; a ">=5% in one 5-min bar" rule would miss 93% of them while still
   firing ~30x/day on a 50-stock list.

Noise control comes from the structural gate plus threshold height, not volume.
"""
from dataclasses import dataclass, field

from config import (
    ALERT_BUILDING_PCT, ALERT_CONFIRMED_PCT, ALERT_HEADSUP_PCT,
    ALERT_URGENT_PCT, ALERT_URGENT_RVOL, ALERT_WATCH_PCT, ALERT_WATCH_RVOL,
    GATE_MIN_DAYS_TO_COVER, GATE_MIN_SHORT_PCT_FLOAT,
)

# Tier order matters: the first match wins, strongest first.
TIERS = ["urgent", "heads_up", "watch"]

TIER_META = {
    "watch": {"emoji": "🔵", "label": "Watch", "push": False, "priority": "low"},
    "heads_up": {"emoji": "🔔", "label": "Heads-up", "push": True, "priority": "default"},
    "urgent": {"emoji": "🔴", "label": "Urgent", "push": True, "priority": "high"},
    "confirmed": {"emoji": "✅", "label": "Confirmed", "push": True, "priority": "high"},
    "continuation": {"emoji": "📈", "label": "Continuation", "push": True, "priority": "default"},
    "building": {"emoji": "🟡", "label": "Building", "push": True, "priority": "low"},
}

# Intraday alerts are explicitly NOT entry signals: 16.1% of even the successful
# events closed day 0 below the +10% crossing price.
UNCONFIRMED_NOTE = "UNCONFIRMED — not an entry signal"


@dataclass
class Signal:
    symbol: str
    tier: str
    pct_change: float
    rvol: float | None = None
    price: float | None = None
    prev_close: float | None = None
    note: str = ""
    extras: dict = field(default_factory=dict)


def passes_gate(short_pct_float: float | None, days_to_cover: float | None) -> bool:
    """The structural gate — the real noise filter. Only heavily-shorted, slow-to-cover
    names can alert at all. Values above 100% are split/stale-float artifacts."""
    if short_pct_float is None or days_to_cover is None:
        return False
    if short_pct_float > 100:
        return False
    return (short_pct_float >= GATE_MIN_SHORT_PCT_FLOAT
            and days_to_cover >= GATE_MIN_DAYS_TO_COVER)


def evaluate_intraday(symbol: str, price: float, prev_close: float,
                      rvol: float | None = None) -> Signal | None:
    """Cumulative move vs previous close, evaluated on every scan.

    `rvol` is cumulative volume vs the SAME-TIME-OF-DAY 20-day baseline — comparing
    a 10:05 volume against a full-day average would fire every single morning.
    """
    if not prev_close or prev_close <= 0 or price is None:
        return None
    pct = (price - prev_close) / prev_close * 100

    if pct >= ALERT_URGENT_PCT or (pct >= ALERT_HEADSUP_PCT and (rvol or 0) >= ALERT_URGENT_RVOL):
        tier = "urgent"
    elif pct >= ALERT_HEADSUP_PCT:
        tier = "heads_up"
    elif pct >= ALERT_WATCH_PCT and (rvol or 0) >= ALERT_WATCH_RVOL:
        tier = "watch"
    else:
        return None

    return Signal(symbol=symbol, tier=tier, pct_change=round(pct, 2), rvol=rvol,
                  price=price, prev_close=prev_close, note=UNCONFIRMED_NOTE)


def evaluate_close(symbol: str, close: float, prev_close: float) -> Signal | None:
    """Post-close confirmation — the actual quality signal.

    Entering at the next open still left ~95% of the median upside in the study,
    while avoiding the 16.1% of days that closed back below the intraday trigger.
    """
    if not prev_close or prev_close <= 0:
        return None
    pct = (close - prev_close) / prev_close * 100
    if pct < ALERT_CONFIRMED_PCT:
        return None
    return Signal(symbol=symbol, tier="confirmed", pct_change=round(pct, 2),
                  price=close, prev_close=prev_close,
                  note="Closed above the threshold — the higher-quality signal.")


def evaluate_building(symbol: str, closes: list[float], volumes: list[float],
                      avg_volume: float) -> Signal | None:
    """The multi-day 'simmer' that preceded SLS by ~7 days: repeated up-days on
    mildly elevated (not extreme) volume. Catches setups before they break out."""
    if len(closes) < 6 or avg_volume <= 0:
        return None
    window_c, window_v = closes[-6:], volumes[-6:]
    up_days = sum(
        1 for i in range(1, 6)
        if window_c[i] > window_c[i - 1] and 1.5 <= window_v[i] / avg_volume <= 2.5
    )
    cum = (window_c[-1] - window_c[0]) / window_c[0] * 100 if window_c[0] else 0
    if up_days >= 2 and cum >= ALERT_BUILDING_PCT:
        return Signal(symbol=symbol, tier="building", pct_change=round(cum, 2),
                      note=f"{up_days} up-days on elevated volume over 5 sessions.")
    return None


def evaluate_continuation(symbol: str, day_n: int, gain_since_trigger: float,
                          made_higher_high: bool) -> Signal | None:
    """Still climbing after an earlier trigger. 87% of real squeezes peaked on
    day 5 or later, so this is where the multi-day opportunity actually lives."""
    if day_n < 1 or not made_higher_high or gain_since_trigger <= 0:
        return None
    return Signal(symbol=symbol, tier="continuation", pct_change=round(gain_since_trigger, 2),
                  extras={"day_n": day_n},
                  note=f"Day {day_n} since trigger, still making higher highs.")


def format_message(sig: Signal, catalyst: str | None = None) -> tuple[str, str]:
    """(title, body) for the push. The catalyst is a LABEL, never a filter."""
    meta = TIER_META[sig.tier]
    title = f"{meta['emoji']} {sig.symbol} {sig.pct_change:+.1f}%"
    lines = [f"{meta['label']}"]
    if sig.price:
        lines.append(f"${sig.price:.2f} (prev close ${sig.prev_close:.2f})")
    if sig.rvol:
        lines.append(f"volume {sig.rvol:.1f}x normal")
    lines.append(f"📰 {catalyst}" if catalyst else "no news found")
    if sig.note:
        lines.append(sig.note)
    return title, "\n".join(lines)
