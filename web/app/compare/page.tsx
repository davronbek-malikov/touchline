"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { RADAR_AXES, Radar, SERIES_COLOURS } from "@/components/Charts";
import PlayerPicker from "@/components/PlayerPicker";
import { CoverageBadge } from "@/components/PlayerTable";
import { api, EventProfile, euros, PlayerRow, shortDate } from "@/lib/api";

type Compared = PlayerRow & { event_profile: EventProfile | null };

function Compare() {
  const params = useSearchParams();
  const router = useRouter();
  const ids = (params.get("ids") || "").split(",").map(Number).filter(Boolean).slice(0, 4);
  const [players, setPlayers] = useState<Compared[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const setIds = (next: number[]) => router.replace(next.length ? `/compare?ids=${next.join(",")}` : "/compare", { scroll: false });

  useEffect(() => {
    if (ids.length < 2) { setPlayers([]); setNotes([]); return; }
    api.compare(ids).then((r) => { setPlayers(r.players); setNotes(r.notes); setError(null); }).catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const withEvents = players.filter((p) => p.event_profile);

  return (
    <div className="page">
      <h1>Compare players</h1>
      <p className="lede">Pick two to four players. The radar uses position-group percentiles from StatsBomb event data.</p>
      <div style={{ marginTop: 20 }}>
        <PlayerPicker label="Add a player" onPick={(p) => !ids.includes(p.player_id) && ids.length < 4 && setIds([...ids, p.player_id])} />
        {ids.length > 0 && (
          <ul className="chips">
            {ids.map((id, k) => (
              <li key={id}>
                <i style={{ background: SERIES_COLOURS[k] }} />
                {players.find((p) => p.player_id === id)?.name ?? `Player ${id}`}
                <button className="btn btn-quiet" aria-label="Remove" onClick={() => setIds(ids.filter((x) => x !== id))}>✕</button>
              </li>
            ))}
          </ul>
        )}
        {ids.length === 1 && <p className="hint">Add at least one more player.</p>}
      </div>
      {error && <p className="error">{error}</p>}
      {notes.map((n) => <p key={n} className="notice" style={{ marginTop: 16 }}>{n}</p>)}

      {players.length >= 2 && (
        <div className="compare-top" style={{ marginTop: 28 }}>
          <section>
            {withEvents.length ? (
              <Radar series={withEvents.map((p) => ({ name: p.name, metrics: p.event_profile!.metrics }))} />
            ) : <p className="hint">None of these players has event data, so there is no radar.</p>}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {withEvents.length > 0 && <p className="hint" style={{ textAlign: "center" }}><img src="/statsbomb-logo.png" alt="Data from StatsBomb" className="sb-logo" /></p>}
          </section>
          <section className="table-wrap">
            <table className="data">
              <thead>
                <tr><th />{players.map((p) => <th key={p.player_id}><Link href={`/players/${p.player_id}`}>{p.name}</Link></th>)}</tr>
              </thead>
              <tbody>
                <tr><td>Age</td>{players.map((p) => <td key={p.player_id}>{p.age ?? "–"}</td>)}</tr>
                <tr><td>Club</td>{players.map((p) => <td key={p.player_id}>{p.club_name ?? "–"}</td>)}</tr>
                <tr><td>Value</td>{players.map((p) => <td key={p.player_id}>{euros(p.market_value_eur)}</td>)}</tr>
                <tr><td>Contract</td>{players.map((p) => <td key={p.player_id}>{shortDate(p.contract_until)}</td>)}</tr>
                <tr><td>Event sample</td>{players.map((p) => <td key={p.player_id}>{p.event_profile ? `${p.event_profile.competition}, ${Math.round(p.event_profile.minutes)} min` : <CoverageBadge coverage="market only" />}</td>)}</tr>
                {RADAR_AXES.map(([key, label]) => (
                  <tr key={key}>
                    <td>{label}</td>
                    {players.map((p) => {
                      const pct = p.event_profile?.metrics[key]?.percentile;
                      return <td key={p.player_id}>{pct != null ? `${Math.round(pct)}th` : "–"}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  );
}

export default function ComparePage() {
  return <Suspense><Compare /></Suspense>;
}
