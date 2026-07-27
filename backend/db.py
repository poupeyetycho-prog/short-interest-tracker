"""SQLAlchemy models and session setup (SQLite)."""
from datetime import datetime

from sqlalchemy import (
    Column, DateTime, Float, Integer, String, Text, UniqueConstraint, create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DB_URL

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


class Stock(Base):
    """One row per ticker: FINRA short-interest fields + yfinance enrichment + computed ranking metric."""
    __tablename__ = "stocks"

    symbol = Column(String, primary_key=True)
    name = Column(String)
    exchange = Column(String)            # marketClassCode (NYSE / NNM / SC / AMEX)

    # --- FINRA (official, bi-monthly) ---
    short_interest = Column(Integer)     # currentShortPositionQuantity (shares)
    prev_short_interest = Column(Integer)
    avg_daily_volume = Column(Integer)   # averageDailyVolumeQuantity (shares)
    days_to_cover = Column(Float)
    change_percent = Column(Float)
    settlement_date = Column(String)     # 'YYYY-MM-DD'

    # --- yfinance enrichment (daily) ---
    float_shares = Column(Integer)
    shares_outstanding = Column(Integer)
    market_cap = Column(Float)
    last_close = Column(Float)
    last_volume = Column(Integer)
    dollar_volume = Column(Float)        # last_close * last_volume
    enriched_at = Column(DateTime)

    # --- computed ---
    short_pct_float = Column(Float)      # short_interest / float_shares * 100
    short_pct_outstanding = Column(Float)

    updated_at = Column(DateTime, default=datetime.utcnow)


class CandleCache(Base):
    """Cached OHLCV payload per (symbol, range, interval)."""
    __tablename__ = "candle_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    range = Column(String)
    interval = Column(String)
    payload = Column(Text)               # JSON string
    fetched_at = Column(DateTime, default=datetime.utcnow)


class ShortInterestHistory(Base):
    """One row per (symbol, settlement date) from the FINRA archive — powers the
    'when did the shorting actually start' timeline and inflection detection."""
    __tablename__ = "short_interest_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    settlement_date = Column(String, index=True)   # 'YYYY-MM-DD'
    short_interest = Column(Integer)
    avg_daily_volume = Column(Integer)
    days_to_cover = Column(Float)

    __table_args__ = (UniqueConstraint("symbol", "settlement_date", name="uix_sih"),)


class DailyShortVolume(Base):
    """FINRA daily short *volume* (flow), NOT short interest (position).

    A large share of this is market-maker hedging that is covered intraday, so it
    must never be presented as '% of float shorted' — it is used only as a
    freshness/trend layer between the bi-monthly position reports.
    """
    __tablename__ = "daily_short_volume"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    date = Column(String, index=True)              # 'YYYY-MM-DD'
    short_volume = Column(Float)
    total_volume = Column(Float)
    ratio = Column(Float)                          # short_volume / total_volume

    __table_args__ = (UniqueConstraint("symbol", "date", name="uix_dsv"),)


class AnalysisCache(Base):
    """Cached output of the Reason Short / Reason Squeeze pipelines."""
    __tablename__ = "analysis_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    kind = Column(String)                          # 'short' | 'squeeze' | 'evidence'
    payload = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class Alert(Base):
    """Every alert the scanner raises — the record used to grade the rules."""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    tier = Column(String)                          # watch|heads_up|urgent|confirmed|continuation|building
    triggered_at = Column(DateTime, default=datetime.utcnow)
    trade_date = Column(String, index=True)        # 'YYYY-MM-DD' (for per-day cooldown)
    price = Column(Float)
    prev_close = Column(Float)
    pct_change = Column(Float)
    rvol = Column(Float)
    catalyst = Column(Text)                        # short label, or NULL when none found
    pushed = Column(Integer, default=0)            # 1 once delivered


class WatchlistEntry(Base):
    """Structural-gate survivors the scanner polls (short % of float + days-to-cover)."""
    __tablename__ = "watchlist"

    symbol = Column(String, primary_key=True)
    short_pct_float = Column(Float)
    days_to_cover = Column(Float)
    added_at = Column(DateTime, default=datetime.utcnow)


class MetaKV(Base):
    """Simple key/value store for ingest metadata (settlement date, timestamps)."""
    __tablename__ = "meta"

    key = Column(String, primary_key=True)
    value = Column(String)


def init_db():
    Base.metadata.create_all(engine)


def get_meta(session, key, default=None):
    row = session.get(MetaKV, key)
    return row.value if row else default


def set_meta(session, key, value):
    row = session.get(MetaKV, key)
    if row:
        row.value = str(value)
    else:
        session.add(MetaKV(key=key, value=str(value)))
