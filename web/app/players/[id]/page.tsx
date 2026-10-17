"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";

import { PercentileBars, ValueChart } from "@/components/Charts";
import NotesPanel from "@/components/NotesPanel";
import PlayerTable, { CoverageBadge } from "@/components/PlayerTable";
import { api, euros, PlayerRow, POSITION_NAMES, Profile, shortDate } from "@/lib/api";

export default function PlayerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const playerId = Number(id);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [similar, setSimilar] = useState<{ players: PlayerRow[]; notes: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setProfile(null);
    setError(null);
    api.profile(playerId).then(setProfile).catch((e) => setError(e.message));
    api.similar(playerId).then(setSimilar).catch(() => setSimilar(null));
  }, [playerId]);

  if (error) return <div className="page"><p className="error">{error}</p><Link href="/">Back to search</Link></div>;
  if (!profile) return <div className="page"><p className="hint">Loading player…</p></div>;

  const p = profile.player;
  const ev = profile.event_profile;
  const facts: [string, string][] = [
    ["Age", p.age != null ? `${p.age}` : "–"],
    ["Position", p.sub_position || (p.position_group ? POSITION_NAMES[p.position_group] : "–")],
    ["Club", p.club_name || "–"],
    ["League", p.league || "–"],
    ["Market value", euros(p.market_value_eur)],
    ["Peak value", euros(p.highest_market_value_eur)],
    ["Contract until", shortDate(p.contract_until)],
    ["Foot", p.foot ? p.foot[0].toUpperCase() + p.foot.slice(1) : "–"],
    ["Height", p.height_in_cm ? `${p.height_in_cm} cm` : "–"],
    ["Nationality", p.nationality || "–"],
    ["Caps", p.international_caps != null ? `${p.international_caps}` : "–"],
    ["Minutes 2025/26", p.minutes_2025_26?.toLocaleString("en-GB") ?? "–"],
  ];

  return (
    <div className="page">
      <header className="dossier-head">
        <div>
          <h1>{p.name}</h1>
          <p className="hint">Data as of {shortDate(profile.data_as_of)}. <CoverageBadge coverage={p.coverage} /></p>
        </div>
        <Link className="btn btn-primary" href={`/?q=${encodeURIComponent(`Write a scouting report on ${p.name}`)}`}>
          Write a scouting report
        </Link>
      </header>
      <dl className="facts">
        {facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
      </dl>

      <div className="dossier-grid" style={{ marginTop: 36 }}>
        <section>
          <h2>Event profile</h2>
          {ev ? (
            <>
              <div className="event-caption">
                <span className="hint">
                  {ev.competition}: {Math.round(ev.minutes)} minutes in {ev.matches} matches. Percentiles compare {POSITION_NAMES[ev.position_group]?.toLowerCase() ?? "players"}s in the event data; the tick marks the median.
                </span>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/statsbomb-logo.png" alt="Data from StatsBomb" className="sb-logo" />
              </div>
              <PercentileBars metrics={ev.metrics} />
            </>
          ) : (
            <p className="hint">
              No StatsBomb event data for this player, so there are no per-90 metrics or percentiles. Market data and notes still apply.
            </p>
          )}
        </section>
        <section className="stack">
          <div>
            <h2>Market value</h2>
            <ValueChart points={profile.market_value_history} />
          </div>
          <div>
            <h2>Recent seasons</h2>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Season</th><th className="num">Apps</th><th className="num">Mins</th><th className="num">Goals</th><th className="num">Assists</th></tr></thead>
                <tbody>
                  {profile.seasons.map((s) => (
                    <tr key={s.season}><td>{s.season}</td><td className="num">{s.appearances}</td><td className="num">{s.minutes.toLocaleString("en-GB")}</td><td className="num">{s.goals}</td><td className="num">{s.assists}</td></tr>
                  ))}
                  {!profile.seasons.length && <tr><td colSpan={5} className="hint">No recent appearances recorded.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </div>

      <section style={{ marginTop: 40 }}>
        <h2>Similar players</h2>
        {similar?.players.length ? (
          <>
            <p className="hint">Closest event profiles in the same position group.</p>
            <PlayerTable rows={similar.players} />
          </>
        ) : (
          <p className="hint">{similar?.notes[0] ?? "Similarity needs StatsBomb event data."}</p>
        )}
      </section>

      <section style={{ marginTop: 40 }}>
        <h2>Scout notes</h2>
        <NotesPanel playerId={playerId} playerName={p.name} />
      </section>
    </div>
  );
}
