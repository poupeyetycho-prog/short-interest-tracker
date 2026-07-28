import { useState } from "react";
import { ReasonResult, fetchReason } from "../api";
import { compact, pct } from "../format";

type Mode = "short" | "squeeze";

const LABEL: Record<Mode, string> = {
  short: "Reason Short",
  squeeze: "Reason Short Squeeze",
};

const CONFIDENCE_TONE: Record<string, string> = {
  high: "conf-high",
  medium: "conf-medium",
  low: "conf-low",
  "insufficient evidence": "conf-none",
};

export default function ReasonPanel({ ticker, xUrl }: { ticker: string; xUrl: string }) {
  const [mode, setMode] = useState<Mode | null>(null);
  const [result, setResult] = useState<ReasonResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function run(m: Mode) {
    setMode(m);
    setLoading(true);
    setError(null);
    setResult(null);
    fetchReason(ticker, m)
      .then(setResult)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }

  const a = result?.analysis;
  const ev = result?.evidence;

  return (
    <div className="reason-card">
      <div className="reason-actions">
        <button className="reason-btn" onClick={() => run("short")} disabled={loading}>
          🔍 Reason Short
        </button>
        <button className="reason-btn squeeze" onClick={() => run("squeeze")} disabled={loading}>
          🚀 Reason Short Squeeze
        </button>
        <a className="reason-btn ghost" href={xUrl} target="_blank" rel="noreferrer"
           title="Opens X search in your browser — reading it yourself is fully compliant with X's terms.">
          𝕏 Search X for ${ticker}
        </a>
      </div>

      {loading && (
        <div className="reason-loading">
          Gathering filings, news, short-interest history and sentiment for {ticker}…
        </div>
      )}
      {error && <div className="reason-error">Could not load analysis: {error}</div>}

      {result && (
        <div className="reason-body">
          <div className="reason-head">
            <h3>{LABEL[mode!]} — {result.symbol}</h3>
            {result.cached && <span className="cached-pill">cached</span>}
          </div>

          {/* Verdict first — the quick answer */}
          {a?.verdict && (
            <div className="verdict">
              <div className="verdict-label">Verdict</div>
              <div className="verdict-text">{a.verdict}</div>
              {a.confidence && (
                <span className={"confidence " + (CONFIDENCE_TONE[a.confidence] ?? "")}>
                  confidence: {a.confidence}
                </span>
              )}
            </div>
          )}

          {a?.source === "rules" && (
            <div className="reason-notice rules-note">
              <strong>Rule-based summary</strong> — computed from the evidence below.
              Set <code>ANTHROPIC_API_KEY</code> for a deeper AI-written analysis.
            </div>
          )}

          {a?.error && (
            <div className="reason-notice">
              {a.error === "no_api_key"
                ? "AI synthesis is off (no ANTHROPIC_API_KEY set). Showing the raw evidence below — every source still works."
                : `Synthesis unavailable: ${a.message ?? a.error}. Raw evidence is shown below.`}
            </div>
          )}

          {a?.timeline_note && <p className="timeline-note">📅 {a.timeline_note}</p>}

          {!!a?.factors?.length && (
            <ol className="factors">
              {a.factors.map((f, i) => (
                <li key={i} className="factor">
                  <div className="factor-title">
                    <span className="factor-rank">{i + 1}</span>
                    {f.title}
                    <span className="factor-type">{f.evidence_type.replace(/_/g, " ")}</span>
                  </div>
                  <p>{f.explanation}</p>
                  {!!f.citations?.length && (
                    <div className="citations">
                      {f.citations.map((c, j) =>
                        c.startsWith("http") ? (
                          <a key={j} href={c} target="_blank" rel="noreferrer">source {j + 1}</a>
                        ) : (
                          <span key={j} className="cite-text">{c}</span>
                        )
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ol>
          )}

          {!!a?.contradicting_evidence?.length && (
            <div className="contra">
              <div className="contra-label">Contradicting evidence</div>
              <ul>{a.contradicting_evidence.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </div>
          )}

          {/* Raw evidence — always shown, works with or without the AI layer */}
          {ev && <EvidenceDashboard ev={ev} />}
        </div>
      )}
    </div>
  );
}

function EvidenceDashboard({ ev }: { ev: any }) {
  const filings = Array.isArray(ev.filings) ? ev.filings : [];
  const heads = Array.isArray(ev.headlines) ? ev.headlines : [];
  const cls = ev.news_classification ?? {};
  const sv = ev.short_volume_trend ?? {};
  const st = ev.stocktwits ?? {};
  const ftd = ev.fails_to_deliver ?? {};

  return (
    <details className="evidence" open>
      <summary>Evidence gathered</summary>

      {!!ev.inflections?.length && (
        <div className="ev-block">
          <h4>Short-interest inflection points</h4>
          {ev.inflections.map((i: any, k: number) => (
            <div key={k} className="inflection">
              <div className="infl-head">
                <strong>{i.settlement_date}</strong> — short interest{" "}
                <span className="up">+{i.change_pct}%</span> vs prior report
              </div>
              {!!i.filings_in_window?.length && (
                <ul className="infl-filings">
                  {i.filings_in_window.slice(0, 6).map((f: any, j: number) => (
                    <li key={j}>
                      <span className="form">{f.form}</span> {f.filed}
                      {f.meaning && <em> — {f.meaning}</em>}
                      {f.url && <a href={f.url} target="_blank" rel="noreferrer"> ↗</a>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}

      {!!cls.short_seller_reports?.length && (
        <div className="ev-block warn">
          <h4>⚠ Short-seller report detected</h4>
          <p>{cls.short_seller_reports.join(", ")}</p>
        </div>
      )}

      <div className="ev-grid">
        <div className="ev-block">
          <h4>Dilution signals</h4>
          <p>
            Offering filings: <strong>{ev.dilution?.offering_filings ?? "—"}</strong>
            {" · "}Late filings: <strong>{ev.dilution?.late_filings ?? "—"}</strong>
          </p>
        </div>
        <div className="ev-block">
          <h4>Short volume trend</h4>
          <p>
            Direction: <strong>{sv.direction ?? "—"}</strong>
            {sv.recent_avg != null && <> · recent {pct(sv.recent_avg * 100)}</>}
          </p>
          <small>Flow, not position — includes market-maker hedging.</small>
        </div>
        <div className="ev-block">
          <h4>Fails to deliver</h4>
          <p>
            {ftd.available
              ? <>Max <strong>{compact(ftd.max_fails)}</strong> over {ftd.days} days</>
              : "No data"}
          </p>
        </div>
        <div className="ev-block">
          <h4>Retail sentiment</h4>
          <p>
            StockTwits: <strong>{st.messages ?? "—"}</strong> msgs
            {st.bull_ratio != null && <> · {Math.round(st.bull_ratio * 100)}% bullish</>}
          </p>
          {ev.reddit?.available === false && <small>Reddit not configured</small>}
        </div>
      </div>

      {!!filings.length && (
        <div className="ev-block">
          <h4>Recent SEC filings</h4>
          <ul className="filing-list">
            {filings.slice(0, 10).map((f: any, i: number) => (
              <li key={i}>
                <span className="form">{f.form}</span> {f.filed}
                {f.meaning && <em> — {f.meaning}</em>}
                {f.url && <a href={f.url} target="_blank" rel="noreferrer"> ↗</a>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {!!heads.length && (
        <div className="ev-block">
          <h4>Headlines</h4>
          <ul className="headline-list">
            {heads.slice(0, 10).map((h: any, i: number) => (
              <li key={i}>
                <a href={h.url} target="_blank" rel="noreferrer">{h.title}</a>
                <span className="src">{h.source}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </details>
  );
}
