import { useEffect, useState } from "react";
import { Stock, fetchStocks } from "../api";
import { compact, usd, pct, price, signedPct, heatColor } from "../format";

const COLUMNS: { key: string; label: string; sortable: boolean; tip: string }[] = [
  { key: "rank", label: "#", sortable: false, tip: "Rank by short % of float" },
  { key: "symbol", label: "Ticker", sortable: false, tip: "Ticker and company name — click a row for details" },
  { key: "short_pct_float", label: "Short % Float", sortable: true, tip: "Shares sold short ÷ shares available to trade (float). The headline 'how heavily shorted' metric." },
  { key: "days_to_cover", label: "Days to Cover", sortable: true, tip: "Short interest ÷ average daily volume — trading days it would take shorts to buy back." },
  { key: "float_shares", label: "Float", sortable: true, tip: "Shares available for public trading." },
  { key: "market_cap", label: "Market Cap", sortable: true, tip: "Share price × shares outstanding." },
  { key: "dollar_volume", label: "$ Daily Volume", sortable: true, tip: "Latest close × latest day's share volume." },
  { key: "short_interest", label: "Short Interest", sortable: true, tip: "Shares sold short (official FINRA figure). ▲/▼ = change vs prior report." },
  { key: "last_close", label: "Price", sortable: false, tip: "Latest close price." },
];

const PAGE_SIZE = 50;

export default function RankingTable({
  onPick,
  includeSuspect,
}: {
  onPick: (symbol: string) => void;
  includeSuspect: boolean;
}) {
  const [rows, setRows] = useState<Stock[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("short_pct_float");
  const [order, setOrder] = useState("desc");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchStocks({ sort, order, page, page_size: PAGE_SIZE, includeSuspect })
      .then((r) => {
        setRows(r.items);
        setTotal(r.total);
      })
      .finally(() => setLoading(false));
  }, [sort, order, page, includeSuspect]);

  // Reset to page 1 when the anomalies toggle changes.
  useEffect(() => setPage(1), [includeSuspect]);

  function toggleSort(key: string) {
    if (sort === key) {
      setOrder(order === "desc" ? "asc" : "desc");
    } else {
      setSort(key);
      setOrder("desc");
    }
    setPage(1);
  }

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="table-card">
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  className={c.sortable ? "sortable" : ""}
                  title={c.tip}
                  onClick={() => c.sortable && toggleSort(c.key)}
                >
                  {c.label}
                  {c.sortable && (
                    <span className="arrow">{sort === c.key ? (order === "desc" ? " ▼" : " ▲") : " ↕"}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((s, i) => {
              const rank = s.rank ?? (page - 1) * PAGE_SIZE + i + 1;
              const chg = s.change_percent;
              return (
                <tr key={s.symbol} onClick={() => onPick(s.symbol)} title={`View ${s.symbol} details & chart`}>
                  <td className="dim">{rank}</td>
                  <td className="ticker-cell">
                    <span className="ticker">{s.symbol}</span>
                    <span className="row-name">{s.name}</span>
                  </td>
                  <td className="strong pct-cell" style={{ background: heatColor(s.short_pct_float) }}>
                    {pct(s.short_pct_float)}
                    {s.suspect_data && <span className="suspect-dot" title="Likely stale-float / post-split artifact">⚠</span>}
                  </td>
                  <td>{s.days_to_cover?.toFixed(2) ?? "—"}</td>
                  <td>{compact(s.float_shares)}</td>
                  <td>{usd(s.market_cap)}</td>
                  <td>{usd(s.dollar_volume)}</td>
                  <td>
                    {compact(s.short_interest)}
                    {chg !== null && chg !== undefined && (
                      <span className={"si-delta " + (chg > 0 ? "up" : chg < 0 ? "down" : "")}>
                        {chg > 0 ? "▲" : chg < 0 ? "▼" : ""}
                        {Math.abs(chg).toFixed(1)}%
                      </span>
                    )}
                  </td>
                  <td>{price(s.last_close)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {loading && <div className="table-loading">Loading…</div>}
      {!loading && rows.length === 0 && <div className="table-loading">No stocks to show.</div>}
      <div className="pager">
        <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
          ← Prev
        </button>
        <span>
          Page {page} / {pages} · {total.toLocaleString("en-US")} ranked stocks
        </span>
        <button disabled={page >= pages} onClick={() => setPage(page + 1)}>
          Next →
        </button>
      </div>
    </div>
  );
}
