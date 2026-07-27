"""JSON state for ephemeral runners (GitHub Actions).

Actions runners have no persistent disk and the SQLite DB is rebuilt from scratch
each run, so the two things that MUST survive between runs live in small JSON
files committed to a dedicated `state` branch:

    watchlist.json  - the structural-gate survivors (refreshed once daily)
    alerts.json     - per-ticker/per-tier cooldown, so a move alerts once a day

Written only when something actually changes, which keeps the commit history
from growing by 288 commits a day.
"""
import json
import os
from datetime import date, datetime, timedelta

WATCHLIST_FILE = "watchlist.json"
ALERTS_FILE = "alerts.json"


def _path(state_dir: str, name: str) -> str:
    return os.path.join(state_dir, name)


def load_watchlist(state_dir: str) -> list[dict]:
    try:
        with open(_path(state_dir, WATCHLIST_FILE), encoding="utf-8") as f:
            data = json.load(f)
        return data.get("symbols", [])
    except (OSError, json.JSONDecodeError):
        return []


def watchlist_age_days(state_dir: str) -> float:
    try:
        with open(_path(state_dir, WATCHLIST_FILE), encoding="utf-8") as f:
            built = json.load(f).get("built_at")
        return (datetime.utcnow() - datetime.fromisoformat(built)).total_seconds() / 86400
    except Exception:
        return 999.0


def save_watchlist(state_dir: str, symbols: list[dict]) -> None:
    os.makedirs(state_dir, exist_ok=True)
    with open(_path(state_dir, WATCHLIST_FILE), "w", encoding="utf-8") as f:
        json.dump({"built_at": datetime.utcnow().isoformat(), "symbols": symbols}, f, indent=1)


def load_alerts(state_dir: str) -> dict:
    try:
        with open(_path(state_dir, ALERTS_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_alerts(state_dir: str, alerts: dict) -> None:
    os.makedirs(state_dir, exist_ok=True)
    # Drop anything older than 5 days so the file stays small.
    cutoff = (date.today() - timedelta(days=5)).isoformat()
    pruned = {k: v for k, v in alerts.items() if v.get("date", "") >= cutoff}
    with open(_path(state_dir, ALERTS_FILE), "w", encoding="utf-8") as f:
        json.dump(pruned, f, indent=1, sort_keys=True)


def cooldown_key(symbol: str, tier: str, trade_date: str) -> str:
    return f"{symbol}|{tier}|{trade_date}"
