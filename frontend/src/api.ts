export interface Stock {
  symbol: string;
  name: string;
  exchange: string;
  short_interest: number | null;
  prev_short_interest: number | null;
  avg_daily_volume: number | null;
  days_to_cover: number | null;
  change_percent: number | null;
  settlement_date: string | null;
  float_shares: number | null;
  shares_outstanding: number | null;
  market_cap: number | null;
  last_close: number | null;
  last_volume: number | null;
  dollar_volume: number | null;
  short_pct_float: number | null;
  short_pct_outstanding: number | null;
  enriched: boolean;
  suspect_data: boolean;
  rank?: number | null;
}

export interface Meta {
  settlement_date: string | null;
  last_ingest_at: string | null;
  last_enrich_at: string | null;
  total_stocks: number;
  ranked_stocks: number;
  disclaimer: string;
}

export interface Candle {
  /** 'YYYY-MM-DD' for daily bars, unix seconds for intraday bars. */
  time: string | number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const fetchMeta = () => get<Meta>("/api/meta");

export const fetchStocks = (params: {
  sort: string;
  order: string;
  page: number;
  page_size: number;
  includeSuspect?: boolean;
}) =>
  get<{ total: number; page: number; page_size: number; items: Stock[] }>(
    `/api/stocks?sort=${params.sort}&order=${params.order}&page=${params.page}` +
      `&page_size=${params.page_size}&include_suspect=${params.includeSuspect ? "true" : "false"}`
  );

export const searchStocks = (q: string) =>
  get<{ items: Stock[] }>(`/api/stocks/search?q=${encodeURIComponent(q)}`);

export const fetchStock = (ticker: string) => get<Stock>(`/api/stocks/${ticker}`);

export interface SiPoint {
  settlement_date: string;
  short_interest: number | null;
  days_to_cover: number | null;
  change_pct: number | null;
}

export interface Inflection {
  settlement_date: string;
  change_pct: number;
  window_start: string;
  window_end: string;
  filings_in_window?: { form: string; filed: string; meaning?: string; url?: string }[];
}

export interface ReasonFactor {
  title: string;
  explanation: string;
  evidence_type: string;
  citations: string[];
}

export interface ReasonAnalysis {
  verdict?: string;
  confidence?: string;
  factors?: ReasonFactor[];
  contradicting_evidence?: string[];
  timeline_note?: string;
  error?: string;
  message?: string;
  _model?: string;
}

export interface ReasonResult {
  symbol: string;
  mode: string;
  analysis: ReasonAnalysis;
  evidence: any;
  ai_available: boolean;
  x_search_url: string;
  cached: boolean;
}

export const fetchSiHistory = (ticker: string) =>
  get<{ symbol: string; timeline: SiPoint[]; inflections: Inflection[]; short_volume: any }>(
    `/api/stocks/${ticker}/si-history`
  );

export async function fetchReason(ticker: string, mode: "short" | "squeeze", refresh = false) {
  const res = await fetch(`/api/stocks/${ticker}/reason-${mode}?refresh=${refresh}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as ReasonResult;
}

export const fetchCandles = (ticker: string, range: string, interval = "1d") =>
  get<{ symbol: string; range: string; interval: string; clamped: boolean; candles: Candle[] }>(
    `/api/stocks/${ticker}/candles?range=${range}&interval=${interval}`
  );
