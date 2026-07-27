// Always format in en-US so decimals use "." regardless of the viewer's OS locale
// (a US-stock app showing "$1,81" for $1.81 is confusing).
const EN = "en-US";

export function compact(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e12) return (n / 1e12).toFixed(2) + "T";
  if (abs >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (abs >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (abs >= 1e3) return (n / 1e3).toFixed(2) + "K";
  return n.toLocaleString(EN);
}

export function usd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return "$" + compact(n);
}

export function pct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toFixed(2) + "%";
}

// Percent with an explicit + / − sign (for period-over-period change).
export function signedPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const s = n > 0 ? "+" : "";
  return s + n.toFixed(2) + "%";
}

export function price(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return "$" + n.toLocaleString(EN, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// A background color for a short-%-of-float "heat" scale: calm below ~10%,
// intensifying through amber to red as it approaches the ~50%+ danger zone.
export function heatColor(pctFloat: number | null | undefined): string {
  if (pctFloat === null || pctFloat === undefined) return "transparent";
  const t = Math.max(0, Math.min(1, pctFloat / 50));
  const alpha = 0.08 + t * 0.32; // 0.08 → 0.40
  // hue 45 (amber) → 8 (red) as t grows
  const hue = 45 - t * 37;
  return `hsla(${hue}, 90%, 50%, ${alpha})`;
}
