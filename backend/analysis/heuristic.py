"""Deterministic, rule-based 'why is it shorted' verdict.

Used when the Claude API isn't configured (no key), so the Reason buttons always
answer the question instead of just dumping evidence. Output matches the exact
shape the frontend renders for the LLM path — verdict, confidence, ranked
factors with citations, contradicting evidence, timeline note — so no UI branch
is needed beyond a small "rule-based" label.

Input is the compacted bundle from evidence.compact_for_llm().
"""


def _fmt(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= div:
            return f"{n / div:.1f}{unit}"
    return f"{n:.0f}"


def verdict(compact: dict, mode: str = "short") -> dict:
    stock = compact.get("stock") or {}
    dilution = compact.get("dilution") or {}
    news = compact.get("news_classification") or {}
    svt = compact.get("short_volume_trend") or {}
    ftd = compact.get("fails_to_deliver") or {}
    inflections = compact.get("inflection_points") or []
    recent_filings = compact.get("recent_filings") or []

    sym = stock.get("symbol") or "This stock"
    spf = stock.get("short_pct_float")
    d2c = stock.get("days_to_cover")

    factors: list[dict] = []
    contra: list[str] = []

    # --- Collect candidate factors, strongest first ------------------------------

    short_sellers = news.get("short_seller_reports") or []
    if short_sellers:
        firms = ", ".join(s.title() for s in short_sellers)
        factors.append({
            "title": "Published short-seller report",
            "explanation": f"Activist short seller(s) {firms} have published bearish "
                           "research — often the direct catalyst for a short thesis.",
            "evidence_type": "news",
            "citations": [h["title"] for h in (compact.get("headlines") or [])
                          if any(f in h["title"].lower() for f in short_sellers)][:3]
                         or [f"{firms} report"],
        })

    offerings = dilution.get("offering_filings") or 0
    if offerings:
        recent = dilution.get("most_recent") or {}
        cite = []
        if recent.get("url"):
            cite.append(recent["url"])
        cite += [f"{f['form']} filed {f['filed']}"
                 for f in recent_filings
                 if f.get("form") in ("S-1", "S-3", "424B5", "424B3", "424B4")][:3]
        factors.append({
            "title": "Dilution / capital raises",
            "explanation": f"{offerings} offering-related filing(s) (shelf/ATM/secondary). "
                           "Ongoing dilution is one of the most common reasons a stock is "
                           "shorted — new shares pressure the price and reward short sellers.",
            "evidence_type": "filing",
            "citations": cite or ["SEC EDGAR offering filings"],
        })

    late = dilution.get("late_filings") or 0
    if late:
        factors.append({
            "title": "Late regulatory filings (distress)",
            "explanation": f"{late} late-filing notice(s) (NT 10-K/10-Q). Missing an SEC "
                           "filing deadline signals accounting or operational distress.",
            "evidence_type": "filing",
            "citations": [f"{f['form']} filed {f['filed']}"
                          for f in recent_filings if f.get("form", "").startswith("NT ")][:3]
                         or ["SEC late-filing notices"],
        })

    crowded = spf is not None and spf >= 15 and d2c is not None and d2c >= 5
    if crowded:
        rising = svt.get("direction") == "rising"
        expl = (f"{spf:.0f}% of the float is sold short and it would take ~{d2c:.1f} days of "
                "normal volume for shorts to cover — a crowded, hard-to-exit position.")
        if rising:
            expl += " Daily short-volume is also trending up, i.e. shorts are still adding."
        factors.append({
            "title": "Crowded, slow-to-cover short",
            "explanation": expl,
            "evidence_type": "short_interest",
            "citations": [f"short % of float {spf:.1f}%", f"days to cover {d2c:.1f}"],
        })
    elif svt.get("direction") == "rising":
        factors.append({
            "title": "Short activity rising",
            "explanation": "Daily short-volume ratio is trending higher between the official "
                           "bi-monthly reports — a nowcast that shorts are actively adding.",
            "evidence_type": "short_interest",
            "citations": [f"short-volume trend: rising (recent avg {svt.get('recent_avg')})"],
        })
    elif svt.get("direction") == "falling":
        contra.append("Daily short-volume is trending down — shorts may be covering, which "
                      "cuts against a worsening bear case.")

    if ftd.get("available") and (ftd.get("max_fails") or 0) > 0:
        factors.append({
            "title": "Persistent settlement failures",
            "explanation": f"Fails-to-deliver peaked around {_fmt(ftd.get('max_fails'))} shares "
                           f"over {ftd.get('days')} reported days — sustained delivery failures "
                           "indicate settlement pressure often tied to heavy shorting.",
            "evidence_type": "fails_to_deliver",
            "citations": [f"max FTD {_fmt(ftd.get('max_fails'))} shares"],
        })

    bear = [b for b in (news.get("bear_signals") or [])]
    if bear and len(factors) < 4:
        factors.append({
            "title": "Negative news flow",
            "explanation": "Recent headlines carry bearish signals: " + ", ".join(bear[:6]) + ".",
            "evidence_type": "news",
            "citations": [h["title"] for h in (compact.get("headlines") or [])][:3],
        })

    bull = news.get("bull_signals") or []
    if bull:
        contra.append("Some headlines are constructive (" + ", ".join(bull[:4]) +
                      "), which could squeeze shorts if it continues.")
    if stock.get("suspect_data"):
        contra.append("Short % of float exceeds 100% — likely a stale-float or reverse-split "
                      "artifact, so the headline short figure may be unreliable.")

    # --- Pick the one-line verdict from the strongest factor ---------------------

    if short_sellers:
        headline = f"{sym} is shorted on an activist short-seller thesis " \
                   f"({', '.join(s.title() for s in short_sellers)})."
        confidence = "high"
    elif offerings >= 2:
        headline = f"Shorts are betting on dilution — {offerings} offering filings are steadily " \
                   "adding shares."
        confidence = "high"
    elif offerings == 1 or late:
        bits = []
        if offerings:
            bits.append("a capital raise")
        if late:
            bits.append("late/distressed filings")
        headline = f"{sym} is shorted mainly on balance-sheet risk — {' and '.join(bits)}."
        confidence = "medium"
    elif crowded:
        headline = f"{sym} is a crowded short: {spf:.0f}% of float shorted, ~{d2c:.1f} days to " \
                   "cover" + (", and shorts are still adding." if svt.get("direction") == "rising" else ".")
        confidence = "medium"
    elif factors:
        headline = f"{sym} is heavily shorted; the clearest driver in the evidence is " \
                   f"{factors[0]['title'].lower()}."
        confidence = "low"
    else:
        headline = "Not enough public evidence here to pin down a specific short thesis — the " \
                   "position may be valuation- or macro-driven."
        confidence = "insufficient evidence"

    # Squeeze mode reframes the same evidence around the near-term setup.
    if mode == "squeeze" and confidence != "insufficient evidence":
        if crowded:
            headline = f"Squeeze setup present: {spf:.0f}% of float short and ~{d2c:.1f} days to " \
                       "cover. A catalyst could force covering — " + (
                           "recent bullish news is the likely spark." if bull
                           else "no clear catalyst in the evidence yet.")
        else:
            headline = f"Short interest is elevated but the classic squeeze fuel " \
                       "(very high short % + high days-to-cover) isn't all present here."

    # --- Timeline note: when the shorting actually ramped ------------------------

    timeline_note = ""
    if inflections:
        top = inflections[0]
        forms = ", ".join(sorted({f["form"] for f in (top.get("filings_in_window") or [])}))
        timeline_note = f"Short interest jumped {top['change_pct']:+.0f}% around " \
                        f"{top['settlement_date']}."
        if forms:
            timeline_note += f" Filings in that window: {forms}."

    return {
        "verdict": headline,
        "confidence": confidence,
        "factors": factors[:5],
        "contradicting_evidence": contra,
        "timeline_note": timeline_note,
        "source": "rules",
    }
