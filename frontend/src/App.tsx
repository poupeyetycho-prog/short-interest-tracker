import { useEffect, useState } from "react";
import { Meta, fetchMeta } from "./api";
import SearchBar from "./components/SearchBar";
import RankingTable from "./components/RankingTable";
import StockDetail from "./components/StockDetail";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [includeSuspect, setIncludeSuspect] = useState(false);

  useEffect(() => {
    fetchMeta().then(setMeta).catch(() => setMeta(null));
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <h1>Short Interest Tracker</h1>
          <p className="tagline">US exchange-listed stocks ranked by short&nbsp;% of float</p>
        </div>
        <SearchBar onPick={setSelected} />
      </header>

      {meta && (
        <div className="meta-bar">
          <span className="badge" title="The settlement date of the short-interest report currently loaded.">
            Short interest as of <strong>{meta.settlement_date ?? "—"}</strong>
          </span>
          <span className="meta-count">
            {meta.ranked_stocks.toLocaleString("en-US")} ranked · {meta.total_stocks.toLocaleString("en-US")} tracked
          </span>
          <span className="info" tabIndex={0} title={meta.disclaimer}>
            ⓘ Why is this delayed?
          </span>
          {!selected && (
            <label className="anomaly-toggle" title="Show stocks whose short % of float exceeds 100% — almost always a stale-float or post-split data artifact.">
              <input
                type="checkbox"
                checked={includeSuspect}
                onChange={(e) => setIncludeSuspect(e.target.checked)}
              />
              Show data anomalies
            </label>
          )}
        </div>
      )}

      <main>
        {selected ? (
          <StockDetail ticker={selected} onBack={() => setSelected(null)} />
        ) : (
          <RankingTable onPick={setSelected} includeSuspect={includeSuspect} />
        )}
      </main>

      <footer className="app-footer">
        Data: <strong>FINRA</strong> (short interest, official bi-monthly) · <strong>Yahoo Finance</strong>{" "}
        (price, float, market cap). For information only — not investment advice.
      </footer>
    </div>
  );
}
