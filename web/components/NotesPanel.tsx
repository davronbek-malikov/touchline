"use client";

import { FormEvent, useEffect, useState } from "react";

import { api, Note, shortDate } from "@/lib/api";

const AUTHOR_KEY = "touchline.author";

/** A player's notes, and a form to add one. Saved notes are searchable by the agent straight away. */
export default function NotesPanel({ playerId, playerName }: { playerId: number; playerName: string }) {
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [text, setText] = useState("");
  const [context, setContext] = useState("");
  const [author, setAuthor] = useState("");
  const [status, setStatus] = useState<{ kind: "error" | "ok"; msg: string } | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    try { setAuthor(localStorage.getItem(AUTHOR_KEY) || ""); } catch { /* storage unavailable */ }
  }, []);
  useEffect(() => {
    api.notes(playerId).then((r) => setNotes(r.notes)).catch((e) => setStatus({ kind: "error", msg: e.message }));
  }, [playerId]);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setStatus(null);
    try {
      const note = await api.addNote({ player_id: playerId, text: text.trim(), author: author.trim() || "scout", context: context.trim() || undefined });
      setNotes((n) => [...(n ?? []), note]);
      setText("");
      setContext("");
      try { localStorage.setItem(AUTHOR_KEY, author.trim()); } catch { /* storage unavailable */ }
      setStatus({ kind: "ok", msg: "Note saved. The agent can search it now." });
    } catch (err) {
      setStatus({ kind: "error", msg: (err as Error).message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      {notes === null ? <p className="hint">Loading notes…</p> : notes.length === 0 ? (
        <p className="hint">No notes on {playerName} yet. What you write here feeds the agent&apos;s reports, with a citation.</p>
      ) : (
        <ul className="note-list">
          {notes.map((n) => (
            <li key={n.note_id}>
              <span className="hint">{n.author}, {shortDate(n.created_at)}{n.context ? `, ${n.context}` : ""}</span>
              <p>{n.text}</p>
            </li>
          ))}
        </ul>
      )}
      <form className="note-form" onSubmit={save}>
        <div className="field">
          <label htmlFor={`note-${playerId}`}>New note</label>
          <textarea id={`note-${playerId}`} className="input" rows={3} value={text} onChange={(e) => setText(e.target.value)}
                    placeholder="What did you see? e.g. great first touch, slow on the turn, scans before receiving" required minLength={3} />
        </div>
        <div className="row">
          <div className="field">
            <label htmlFor={`ctx-${playerId}`}>Match or context (optional)</label>
            <input id={`ctx-${playerId}`} className="input" value={context} onChange={(e) => setContext(e.target.value)} placeholder="vs Real Madrid, 12 Oct" />
          </div>
          <div className="field">
            <label htmlFor={`by-${playerId}`}>Your name</label>
            <input id={`by-${playerId}`} className="input" value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="scout" />
          </div>
        </div>
        <div><button className="btn btn-primary" disabled={saving || text.trim().length < 3}>{saving ? "Saving…" : "Save note"}</button></div>
        {status && <p className={status.kind === "error" ? "error" : "hint"} role="status">{status.msg}</p>}
      </form>
    </div>
  );
}
