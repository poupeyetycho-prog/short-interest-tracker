import { useEffect, useRef, useState } from "react";
import { Stock, searchStocks } from "../api";
import { pct } from "../format";

export default function SearchBar({ onPick }: { onPick: (symbol: string) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Stock[]>([]);
  const [open, setOpen] = useState(false);
  const [searched, setSearched] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  // Debounced search.
  useEffect(() => {
    if (q.trim().length < 1) {
      setResults([]);
      setSearched(false);
      return;
    }
    const t = setTimeout(() => {
      searchStocks(q.trim())
        .then((r) => {
          setResults(r.items);
          setSearched(true);
          setOpen(true);
        })
        .catch(() => setResults([]));
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  // Close dropdown on outside click.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  function pick(sym: string) {
    onPick(sym);
    setQ("");
    setResults([]);
    setSearched(false);
    setOpen(false);
  }

  return (
    <div className="search" ref={boxRef}>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => results.length && setOpen(true)}
        onKeyDown={(e) => e.key === "Enter" && results[0] && pick(results[0].symbol)}
        placeholder="Search ticker or company…"
        aria-label="Search stocks"
      />
      {open && results.length > 0 && (
        <ul className="search-results">
          {results.map((s) => (
            <li key={s.symbol} onClick={() => pick(s.symbol)}>
              <span className="sr-symbol">{s.symbol}</span>
              <span className="sr-name">{s.name}</span>
              <span className="sr-pct">{pct(s.short_pct_float)}</span>
            </li>
          ))}
        </ul>
      )}
      {open && searched && results.length === 0 && (
        <ul className="search-results">
          <li className="sr-empty">No matches for “{q.trim()}”.</li>
        </ul>
      )}
    </div>
  );
}
