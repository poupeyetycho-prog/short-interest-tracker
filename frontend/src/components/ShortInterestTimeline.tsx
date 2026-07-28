import { useEffect, useRef, useState } from "react";
import { createChart, ColorType, LineData } from "lightweight-charts";
import { SiPoint, Inflection, fetchSiHistory } from "../api";
import { compact, signedPct } from "../format";

/** Short interest over time, with the biggest jumps called out.
 *  This is the "when did the shorting actually start" view. */
export default function ShortInterestTimeline({ ticker }: { ticker: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [timeline, setTimeline] = useState<SiPoint[]>([]);
  const [inflections, setInflections] = useState<Inflection[]>([]);
  const [status, setStatus] = useState<"loading" | "ok" | "empty">("loading");

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    fetchSiHistory(ticker)
      .then((r) => {
        if (cancelled) return;
        setTimeline(r.timeline ?? []);
        setInflections(r.inflections ?? []);
        setStatus((r.timeline ?? []).length ? "ok" : "empty");
      })
      .catch(() => !cancelled && setStatus("empty"));
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  useEffect(() => {
    const el = ref.current;
    if (!el || status !== "ok" || !timeline.length) return;

    const chart = createChart(el, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#c8cdd6",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.05)" },
        horzLines: { color: "rgba(255,255,255,0.05)" },
      },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.1)" },
      timeScale: { borderColor: "rgba(255,255,255,0.1)" },
      autoSize: true,
      height: 220,
    });

    const series = chart.addAreaSeries({
      lineColor: "#f6ad55",
      topColor: "rgba(246,173,85,0.35)",
      bottomColor: "rgba(246,173,85,0.02)",
      lineWidth: 2,
    });
    series.setData(
      timeline
        .filter((t) => t.short_interest != null)
        .map((t) => ({ time: t.settlement_date, value: t.short_interest as number })) as LineData[]
    );

    // Mark the periods where shorting ramped hardest.
    //
    // setMarkers() requires ASCENDING TIME ORDER and throws otherwise, which
    // unmounted the whole app. The API deliberately returns inflections sorted
    // by change size (biggest jump first) for the list below, so sort a copy by
    // date here rather than changing the API's ordering.
    if (inflections.length) {
      const byDate = [...inflections].sort((a, b) =>
        a.settlement_date < b.settlement_date ? -1 : a.settlement_date > b.settlement_date ? 1 : 0
      );
      series.setMarkers(
        byDate.map((i) => ({
          time: i.settlement_date,
          position: "aboveBar" as const,
          color: "#ef5350",
          shape: "arrowUp" as const,
          text: `+${i.change_pct}%`,
        }))
      );
    }

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [timeline, inflections, status]);

  if (status === "loading") return <div className="si-card"><div className="chart-overlay">Loading short-interest history…</div></div>;
  if (status === "empty")
    return (
      <div className="si-card">
        <div className="si-empty">
          No short-interest history stored yet for {ticker}. Run the FINRA history
          backfill to populate it.
        </div>
      </div>
    );

  const latest = timeline[timeline.length - 1];

  return (
    <div className="si-card">
      <div className="si-head">
        <span className="chart-title">Short interest over time — {ticker}</span>
        {latest && (
          <span className="si-latest">
            latest {compact(latest.short_interest)} shares
            {latest.change_pct != null && (
              <span className={latest.change_pct >= 0 ? "up" : "down"}>
                {" "}({signedPct(latest.change_pct)})
              </span>
            )}
            <span className="dim"> · {timeline.length} reports</span>
          </span>
        )}
      </div>
      <div ref={ref} className="si-canvas" />
      {!!inflections.length && (
        <div className="si-inflections">
          {inflections.map((i, k) => (
            <div key={k} className="si-infl">
              <strong>{i.settlement_date}</strong>
              <span className="up"> +{i.change_pct}%</span>
              {!!i.filings_in_window?.length && (
                <span className="dim">
                  {" "}· {i.filings_in_window.length} SEC filing
                  {i.filings_in_window.length === 1 ? "" : "s"} in that window
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
