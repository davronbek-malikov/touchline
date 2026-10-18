"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, Candidate, ChatSummary, shortDate } from "@/lib/api";

type Waiting = ChatSummary & { candidates: Candidate[] };
type Written = ChatSummary & { reports: { player_id: number; name: string }[] };

/** Your chats with a shortlist waiting for approval, and the players you've had reports written on. */
export default function ShortlistPage() {
  const [data, setData] = useState<{ waiting: Waiting[]; written: Written[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.shortlists().then(setData).catch((e) => setError(e.message)); }, []);

  return (
    <div className="page">
      <h1>Shortlists</h1>
      <p className="lede">Shortlists the assistant proposed in your chats, and the players you approved for reports.</p>
      {error && <p className="error" style={{ marginTop: 20 }}>{error}</p>}
      {!data && !error && <p className="hint">Loading…</p>}
      {data && !data.waiting.length && !data.written.length && (
        <p className="hint" style={{ marginTop: 20 }}>
          Nothing here yet. Ask the <Link href="/">Scout Assistant</Link> for scouting reports and it will propose a shortlist for you to approve.
        </p>
      )}
      {data && data.waiting.length > 0 && (
        <section style={{ marginTop: 28 }}>
          <h2>Waiting for your approval</h2>
          <ul className="note-list">
            {data.waiting.map((c) => (
              <li key={c.chat_id}>
                <Link href={`/?chat=${c.chat_id}`}><strong>{c.title}</strong></Link>
                <span className="hint"> {shortDate(c.updated_at)}</span>
                <p>{c.candidates.map((x) => x.name).join(", ")}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
      {data && data.written.length > 0 && (
        <section style={{ marginTop: 28 }}>
          <h2>Reports written</h2>
          <ul className="note-list">
            {data.written.map((c) => (
              <li key={c.chat_id}>
                <Link href={`/?chat=${c.chat_id}`}><strong>{c.title}</strong></Link>
                <span className="hint"> {shortDate(c.updated_at)}</span>
                <p>{c.reports.map((r) => (
                  <Link key={r.player_id} href={`/players/${r.player_id}`} style={{ marginRight: 12 }}>{r.name}</Link>
                ))}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
