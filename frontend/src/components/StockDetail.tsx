import { useEffect, useState } from "react";
import { Stock, fetchStock } from "../api";
import { compact, usd, pct, price, signedPct } from "../format";
import CandlestickChart from "./CandlestickChart";
import ReasonPanel from "./ReasonPanel";
import ShortInterestTimeline from "./ShortInterestTimeline";
import ErrorBoundary from "./ErrorBoundary";

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "accent" | "up" | "down";
}) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={"stat-value" + (tone ? " " + tone : "")}>{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export default function StockDetail({ ticker, onBack }: { ticker: string; onBack: () => void }) {
  const [s, setS] = useState<Stock | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    setS(null);
    setError(false);
    fetchStock(ticker).then(setS).catch(() => setError(true));
  }, [ticker]);

  if (error) {
    return (
      <div className="detail">
        <button className="back" onClick={onBack}>← Back to ranking</button>
        <p className="empty">Could not load {ticker}.</p>
      </div>
    );
  }
  if (!s) {
    return (
      <div className="detail">
        <button className="back" onClick={onBack}>← Back to ranking</button>
        <p className="empty">Loading {ticker}…</p>
      </div>
    );
  }

  const chg = s.change_percent;
  const chgTone = chg == null ? undefined : chg > 0 ? "up" : chg < 0 ? "down" : undefined;

  return (
    <div className="detail">
      <button className="back" onClick={onBack}>← Back to ranking</button>
      <div className="detail-head">
        <div>
          <h2>
            {s.symbol} <span className="detail-name">{s.name}</span>
          </h2>
          <div className="detail-sub">
            {s.exchange} · {price(s.last_close)}
          </div>
        </div>
        {s.suspect_data && (
          <div className="warn-badge" title="Short % of float exceeds 100% — almost certainly a stale-float or post-split data artifact.">
            ⚠ Short % looks unreliable (stale float / split)
          </div>
        )}
      </div>

      <div className="stat-grid">
        <Stat label="Short % of Float" value={pct(s.short_pct_float)} tone="accent" hint={`short interest ÷ float · as of ${s.settlement_date ?? "—"}`} />
        <Stat label="Float" value={compact(s.float_shares)} hint="shares available to trade" />
        <Stat label="Market Cap" value={usd(s.market_cap)} hint="price × shares outstanding" />
        <Stat label="$ Daily Volume" value={usd(s.dollar_volume)} hint="last close × volume" />
        <Stat label="Days to Cover" value={s.days_to_cover?.toFixed(2) ?? "—"} hint="short interest ÷ avg daily volume" />
        <Stat label="Short Interest" value={compact(s.short_interest)} hint="shares sold short (FINRA)" />
        <Stat
          label="Change vs Prior Report"
          value={signedPct(chg)}
          tone={chgTone}
          hint={s.prev_short_interest != null ? `was ${compact(s.prev_short_interest)} shares` : undefined}
        />
        <Stat label="Short % of Outstanding" value={pct(s.short_pct_outstanding)} hint={`${compact(s.shares_outstanding)} shares outstanding`} />
      </div>

      <ErrorBoundary label="price chart">
        <CandlestickChart ticker={s.symbol} />
      </ErrorBoundary>

      <ErrorBoundary label="research">
        <ReasonPanel
          ticker={s.symbol}
          xUrl={`https://x.com/search?q=%24${s.symbol}&f=live`}
        />
      </ErrorBoundary>

      <ErrorBoundary label="short-interest timeline">
        <ShortInterestTimeline ticker={s.symbol} />
      </ErrorBoundary>
    </div>
  );
}
