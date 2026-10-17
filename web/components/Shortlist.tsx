"use client";

import Link from "next/link";
import { useState } from "react";

import { Candidate, euros, POSITION_NAMES } from "@/lib/api";

/** The approval step: the agent stops here until the scout picks who gets a full report. */
export default function ShortlistApproval({ candidates, busy, onDecide }: {
  candidates: Candidate[];
  busy: boolean;
  onDecide: (approved: number[], comment: string | null) => void;
}) {
  const [picked, setPicked] = useState<Set<number>>(new Set(candidates.map((c) => c.player_id)));
  const [comment, setComment] = useState("");
  const toggle = (id: number) => setPicked((p) => {
    const next = new Set(p);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const n = picked.size;

  return (
    <section className="shortlist panel" aria-label="Approve the shortlist">
      <h3>Choose who gets a full report</h3>
      <p className="hint">Reports cite their sources. Untick anyone you don&apos;t want written up.</p>
      <ul className="shortlist-list">
        {candidates.map((c) => (
          <li key={c.player_id}>
            <label>
              <input type="checkbox" checked={picked.has(c.player_id)} onChange={() => toggle(c.player_id)} disabled={busy} />
              <span>
                <strong>{c.name}</strong>{" "}
                <span className="hint">
                  {[c.age != null ? `${c.age}` : null, c.position_group ? POSITION_NAMES[c.position_group] : null,
                    c.club_name, euros(c.market_value_eur)].filter(Boolean).join(", ")}
                </span>
                <span className="shortlist-reason">{c.reason}</span>
              </span>
            </label>
            <Link href={`/players/${c.player_id}`} className="hint" target="_blank">Profile</Link>
          </li>
        ))}
      </ul>
      <div className="field">
        <label htmlFor="sl-comment">Note for the agent (optional)</label>
        <input id="sl-comment" className="input" value={comment} onChange={(e) => setComment(e.target.value)}
               placeholder="e.g. focus on how they handle a high press" disabled={busy} />
      </div>
      <div className="shortlist-actions">
        <button className="btn btn-primary" disabled={busy || n === 0}
                onClick={() => onDecide([...picked], comment.trim() || null)}>
          {busy ? "Writing reports…" : `Write ${n} report${n === 1 ? "" : "s"}`}
        </button>
        <button className="btn btn-quiet" disabled={busy} onClick={() => onDecide([], comment.trim() || null)}>
          Skip reports
        </button>
      </div>
    </section>
  );
}
