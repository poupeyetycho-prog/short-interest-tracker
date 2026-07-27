import { useEffect, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  CandlestickData,
  HistogramData,
} from "lightweight-charts";
import { Candle, fetchCandles } from "../api";
import { price } from "../format";

// Ranges offered per interval — kept in step with the backend's clamping matrix
// (1m -> 7d, 5m/15m -> 60d, 1h -> 730d, 1d -> years).
const INTERVALS: { key: string; label: string; ranges: string[] }[] = [
  { key: "1m", label: "1m", ranges: ["1d", "5d"] },
  { key: "5m", label: "5m", ranges: ["5d", "1mo"] },
  { key: "15m", label: "15m", ranges: ["5d", "1mo", "3mo"] },
  { key: "1h", label: "1H", ranges: ["1mo", "3mo", "6mo", "1y", "2y"] },
  { key: "1d", label: "1D", ranges: ["3mo", "6mo", "1y", "2y", "5y"] },
];

const RANGE_LABEL: Record<string, string> = {
  "1d": "1D", "5d": "5D", "1mo": "1M", "3mo": "3M",
  "6mo": "6M", "1y": "1Y", "2y": "2Y", "5y": "5Y",
};

export default function CandlestickChart({ ticker }: { ticker: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [interval, setInterval] = useState("1d");
  const [range, setRange] = useState("1y");
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [legend, setLegend] = useState<Candle | null>(null);
  const [periodChange, setPeriodChange] = useState<number | null>(null);

  const activeIv = INTERVALS.find((i) => i.key === interval)!;

  // Keep the range legal whenever the interval changes.
  function pickInterval(iv: string) {
    const def = INTERVALS.find((i) => i.key === iv)!;
    setInterval(iv);
    if (!def.ranges.includes(range)) {
      setRange(def.ranges[def.ranges.length - 1]);
    }
  }

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let cancelled = false;
    setStatus("loading");
    setLegend(null);

    const isIntraday = interval !== "1d";
    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#c8cdd6",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.05)" },
        horzLines: { color: "rgba(255,255,255,0.05)" },
      },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.1)" },
      timeScale: {
        borderColor: "rgba(255,255,255,0.1)",
        timeVisible: isIntraday,
        secondsVisible: false,
      },
      autoSize: true,
      crosshair: { mode: 1 },
    });

    fetchCandles(ticker, range, interval)
      .then((res) => {
        if (cancelled) return;
        if (!res.candles.length) {
          setStatus("error");
          return;
        }
        const candleSeries = chart.addCandlestickSeries({
          upColor: "#26a69a",
          downColor: "#ef5350",
          borderUpColor: "#26a69a",
          borderDownColor: "#ef5350",
          wickUpColor: "#26a69a",
          wickDownColor: "#ef5350",
        });
        candleSeries.setData(res.candles as unknown as CandlestickData[]);

        const volSeries = chart.addHistogramSeries({
          priceFormat: { type: "volume" },
          priceScaleId: "vol",
        });
        chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
        volSeries.setData(
          res.candles.map((c) => ({
            time: c.time,
            value: c.volume,
            color: c.close >= c.open ? "rgba(38,166,154,0.4)" : "rgba(239,83,80,0.4)",
          })) as unknown as HistogramData[]
        );

        chart.timeScale().fitContent();

        const first = res.candles[0].close;
        const last = res.candles[res.candles.length - 1].close;
        setPeriodChange(first ? ((last - first) / first) * 100 : null);
        setLegend(res.candles[res.candles.length - 1]);

        const byTime = new Map(res.candles.map((c) => [String(c.time), c]));
        chart.subscribeCrosshairMove((param) => {
          if (!param.time) {
            setLegend(res.candles[res.candles.length - 1]);
            return;
          }
          const c = byTime.get(String(param.time));
          if (c) setLegend(c);
        });

        setStatus("ok");
      })
      .catch(() => !cancelled && setStatus("error"));

    return () => {
      cancelled = true;
      chart.remove();
    };
  }, [ticker, range, interval]);

  const up = legend ? legend.close >= legend.open : true;
  const legendTime =
    legend == null
      ? ""
      : typeof legend.time === "number"
      ? new Date(legend.time * 1000).toLocaleString("en-US", {
          month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
        })
      : String(legend.time);

  return (
    <div className="chart-card">
      <div className="chart-toolbar">
        <div className="chart-legend">
          <span className="chart-title">{ticker}</span>
          {legend && (
            <span className="ohlc">
              <span className="legend-date">{legendTime}</span>
              <span>O <b>{price(legend.open)}</b></span>
              <span>H <b>{price(legend.high)}</b></span>
              <span>L <b>{price(legend.low)}</b></span>
              <span>C <b className={up ? "up" : "down"}>{price(legend.close)}</b></span>
              <span>Vol <b>{legend.volume.toLocaleString("en-US")}</b></span>
            </span>
          )}
          {periodChange != null && (
            <span className={"period-change " + (periodChange >= 0 ? "up" : "down")}>
              {periodChange >= 0 ? "▲" : "▼"} {Math.abs(periodChange).toFixed(2)}%
            </span>
          )}
        </div>
        <div className="chart-controls">
          <div className="range-toggle interval-toggle">
            {INTERVALS.map((iv) => (
              <button
                key={iv.key}
                className={iv.key === interval ? "active" : ""}
                onClick={() => pickInterval(iv.key)}
                title={`${iv.label} candles`}
              >
                {iv.label}
              </button>
            ))}
          </div>
          <div className="range-toggle">
            {activeIv.ranges.map((r) => (
              <button key={r} className={r === range ? "active" : ""} onClick={() => setRange(r)}>
                {RANGE_LABEL[r] ?? r}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="chart-host">
        <div ref={containerRef} className="chart-canvas" />
        {status === "loading" && <div className="chart-overlay">Loading chart…</div>}
        {status === "error" && (
          <div className="chart-overlay">No price data available for this interval.</div>
        )}
      </div>
    </div>
  );
}
