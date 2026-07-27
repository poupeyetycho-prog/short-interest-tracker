"""SEC EDGAR filings — the highest-signal evidence for a short thesis.

Free and keyless, but the SEC returns 403 (and may block the IP briefly) unless a
descriptive User-Agent naming a real contact is sent on every request.

Form types that matter here:
    S-1 / S-3 / 424B*      shelf offerings & ATMs  -> dilution, a top short thesis
    8-K                    material events
    10-K / 10-Q            risk factors, cash burn, covenants
    NT 10-K / NT 10-Q      late filing -> distress signal
    SC 13D / SC 13G        activist / large stakes
    4                      insider buying & selling
"""
import threading
from datetime import date

import requests

from config import SEC_USER_AGENT

_SUB = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_TICKERS = "https://www.sec.gov/files/company_tickers.json"
_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"

THESIS_FORMS = {
    "S-1": "dilution", "S-3": "dilution", "424B5": "dilution", "424B3": "dilution",
    "424B4": "dilution", "8-K": "material event", "10-K": "annual report",
    "10-Q": "quarterly report", "NT 10-K": "LATE FILING (distress)",
    "NT 10-Q": "LATE FILING (distress)", "SC 13D": "activist stake",
    "SC 13G": "large stake", "4": "insider transaction",
}

_lock = threading.Lock()
_cik_map: dict[str, int] | None = None


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"})
    return s


def _load_cik_map():
    global _cik_map
    with _lock:
        if _cik_map is not None:
            return _cik_map
        try:
            r = _session().get(_TICKERS, timeout=60)
            r.raise_for_status()
            _cik_map = {
                v["ticker"].upper(): int(v["cik_str"]) for v in r.json().values()
            }
        except Exception:
            _cik_map = {}
        return _cik_map


def cik_for(symbol: str) -> int | None:
    return _load_cik_map().get(symbol.upper())


def filings(symbol: str, since: str | None = None, until: str | None = None,
            forms: set[str] | None = None, limit: int = 40) -> list[dict]:
    """Recent filings for a ticker, newest first, optionally windowed by date."""
    cik = cik_for(symbol)
    if not cik:
        return []
    try:
        r = _session().get(_SUB.format(cik=cik), timeout=60)
        r.raise_for_status()
        recent = (r.json().get("filings") or {}).get("recent") or {}
    except Exception:
        return []

    out = []
    forms_list = recent.get("form") or []
    for i, form in enumerate(forms_list):
        fdate = (recent.get("filingDate") or [None] * len(forms_list))[i]
        if not fdate:
            continue
        if since and fdate < since:
            continue
        if until and fdate > until:
            continue
        if forms and form not in forms:
            continue
        accession = (recent.get("accessionNumber") or [""] * len(forms_list))[i]
        doc = (recent.get("primaryDocument") or [""] * len(forms_list))[i]
        acc_plain = accession.replace("-", "")
        out.append({
            "form": form,
            "filed": fdate,
            "meaning": THESIS_FORMS.get(form),
            "description": (recent.get("primaryDocDescription") or [""] * len(forms_list))[i],
            "url": f"{_ARCHIVE}/{cik}/{acc_plain}/{doc}" if doc else
                   f"{_ARCHIVE}/{cik}/{acc_plain}",
        })
        if len(out) >= limit:
            break
    return out


def thesis_filings(symbol: str, since: str | None = None, limit: int = 25) -> list[dict]:
    """Only the filings that actually inform a short thesis."""
    return filings(symbol, since=since, forms=set(THESIS_FORMS), limit=limit)


def dilution_signals(symbol: str, since: str | None = None) -> dict:
    """Count offering-related filings — the clearest quantifiable bear signal."""
    f = filings(symbol, since=since, forms={"S-1", "S-3", "424B5", "424B3", "424B4"}, limit=50)
    late = filings(symbol, since=since, forms={"NT 10-K", "NT 10-Q"}, limit=10)
    return {
        "offering_filings": len(f),
        "most_recent": f[0] if f else None,
        "late_filings": len(late),
        "items": f[:10],
    }


def filings_in_window(symbol: str, start: str, end: str) -> list[dict]:
    """Filings inside a short-interest inflection window — the causal link."""
    return filings(symbol, since=start, until=end, forms=set(THESIS_FORMS), limit=25)


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "HTZ"
    print("CIK:", cik_for(sym))
    for f in thesis_filings(sym, since=str(date.today().replace(year=date.today().year - 1)))[:10]:
        print(" ", f["filed"], f["form"], "-", f["meaning"])
