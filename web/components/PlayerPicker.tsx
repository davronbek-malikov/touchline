"use client";

import { useEffect, useId, useRef, useState } from "react";

import { api, euros, PlayerRow } from "@/lib/api";

/** Type-ahead player search over /api/players/find. */
export default function PlayerPicker({ label, onPick, placeholder = "Type a player's name" }: {
  label: string;
  onPick: (p: PlayerRow) => void;
  placeholder?: string;
}) {
  const id = useId();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<PlayerRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    clearTimeout(timer.current);
    if (q.trim().length < 2) { setResults([]); return; }
    timer.current = setTimeout(() => {
      api.find(q.trim())
        .then((r) => { setResults(r.candidates); setActive(0); setError(null); })
        .catch((e) => setError(e.message));
    }, 220);
    return () => clearTimeout(timer.current);
  }, [q]);

  const pick = (p: PlayerRow) => { onPick(p); setQ(""); setResults([]); };

  return (
    <div className="picker field">
      <label htmlFor={id}>{label}</label>
      <input id={id} className="input" value={q} placeholder={placeholder} autoComplete="off"
             role="combobox" aria-expanded={results.length > 0} aria-controls={`${id}-list`}
             onChange={(e) => setQ(e.target.value)}
             onKeyDown={(e) => {
               if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
               if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
               if (e.key === "Enter" && results[active]) { e.preventDefault(); pick(results[active]); }
               if (e.key === "Escape") setResults([]);
             }} />
      {error && <p className="error">{error}</p>}
      {results.length > 0 && (
        <ul className="picker-list" id={`${id}-list`} role="listbox">
          {results.map((p, i) => (
            <li key={p.player_id} role="option" aria-selected={i === active}
                onMouseDown={(e) => { e.preventDefault(); pick(p); }} onMouseEnter={() => setActive(i)}>
              <strong>{p.name}</strong>
              <span className="hint">{[p.age, p.club_name, euros(p.market_value_eur)].filter((x) => x != null && x !== "–").join(", ")}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
