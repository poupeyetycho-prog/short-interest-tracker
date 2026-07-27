"""Replay the alert rules over history and measure recall / precision.

This is the gate: no push notifications are enabled until these numbers
reproduce the study the thresholds were derived from.

Expected (from the planning study, 2020-2026):
  * >=2x squeeze events detected, split-adjusted and liquidity-filtered
  * recall at the +10% tier  ~= 93.7%
  * precision at the +10% tier ~= 10.4%  (i.e. ~9 of 10 alerts are NOT 2x moves)
  * must fire on SLS 2025-12-29 and HTZ 2025-11-04

Reverse splits are filtered out explicitly — without that the raw scan produces
nonsense (BBIG "+1,566%", TTOO "+900%") that badly skews every threshold.
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from curl_cffi import requests as creq

from analysis.squeeze_rules import evaluate_intraday

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"

UNIVERSE = [
    "GME", "AMC", "KOSS", "CLOV", "ATER", "PROG", "PHUN", "GNS", "HKD", "SNDL",
    "NVAX", "SAVA", "BYND", "UPST", "CVNA", "DJT", "NKLA", "RIDE", "WKHS", "SPCE",
    "HTZ", "SLS", "ANVS", "LCID", "SOUN", "MARA", "CLSK", "RIOT", "BBAI", "QUBT",
    "IONQ", "OPEN", "CHPT", "PLUG", "FCEL", "BLNK", "RUN", "ASTS", "LUNR", "RKLB",
    "SMCI", "TLRY", "PTON", "CAR", "AI", "PATH", "RXRX", "NNE", "OKLO", "SMR",
    "APLD", "CORZ", "WULF", "HIVE", "BTDR", "EOSE", "INDI", "TEM", "HIMS", "RCAT",
    "ONDS", "TNGX", "VNET", "W", "BBBY",
]

MUST_FIRE = [("SLS", "2025-12-29"), ("HTZ", "2025-11-04")]


def _fetch(session, sym):
    r = session.get(_CHART.format(sym=sym),
                    params={"range": "10y", "interval": "1d", "events": "split"})
    if r.status_code != 200:
        return None, []
    res = (r.json().get("chart") or {}).get("result") or []
    if not res:
        return None, []
    res = res[0]
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    splits = []
    for v in ((res.get("events") or {}).get("splits") or {}).values():
        splits.append(datetime.fromtimestamp(v["date"], tz=timezone.utc).date())
    rows = []
    for i, t in enumerate(ts):
        c, h, vol = _at(q.get("close"), i), _at(q.get("high"), i), _at(q.get("volume"), i)
        if c is None or h is None or vol is None:
            continue
        rows.append({
            "d": datetime.fromtimestamp(t, tz=timezone.utc).date(),
            "c": float(c), "h": float(h), "v": float(vol),
        })
    return splits, rows


def _at(arr, i):
    if not arr or i >= len(arr):
        return None
    v = arr[i]
    return None if v is None or (isinstance(v, float) and v != v) else v


def run(verbose: bool = True) -> dict:
    session = creq.Session(impersonate="chrome", timeout=60)
    events, fired_on_events = [], []
    alerts = hits = ticker_days = 0
    fired_dates: dict[str, set] = {}

    for sym in UNIVERSE:
        try:
            splits, rows = _fetch(session, sym)
        except Exception:
            continue
        if len(rows) < 60:
            continue

        # `skip_until` implements the same de-duplication the planning study used:
        # once an event is found, jump past its 15-day window so a single squeeze
        # counts once (as its IGNITION day) rather than once per day of the run.
        skip_until = -1

        for i in range(25, len(rows) - 16):
            r = rows[i]
            if r["d"].isoformat() < "2020-01-01":
                continue
            base = rows[i - 1]["c"]
            if base < 1.0:                       # no sub-$1 penny names
                continue
            prior = rows[i - 20:i]
            avg_v = sum(p["v"] for p in prior) / 20
            if avg_v * base < 3_000_000:         # must trade >=$3M/day pre-event
                continue

            ticker_days += 1
            fwd = rows[i:i + 16]
            peak = max(p["h"] for p in fwd)
            mult = peak / base
            volx = r["v"] / avg_v if avg_v else 0
            day_chg = (r["c"] - base) / base * 100
            near_split = any(abs((s - r["d"]).days) <= 12 for s in splits)

            # Two different questions need two different denominators:
            #
            #   RECALL    — "when a squeeze IGNITES, does the rule alert?"
            #               measured against deduped ignition days.
            #   PRECISION — "when the rule alerts, did a 2x follow?"
            #               measured against every alert, using plain forward
            #               2x on that day (no ignition signature, no dedup).
            is_2x_forward = 2.0 <= mult and not near_split
            is_event = (
                is_2x_forward
                and mult <= 15
                and (day_chg >= 8 or volx >= 2.5)
                and i > skip_until
            )

            # The rule under test, evaluated on the day's high (what a live
            # intraday scanner would have seen at the moment of the crossing).
            sig = evaluate_intraday(sym, r["h"], base, rvol=volx)
            fired = sig is not None and sig.tier in ("heads_up", "urgent")

            if fired:
                alerts += 1
                fired_dates.setdefault(sym, set()).add(r["d"].isoformat())
                if is_2x_forward:
                    hits += 1
            if is_event:
                events.append((sym, r["d"].isoformat()))
                fired_on_events.append(fired)
                skip_until = i + 20

    n_events = len(events)
    recall = (sum(fired_on_events) / n_events * 100) if n_events else 0
    precision = (hits / alerts * 100) if alerts else 0
    years = 6.5
    per_day_50 = alerts / years / 252 / len(UNIVERSE) * 50

    checks = []
    for sym, day in MUST_FIRE:
        checks.append((sym, day, day in fired_dates.get(sym, set())))

    result = {
        "ticker_days": ticker_days,
        "events": n_events,
        "alerts": alerts,
        "recall_pct": round(recall, 1),
        "precision_pct": round(precision, 1),
        "alerts_per_day_50_stock_list": round(per_day_50, 1),
        "must_fire": checks,
        "passed": (
            85 <= recall <= 100
            and 5 <= precision <= 30
            and all(ok for _, _, ok in checks)
        ),
    }

    if verbose:
        print(f"Ticker-days evaluated : {ticker_days:,}")
        print(f">=2x squeeze events   : {n_events}")
        print(f"Alerts fired          : {alerts:,}")
        print(f"RECALL   (of real 2x) : {result['recall_pct']}%   (study: 93.7%)")
        print(f"PRECISION             : {result['precision_pct']}%   (study: 10.4%)")
        print(f"Alerts/day (50 names) : {result['alerts_per_day_50_stock_list']}   (study: 5.2)")
        print("Known-squeeze checks:")
        for sym, day, ok in checks:
            print(f"   {'PASS' if ok else 'FAIL'}  {sym} {day}")
        print(f"\nBACKTEST {'PASSED' if result['passed'] else 'FAILED'}")
    return result


if __name__ == "__main__":
    r = run()
    sys.exit(0 if r["passed"] else 1)
