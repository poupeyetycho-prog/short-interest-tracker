"""SEC fails-to-deliver data — settlement pressure, a genuine squeeze ingredient.

Published as semi-monthly pipe-delimited files inside ZIPs. Sustained FTDs mean
shares are being sold but not delivered, which is the mechanical stress a squeeze
feeds on. Requires the SEC User-Agent like every sec.gov endpoint.
"""
import io
import zipfile
from datetime import date

import requests

from config import SEC_USER_AGENT

_BASE = "https://www.sec.gov/files/data/fails-deliver-data"


def _urls_for(year: int, month: int) -> list[str]:
    ym = f"{year}{month:02d}"
    return [f"{_BASE}/cnsfails{ym}a.zip", f"{_BASE}/cnsfails{ym}b.zip"]


def recent(symbol: str, months: int = 3) -> dict:
    """Fails-to-deliver history for one ticker over the last few months."""
    sym = symbol.upper()
    headers = {"User-Agent": SEC_USER_AGENT}
    rows = []
    today = date.today()
    for back in range(months):
        y, m = today.year, today.month - back
        while m <= 0:
            m += 12
            y -= 1
        for url in _urls_for(y, m):
            try:
                r = requests.get(url, headers=headers, timeout=90)
                if r.status_code != 200:
                    continue
                zf = zipfile.ZipFile(io.BytesIO(r.content))
            except Exception:
                continue
            for name in zf.namelist():
                try:
                    text = zf.read(name).decode("latin-1", errors="replace")
                except Exception:
                    continue
                for line in text.splitlines()[1:]:
                    parts = line.split("|")
                    if len(parts) < 6 or parts[2].strip().upper() != sym:
                        continue
                    try:
                        rows.append({
                            "date": parts[0].strip(),
                            "quantity": int(float(parts[3] or 0)),
                            "price": float(parts[5] or 0) if parts[5].strip() else None,
                        })
                    except ValueError:
                        continue
    rows.sort(key=lambda r: r["date"])
    if not rows:
        return {"available": False, "days": 0, "series": []}
    qtys = [r["quantity"] for r in rows]
    return {
        "available": True,
        "days": len(rows),
        "max_fails": max(qtys),
        "avg_fails": int(sum(qtys) / len(qtys)),
        "latest": rows[-1],
        "series": rows[-40:],
        "note": "Sustained fails-to-deliver indicate settlement pressure.",
    }


if __name__ == "__main__":
    import sys
    print(recent(sys.argv[1] if len(sys.argv) > 1 else "HTZ", months=2))
