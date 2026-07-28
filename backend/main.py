"""FastAPI app: ranking, search, stock detail and candlestick endpoints."""
import json
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import asc, desc, func

from analysis import claude_client, evidence as evidence_mod, heuristic
from config import ANALYSIS_TTL_HOURS, CANDLE_TTL_HOURS, DISCLAIMER
from db import AnalysisCache, CandleCache, SessionLocal, Stock, get_meta, init_db
from market_data import get_candles, resolve_range
from sources import finra_history, short_volume, social

app = FastAPI(title="Short Interest Ranking API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Columns the client may sort by -> model attribute.
SORTABLE = {
    "short_pct_float": Stock.short_pct_float,
    "short_pct_outstanding": Stock.short_pct_outstanding,
    "short_interest": Stock.short_interest,
    "days_to_cover": Stock.days_to_cover,
    "market_cap": Stock.market_cap,
    "dollar_volume": Stock.dollar_volume,
    "float_shares": Stock.float_shares,
}


@app.on_event("startup")
def _startup():
    init_db()


def _stock_dict(s: Stock) -> dict:
    return {
        "symbol": s.symbol,
        "name": s.name,
        "exchange": s.exchange,
        "short_interest": s.short_interest,
        "prev_short_interest": s.prev_short_interest,
        "avg_daily_volume": s.avg_daily_volume,
        "days_to_cover": s.days_to_cover,
        "change_percent": s.change_percent,
        "settlement_date": s.settlement_date,
        "float_shares": s.float_shares,
        "shares_outstanding": s.shares_outstanding,
        "market_cap": s.market_cap,
        "last_close": s.last_close,
        "last_volume": s.last_volume,
        "dollar_volume": s.dollar_volume,
        "short_pct_float": s.short_pct_float,
        "short_pct_outstanding": s.short_pct_outstanding,
        "enriched": s.enriched_at is not None,
        # >100% of float shorted is virtually always a data artifact: float is measured
        # now while short interest is from the settlement date, and reverse splits break
        # the ratio. Flag it so the UI can warn and the default ranking can exclude it.
        "suspect_data": bool(s.short_pct_float and s.short_pct_float > 100),
    }


@app.get("/api/meta")
def meta():
    session = SessionLocal()
    try:
        total = session.query(func.count(Stock.symbol)).scalar() or 0
        enriched = (
            session.query(func.count(Stock.symbol))
            .filter(Stock.short_pct_float.isnot(None), Stock.short_pct_float <= 100)
            .scalar()
            or 0
        )
        return {
            "settlement_date": get_meta(session, "settlement_date"),
            "last_ingest_at": get_meta(session, "last_ingest_at"),
            "last_enrich_at": get_meta(session, "last_enrich_at"),
            "total_stocks": total,
            "ranked_stocks": enriched,
            "disclaimer": DISCLAIMER,
        }
    finally:
        session.close()


@app.get("/api/stocks")
def list_stocks(
    sort: str = "short_pct_float",
    order: str = "desc",
    page: int = 1,
    page_size: int = Query(50, le=200),
    ranked_only: bool = True,
    include_suspect: bool = False,
):
    """Ranked, paginated list. Default: stocks with a computed short % of float, highest first.
    Rows with short % of float > 100 (stale-float / post-split artifacts) are excluded
    unless include_suspect=true."""
    if sort not in SORTABLE:
        raise HTTPException(400, f"Invalid sort field. Options: {list(SORTABLE)}")
    col = SORTABLE[sort]
    direction = desc if order == "desc" else asc

    session = SessionLocal()
    try:
        q = session.query(Stock)
        if ranked_only:
            q = q.filter(Stock.short_pct_float.isnot(None))
        if not include_suspect:
            q = q.filter((Stock.short_pct_float.is_(None)) | (Stock.short_pct_float <= 100))
        total = q.count()
        rows = (
            q.order_by(direction(col).nullslast())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        start_rank = (page - 1) * page_size + 1
        items = []
        for i, s in enumerate(rows):
            d = _stock_dict(s)
            # Rank only meaningful for the default ranked-desc view.
            d["rank"] = start_rank + i if (sort == "short_pct_float" and order == "desc" and ranked_only) else None
            items.append(d)
        return {"total": total, "page": page, "page_size": page_size, "items": items}
    finally:
        session.close()


@app.get("/api/stocks/search")
def search(q: str = Query(..., min_length=1)):
    term = f"%{q.strip().upper()}%"
    session = SessionLocal()
    try:
        rows = (
            session.query(Stock)
            .filter((func.upper(Stock.symbol).like(term)) | (func.upper(Stock.name).like(term)))
            .order_by(Stock.short_interest.desc().nullslast())
            .limit(25)
            .all()
        )
        return {"items": [_stock_dict(s) for s in rows]}
    finally:
        session.close()


@app.get("/api/stocks/{ticker}")
def stock_detail(ticker: str):
    session = SessionLocal()
    try:
        s = session.get(Stock, ticker.strip().upper())
        if not s:
            raise HTTPException(404, "Ticker not found in the current short-interest dataset.")
        return _stock_dict(s)
    finally:
        session.close()


# Cache lifetime scales with bar size — 1-minute bars go stale in a minute,
# daily bars are good for hours.
_CANDLE_TTL_MINUTES = {
    "1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30,
    "60m": 60, "1h": 60, "1d": CANDLE_TTL_HOURS * 60,
}


@app.get("/api/stocks/{ticker}/si-history")
def si_history(ticker: str):
    """Short-interest timeline + the inflection points worth explaining."""
    symbol = ticker.strip().upper()
    return {
        "symbol": symbol,
        "timeline": finra_history.timeline(symbol),
        "inflections": finra_history.inflections(symbol),
        "short_volume": short_volume.trend(symbol),
    }


@app.get("/api/stocks/{ticker}/evidence")
def raw_evidence(ticker: str, mode: str = "short"):
    """The gathered evidence with no LLM involved — always works, no API key."""
    return evidence_mod.gather(ticker.strip().upper(), mode=mode)


def _reason(ticker: str, mode: str, refresh: bool):
    symbol = ticker.strip().upper()
    session = SessionLocal()
    try:
        if not refresh:
            cached = (
                session.query(AnalysisCache)
                .filter_by(symbol=symbol, kind=mode)
                .order_by(AnalysisCache.created_at.desc())
                .first()
            )
            fresh = cached and cached.created_at and (
                datetime.utcnow() - cached.created_at < timedelta(hours=ANALYSIS_TTL_HOURS)
            )
            if fresh:
                payload = json.loads(cached.payload)
                payload["cached"] = True
                return payload

        bundle = evidence_mod.gather(symbol, mode=mode)
        compact = evidence_mod.compact_for_llm(bundle)
        analysis = claude_client.synthesize(compact, mode=mode)

        # When the LLM path is unavailable (no key / refusal / error), fall back
        # to the deterministic rule-based verdict so the button always answers
        # the question instead of showing bare evidence.
        if analysis.get("error"):
            analysis = heuristic.verdict(compact, mode=mode)

        payload = {
            "symbol": symbol,
            "mode": mode,
            "analysis": analysis,
            "evidence": bundle,
            "ai_available": claude_client.available(),
            "x_search_url": social.x_search_url(symbol),
            "cached": False,
        }
        # Cache any real verdict (AI or rule-based); the rule-based one is
        # deterministic so caching it is safe.
        if "error" not in analysis:
            session.add(AnalysisCache(symbol=symbol, kind=mode,
                                      payload=json.dumps(payload, default=str),
                                      created_at=datetime.utcnow()))
            session.commit()
        return payload
    finally:
        session.close()


@app.post("/api/stocks/{ticker}/reason-short")
def reason_short(ticker: str, refresh: bool = False):
    """Why is this company heavily shorted? (the bear thesis)"""
    return _reason(ticker, "short", refresh)


@app.post("/api/stocks/{ticker}/reason-squeeze")
def reason_squeeze(ticker: str, refresh: bool = False):
    """What is moving this stock right now? (squeeze conditions + catalyst)"""
    return _reason(ticker, "squeeze", refresh)


@app.get("/api/stocks/{ticker}/candles")
def candles(ticker: str, range: str = "1y", interval: str = "1d"):
    symbol = ticker.strip().upper()
    # Clamp before caching so 1m+1y and 1m+7d share one cache entry.
    effective_range = resolve_range(range, interval)
    ttl = timedelta(minutes=_CANDLE_TTL_MINUTES.get(interval, 60))
    session = SessionLocal()
    try:
        cached = (
            session.query(CandleCache)
            .filter_by(symbol=symbol, range=effective_range, interval=interval)
            .first()
        )
        fresh = cached and cached.fetched_at and (datetime.utcnow() - cached.fetched_at < ttl)
        if fresh:
            return {"symbol": symbol, "range": effective_range, "interval": interval,
                    "clamped": effective_range != range, "candles": json.loads(cached.payload)}

        try:
            data = get_candles(symbol, effective_range, interval)
        except Exception:
            if cached:  # serve stale on fetch failure
                return {"symbol": symbol, "range": effective_range, "interval": interval,
                        "clamped": effective_range != range, "candles": json.loads(cached.payload)}
            raise HTTPException(502, "Could not fetch price data from the market-data provider.")

        payload = json.dumps(data)
        if cached:
            cached.payload = payload
            cached.fetched_at = datetime.utcnow()
        else:
            session.add(CandleCache(
                symbol=symbol, range=effective_range, interval=interval,
                payload=payload, fetched_at=datetime.utcnow(),
            ))
        session.commit()
        return {"symbol": symbol, "range": effective_range, "interval": interval,
                "clamped": effective_range != range, "candles": data}
    finally:
        session.close()
