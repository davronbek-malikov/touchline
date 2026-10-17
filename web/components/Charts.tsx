"use client";

import { euros, Metric, shortDate } from "@/lib/api";

export const METRIC_GROUPS: { title: string; metrics: [string, string][] }[] = [
  { title: "Goal threat and creation", metrics: [["np_goals", "Non-penalty goals"], ["np_xg", "Non-penalty xG"], ["shots", "Shots"],
    ["xa", "Expected assists"], ["key_passes", "Key passes"], ["box_passes", "Passes into the box"]] },
  { title: "Progression", metrics: [["prog_passes", "Progressive passes"], ["prog_carries", "Progressive carries"],
    ["final_third_passes", "Passes into the final third"], ["dribbles_cmp", "Successful dribbles"]] },
  { title: "Defending", metrics: [["pressures", "Pressures"], ["tackles_interceptions", "Tackles + interceptions"],
    ["recoveries", "Ball recoveries"], ["aerial_win_pct", "Aerial duels won"], ["ground_duel_win_pct", "Ground duels won"]] },
  { title: "Security on the ball", metrics: [["pass_cmp_pct", "Pass completion"],
    ["pass_cmp_under_pressure_pct", "Pass completion under pressure"], ["dribble_success_pct", "Dribble success"]] },
];

function fmt(key: string, v: number | null): string {
  if (v == null) return "–";
  return key.endsWith("_pct") ? `${v.toFixed(0)}%` : v.toFixed(2);
}

/** Percentile bars. The tick at 50 is the position-group median, like the halfway line. */
export function PercentileBars({ metrics }: { metrics: Record<string, Metric> }) {
  return (
    <div className="pbars">
      {METRIC_GROUPS.map((g) => (
        <section key={g.title}>
          <h3>{g.title}</h3>
          <dl>
            {g.metrics.map(([key, label]) => {
              const m = metrics[key];
              const pct = m?.percentile;
              return (
                <div key={key} className="pbar" title={m?.description}>
                  <dt>{label}</dt>
                  <dd>
                    <span className="pbar-track" role="img"
                          aria-label={pct == null ? `${label}: not enough data` : `${label}: ${Math.round(pct)}th percentile`}>
                      {pct != null && <span className="pbar-fill" style={{ width: `${pct}%` }} />}
                      <span className="pbar-mid" />
                    </span>
                    <span className="pbar-num">{pct == null ? "n/a" : `${Math.round(pct)}`}</span>
                    <span className="pbar-raw">{fmt(key, m?.value ?? null)}</span>
                  </dd>
                </div>
              );
            })}
          </dl>
        </section>
      ))}
    </div>
  );
}

/** Market value over time as a step line (Transfermarkt revalues in steps). */
export function ValueChart({ points }: { points: { date: string; market_value_eur: number }[] }) {
  if (points.length < 2) return <p className="hint">Not enough valuations to chart.</p>;
  const W = 420, H = 200, P = { l: 52, r: 12, t: 12, b: 26 };
  const t = points.map((p) => new Date(p.date).getTime());
  const v = points.map((p) => p.market_value_eur);
  const t0 = Math.min(...t), t1 = Math.max(...t), vmax = Math.max(...v) * 1.1 || 1;
  const x = (ti: number) => P.l + ((ti - t0) / (t1 - t0 || 1)) * (W - P.l - P.r);
  const y = (vi: number) => H - P.b - (vi / vmax) * (H - P.t - P.b);
  let d = `M${x(t[0])},${y(v[0])}`;
  for (let i = 1; i < points.length; i++) d += ` H${x(t[i])} V${y(v[i])}`;
  const ticks = [0, vmax / 2, vmax].map((tv) => ({ tv, yv: y(tv) }));
  return (
    <figure className="vchart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`Market value from ${euros(v[0])} on ${shortDate(points[0].date)} to ${euros(v.at(-1))} on ${shortDate(points.at(-1)!.date)}`}>
        {ticks.map(({ tv, yv }) => (
          <g key={tv}>
            <line x1={P.l} x2={W - P.r} y1={yv} y2={yv} className="vchart-grid" />
            <text x={P.l - 8} y={yv + 4} textAnchor="end" className="vchart-label">{euros(Math.round(tv / 1e5) * 1e5)}</text>
          </g>
        ))}
        <path d={d} className="vchart-line" />
        {points.map((p, i) => <circle key={i} cx={x(t[i])} cy={y(v[i])} r={3} className="vchart-dot"><title>{`${shortDate(p.date)}: ${euros(p.market_value_eur)}`}</title></circle>)}
        <text x={P.l} y={H - 6} className="vchart-label">{shortDate(points[0].date)}</text>
        <text x={W - P.r} y={H - 6} textAnchor="end" className="vchart-label">{shortDate(points.at(-1)!.date)}</text>
      </svg>
    </figure>
  );
}

export const RADAR_AXES: [string, string][] = [
  ["np_xg", "xG"], ["xa", "xA"], ["key_passes", "Key passes"], ["prog_passes", "Prog. passes"],
  ["prog_carries", "Prog. carries"], ["dribbles_cmp", "Dribbles"], ["pressures", "Pressures"],
  ["tackles_interceptions", "Tackles + int."], ["aerial_win_pct", "Aerials won"], ["pass_cmp_under_pressure_pct", "Passing under pressure"],
];
export const SERIES_COLOURS = ["#2f6fde", "#c2410c", "#0f766e", "#7c3aed"];

/** Percentile radar for 2-4 players. Missing values sit at the centre and are listed below. */
export function Radar({ series }: { series: { name: string; metrics: Record<string, Metric> }[] }) {
  const S = 360, C = S / 2, R = 128;
  const angle = (i: number) => (Math.PI * 2 * i) / RADAR_AXES.length - Math.PI / 2;
  const pt = (i: number, pct: number) => [C + Math.cos(angle(i)) * (R * pct) / 100, C + Math.sin(angle(i)) * (R * pct) / 100];
  return (
    <figure className="radar">
      <svg viewBox={`0 0 ${S} ${S}`} role="img" aria-label={`Percentile radar comparing ${series.map((s) => s.name).join(", ")}`}>
        {[25, 50, 75, 100].map((r) => (
          <polygon key={r} className={r === 50 ? "radar-ring radar-mid" : "radar-ring"}
                   points={RADAR_AXES.map((_, i) => pt(i, r).join(",")).join(" ")} />
        ))}
        {RADAR_AXES.map(([, label], i) => {
          const [lx, ly] = pt(i, 118);
          return (
            <g key={label}>
              <line x1={C} y1={C} x2={pt(i, 100)[0]} y2={pt(i, 100)[1]} className="radar-spoke" />
              <text x={lx} y={ly} textAnchor={Math.abs(lx - C) < 8 ? "middle" : lx > C ? "start" : "end"}
                    dominantBaseline="middle" className="radar-label">{label}</text>
            </g>
          );
        })}
        {series.map((s, k) => (
          <polygon key={s.name} className="radar-shape" style={{ stroke: SERIES_COLOURS[k], fill: SERIES_COLOURS[k] }}
                   points={RADAR_AXES.map(([key], i) => pt(i, s.metrics[key]?.percentile ?? 0).join(",")).join(" ")} />
        ))}
      </svg>
      <figcaption className="radar-legend">
        {series.map((s, k) => (
          <span key={s.name}><i style={{ background: SERIES_COLOURS[k] }} />{s.name}</span>
        ))}
      </figcaption>
    </figure>
  );
}
