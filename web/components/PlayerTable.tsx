"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { euros, PlayerRow, shortDate } from "@/lib/api";

export function CoverageBadge({ coverage }: { coverage?: string }) {
  if (!coverage) return null;
  const events = coverage === "market + events";
  return (
    <span className={`badge ${events ? "badge-events" : ""}`}
          title={events ? "Has StatsBomb event data: per-90 metrics and percentiles"
                        : "Transfermarkt market data only; no event metrics"}>
      {events ? "market + events" : "market only"}
    </span>
  );
}

const BASE_KEYS = new Set(["player_id", "name", "age", "position_group", "sub_position", "foot", "height_in_cm",
  "nationality", "club_name", "league_id", "market_value_eur", "contract_until", "minutes_2025_26", "coverage",
  "event_competition", "event_minutes", "similarity", "shared_traits", "is_active", "match_score"]);

type SortKey = "name" | "age" | "market_value_eur" | "contract_until" | "minutes_2025_26" | "similarity" | string;

/** Results table: base columns plus any metric columns the search asked for (value + percentile). */
export default function PlayerTable({ rows, caption }: { rows: PlayerRow[]; caption?: string }) {
  const metrics = useMemo(() => {
    const keys = new Set<string>();
    rows.forEach((r) => Object.keys(r).forEach((k) => {
      if (!BASE_KEYS.has(k) && !k.endsWith("_pct") && typeof r[k] === "number") keys.add(k);
    }));
    return [...keys];
  }, [rows]);
  const hasSimilarity = rows.some((r) => r.similarity != null);
  const hasContract = rows.some((r) => r.contract_until != null);
  const hasMinutes = rows.some((r) => r.minutes_2025_26 != null);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 } | null>(null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    return [...rows].sort((a, b) => {
      const x = a[sort.key] as number | string | null | undefined;
      const y = b[sort.key] as number | string | null | undefined;
      if (x == null) return 1;
      if (y == null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
    });
  }, [rows, sort]);

  const header = (key: SortKey, label: string, num = false) => {
    const dir = sort?.key === key ? sort.dir : 0;
    return (
      <th className={num ? "num" : undefined} aria-sort={dir === 1 ? "ascending" : dir === -1 ? "descending" : "none"}>
        <button onClick={() => setSort({ key, dir: dir === -1 ? 1 : -1 })}>
          {label}{dir === 1 ? " ▲" : dir === -1 ? " ▼" : ""}
        </button>
      </th>
    );
  };

  return (
    <div className="table-wrap">
      <table className="data">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {header("name", "Player")}
            {header("age", "Age", true)}
            <th>Club</th>
            {header("market_value_eur", "Value", true)}
            {hasContract && header("contract_until", "Contract")}
            {hasMinutes && header("minutes_2025_26", "Mins 25/26", true)}
            {hasSimilarity && header("similarity", "Similarity", true)}
            {metrics.map((m) => header(`${m}_pct`, m.replaceAll("_", " "), true))}
            <th>Data</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.player_id}>
              <td>
                <Link href={`/players/${r.player_id}`}>{r.name}</Link>
                {r.shared_traits && r.shared_traits.length > 0 && (
                  <div className="hint">Shares: {r.shared_traits.slice(0, 2).join("; ")}</div>
                )}
              </td>
              <td className="num">{r.age ?? "–"}</td>
              <td>{r.club_name ?? "–"}</td>
              <td className="num">{euros(r.market_value_eur)}</td>
              {hasContract && <td>{shortDate(r.contract_until)}</td>}
              {hasMinutes && <td className="num">{r.minutes_2025_26?.toLocaleString("en-GB") ?? "–"}</td>}
              {hasSimilarity && <td className="num">{r.similarity != null ? r.similarity.toFixed(2) : "–"}</td>}
              {metrics.map((m) => (
                <td key={m} className="num" title={`${r[m] ?? "–"} per 90 / rate`}>
                  {r[`${m}_pct`] != null ? `${Math.round(r[`${m}_pct`] as number)}th` : "–"}
                </td>
              ))}
              <td><CoverageBadge coverage={r.coverage ?? (r.similarity != null ? "market + events" : undefined)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
