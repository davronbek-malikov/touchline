"use client";

import { useEffect, useState } from "react";

import { api, Meta } from "@/lib/api";

const METRIC_COLUMNS: [string, string][] = [
  ["filter_accuracy", "Filter acc."], ["precision@10", "P@10"], ["numeric_grounding", "Numeric grounding"],
  ["hallucinated_players", "Invented players"], ["citation_coverage", "Citations"], ["latency_p50", "p50 latency (s)"],
  ["cost_usd", "$/query"],
];

export default function AboutPage() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [results, setResults] = useState<Record<string, unknown>[] | null>(null);
  useEffect(() => {
    api.meta().then(setMeta).catch(() => undefined);
    api.evalSummary().then((r) => setResults(r.results)).catch(() => setResults([]));
  }, []);

  return (
    <div className="page about">
      <h1>How Touchline works</h1>
      <p className="lede">
        Touchline is a scouting copilot. You describe a player in plain words; an agent built on Claude searches a player
        database with typed tools, then explains its picks. It never writes database queries itself, so every number it
        quotes comes from a tool result, and every claim about playing style cites the passage it came from.
      </p>

      <section>
        <h2>What happens when you search</h2>
        <ol className="flow">
          <li><span>Claude ({meta?.model ?? "claude-opus-5-5"}) reads your brief and turns scout language into filters, using a glossary that maps terms like &ldquo;ball-playing&rdquo; to specific metrics.</span></li>
          <li><span>It calls typed tools: player search, profiles, similar players, comparisons and note search. Python validates every call and runs the query.</span></li>
          <li><span>When you ask for reports, it proposes a shortlist and waits for you to approve names.</span></li>
          <li><span>Each approved player gets a report written from their data and the matching notes and Wikipedia passages, with citations.</span></li>
          <li><span>Every run is traced in LangSmith and scored against a fixed test set of 120 scouting questions.</span></li>
        </ol>
      </section>

      <section>
        <h2>The data</h2>
        <div className="credits">
          <div className="credit">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/statsbomb-logo.png" alt="StatsBomb" style={{ width: 150, height: "auto" }} />
            <div>
              <strong>StatsBomb open data</strong> provides event data (every pass, carry, shot and duel) for Euro 2024, Copa América 2024,
              World Cup 2022, AFCON 2023, MLS 2023 and selected Bundesliga and Ligue 1 seasons. Touchline turns it into per-90 metrics
              and position-group percentiles for {meta?.event_players ?? "about 600"} players with at least 270 minutes.
              Data © StatsBomb, used under the <a href="https://github.com/statsbomb/open-data" target="_blank" rel="noreferrer">StatsBomb open data licence</a>.
            </div>
          </div>
          <div className="credit">
            <strong>Transfermarkt</strong>
            <div>
              Market data for {meta?.active_players?.toLocaleString("en-GB") ?? "about 22,000"} active players (age, position, club, contract,
              market value and its history, minutes, goals, assists), via the <a href="https://github.com/dcaribou/transfermarkt-datasets" target="_blank" rel="noreferrer">transfermarkt-datasets</a> project.
              The data originates from Transfermarkt and is current to 6 July 2026; updates upstream are paused. Market values are
              Transfermarkt estimates, not transfer fees. Non-commercial use.
            </div>
          </div>
          <div className="credit">
            <strong>Wikipedia</strong>
            <div>
              &ldquo;Style of play&rdquo; sections for well-known players, under <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noreferrer">CC BY-SA 4.0</a>.
              Reports link each cited passage back to its article.
            </div>
          </div>
          <div className="credit">
            <strong>Scout notes</strong>
            <div>Observations written in this app. They&apos;re searchable straight away and cited in reports like any other source.</div>
          </div>
        </div>
        <p className="hint" style={{ marginTop: 14 }}>
          Coverage is uneven, and the app says so: each result is marked <em>market only</em> or <em>market + events</em>,
          and style filters only match players with event data.
        </p>
      </section>

      <section>
        <h2>Evaluation</h2>
        <p>
          A fixed set of 120 questions (filter searches, similar-player requests, facts, reports and trick questions) is scored
          automatically: did the agent choose the right filters, return the right players, use only numbers from the database,
          and avoid naming players who don&apos;t exist?
        </p>
        {results === null ? <p className="hint">Loading results…</p> : results.length === 0 ? (
          <p className="hint">No experiment has been run on this deployment yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Experiment</th>{METRIC_COLUMNS.map(([, l]) => <th key={l} className="num">{l}</th>)}</tr></thead>
              <tbody>
                {results.map((r) => (
                  <tr key={String(r.label)}>
                    <td>{String(r.label)}</td>
                    {METRIC_COLUMNS.map(([k]) => <td key={k} className="num">{r[k] != null ? String(r[k]) : "–"}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
