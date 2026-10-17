"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, Candidate, recentThreads, Report, shortDate } from "@/lib/api";

interface Row {
  id: string;
  title: string;
  at: string;
  pending: Candidate[] | null;
  reports: Report[];
}

/** Searches started in this browser: shortlists waiting for approval and reports already written. */
export default function ShortlistPage() {
  const [rows, setRows] = useState<Row[] | null>(null);

  useEffect(() => {
    const threads = recentThreads();
    Promise.all(threads.map((t) => api.thread(t.id)
      .then((r) => ({ ...t, pending: r.pending?.candidates ?? null, reports: r.reports }))
      .catch(() => ({ ...t, pending: null, reports: [] }))))
      .then(setRows);
  }, []);

  const waiting = rows?.filter((r) => r.pending) ?? [];
  const done = rows?.filter((r) => !r.pending && r.reports.length) ?? [];

  return (
    <div className="page">
      <h1>Shortlists</h1>
      <p className="lede">Shortlists the agent proposed in this browser, and the players you approved for reports.</p>
      {rows === null && <p className="hint">Loading…</p>}
      {rows?.length === 0 && (
        <p className="hint" style={{ marginTop: 20 }}>
          Nothing here yet. Ask for scouting reports on the <Link href="/">search page</Link> and the agent will propose a shortlist for you to approve.
        </p>
      )}
      {waiting.length > 0 && (
        <section style={{ marginTop: 28 }}>
          <h2>Waiting for your approval</h2>
          <ul className="note-list">
            {waiting.map((r) => (
              <li key={r.id}>
                <Link href={`/?thread=${r.id}`}><strong>{r.title}</strong></Link>
                <span className="hint"> started {shortDate(r.at)}</span>
                <p>{r.pending!.map((c) => c.name).join(", ")}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
      {done.length > 0 && (
        <section style={{ marginTop: 28 }}>
          <h2>Reports written</h2>
          <ul className="note-list">
            {done.map((r) => (
              <li key={r.id}>
                <Link href={`/?thread=${r.id}`}><strong>{r.title}</strong></Link>
                <span className="hint"> {shortDate(r.at)}</span>
                <p>{r.reports.map((rep) => (
                  <Link key={rep.player_id} href={`/players/${rep.player_id}`} style={{ marginRight: 12 }}>{rep.name}</Link>
                ))}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
