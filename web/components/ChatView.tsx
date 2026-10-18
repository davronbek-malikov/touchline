"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { useChats } from "@/components/ChatsProvider";
import Composer from "@/components/Composer";
import PlayerTable from "@/components/PlayerTable";
import ReportView, { reportPlainText } from "@/components/ReportView";
import ShortlistApproval from "@/components/Shortlist";
import StepLog from "@/components/StepLog";
import { AgentEvent, api, Candidate, Meta, ModelOption, streamAgent, TurnData } from "@/lib/api";

interface UITurn extends TurnData {
  pending?: Candidate[] | null;
  runId?: string;
  rated?: 0 | 1;
  error?: string;
  live?: boolean;
}

const MODEL_KEY = "touchline.model";

// Shown when the server can't be reached, so the picker isn't empty.
const OFFLINE_MODELS: ModelOption[] = [
  ["claude-opus-5-5", "Claude Opus 5.5"], ["claude-sonnet-5-5", "Claude Sonnet 5.5"], ["claude-haiku-5-5", "Claude Haiku 5.5"],
].map(([id, label]) => ({ id, label, provider: "anthropic", available: false, note: "", reason: "Server unavailable" }));

function plain(md: string): string {
  return md.replace(/```[\s\S]*?```/g, "").replace(/[#*_`>|]/g, "").replace(/\[(.*?)\]\(.*?\)/g, "$1")
    .replace(/-{3,}/g, "").replace(/\n{2,}/g, "\n");
}

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button className="act" onClick={() => {
      navigator.clipboard.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); })
        .catch(() => undefined);
    }}>{done ? "Copied" : label}</button>
  );
}

function ReadAloud({ text }: { text: string }) {
  const [speaking, setSpeaking] = useState(false);
  const supported = typeof window !== "undefined" && "speechSynthesis" in window;
  useEffect(() => () => { if (speaking) window.speechSynthesis.cancel(); }, [speaking]);
  if (!supported) return null;
  return (
    <button className="act" aria-pressed={speaking} onClick={() => {
      if (speaking) { window.speechSynthesis.cancel(); setSpeaking(false); return; }
      const u = new SpeechSynthesisUtterance(plain(text));
      u.lang = "en-GB";
      u.onend = () => setSpeaking(false);
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
      setSpeaking(true);
    }}>{speaking ? "Stop reading" : "Read aloud"}</button>
  );
}

export default function ChatView() {
  const params = useSearchParams();
  const router = useRouter();
  const { refresh } = useChats();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [model, setModel] = useState("claude-opus-5-5");
  const [chatId, setChatId] = useState<string | null>(params.get("chat"));
  const [turns, setTurns] = useState<UITurn[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [editing, setEditing] = useState<{ turn: number; text: string } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const ownChat = useRef<string | null>(params.get("chat"));
  const bottom = useRef<HTMLDivElement>(null);

  // Server facts and the model list.
  useEffect(() => {
    api.meta().then(setMeta).catch((e) => setConnectError(e.message));
    api.models().then((r) => {
      setModels(r.models);
      let saved: string | null = null;
      try { saved = localStorage.getItem(MODEL_KEY); } catch { /* storage unavailable */ }
      const usable = r.models.filter((m) => m.available);
      const pick = [saved, r.default].find((id) => id && usable.some((m) => m.id === id)) ?? usable[0]?.id ?? r.default;
      setModel(pick);
    }).catch(() => setModels(OFFLINE_MODELS));
  }, []);

  // Load a chat when the URL points at one we didn't just create here.
  useEffect(() => {
    const id = params.get("chat");
    if (id === ownChat.current && turns.length) return;
    ownChat.current = id;
    setChatId(id);
    setEditing(null);
    setLoadError(null);
    if (!id) { setTurns([]); return; }
    api.chat(id).then((c) => {
      const t: UITurn[] = c.turns;
      if (c.pending && t.length) t[t.length - 1].pending = c.pending.candidates;
      setTurns(t);
      if (c.model && models.some((m) => m.id === c.model && m.available)) setModel(c.model);
    }).catch((e) => setLoadError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns.length, running]);

  const chooseModel = (id: string) => {
    setModel(id);
    try { localStorage.setItem(MODEL_KEY, id); } catch { /* storage unavailable */ }
  };

  const updateLast = useCallback((fn: (t: UITurn) => UITurn) => {
    setTurns((ts) => (ts.length ? [...ts.slice(0, -1), fn(ts[ts.length - 1])] : ts));
  }, []);

  const onEvent = useCallback((e: AgentEvent) => {
    switch (e.event) {
      case "meta":
        if (!ownChat.current) {
          ownChat.current = e.data.chat_id;
          setChatId(e.data.chat_id);
          router.replace(`/?chat=${e.data.chat_id}`, { scroll: false });
        }
        updateLast((t) => ({ ...t, runId: e.data.run_id }));
        refresh();
        break;
      case "step":
        updateLast((t) => ({ ...t, steps: [...t.steps, { ...e.data }] }));
        break;
      case "result":
        updateLast((t) => ({
          ...t,
          steps: t.steps.map((s) => (s.id === e.data.id ? { ...s, done: true, summary: e.data.summary, is_error: e.data.is_error } : s)),
          table: e.data.data?.length ? { name: e.data.name, rows: e.data.data } : t.table,
        }));
        break;
      case "shortlist":
        updateLast((t) => ({
          ...t, pending: e.data.candidates,
          steps: t.steps.map((s) => (s.name === "propose_shortlist" && !s.done ? { ...s, done: true, summary: "Waiting for your approval" } : s)),
        }));
        break;
      case "report":
        updateLast((t) => ({ ...t, reports: [...t.reports.filter((r) => r.player_id !== e.data.player_id), e.data] }));
        break;
      case "answer":
        updateLast((t) => ({ ...t, answer: e.data.text }));
        break;
      case "error":
        updateLast((t) => ({ ...t, error: e.data.message }));
        break;
    }
  }, [updateLast, refresh, router]);

  const run = useCallback(async (path: string, body: unknown) => {
    const ctrl = new AbortController();
    abort.current = ctrl;
    setRunning(true);
    try {
      await streamAgent(path, body, onEvent, ctrl.signal);
    } catch (err) {
      updateLast((t) => ({ ...t, error: (err as Error).message }));
    } finally {
      setRunning(false);
      updateLast((t) => ({ ...t, live: false }));
      abort.current = null;
    }
  }, [onEvent, updateLast]);

  const send = (text: string, fileIds: string[], editTurn?: number) => {
    const fresh: UITurn = { turn: editTurn ?? turns.length, text, attachments: fileIds.length ? [`${fileIds.length} file(s)`] : [],
      steps: [], table: null, answer: null, reports: [], live: true };
    setTurns((ts) => (editTurn == null ? [...ts, fresh] : [...ts.slice(0, editTurn), fresh]));
    setEditing(null);
    run("/api/chat", { message: text, chat_id: chatId, model, file_ids: fileIds, edit_turn: editTurn ?? null });
  };

  const decide = (approved: number[], comment: string | null) => {
    if (!chatId) return;
    updateLast((t) => ({ ...t, pending: null, live: true }));
    run("/api/chat/resume", { chat_id: chatId, approved, comment });
  };

  const usable = models.some((m) => m.available);
  const pending = turns.at(-1)?.pending;
  const disabledReason = connectError
    ?? (models.length && !usable ? "No model is available on this server: it needs an Anthropic API key or a running Ollama." : null)
    ?? (pending ? "Approve or skip the shortlist above to continue." : null);
  const composer = (
    <Composer busy={running} disabled={!!disabledReason} disabledReason={disabledReason} models={models} model={model}
              onModel={chooseModel} onSend={(t, f) => send(t, f)} onStop={() => abort.current?.abort()}
              placeholder={turns.length ? "Ask a follow-up, attach a file, or ask for reports" : "Describe the player you need"} />
  );

  if (!turns.length && !loadError) {
    return (
      <div className="chat-empty">
        <h1>What player do you need?</h1>
        <p className="lede">
          Describe the role, age, budget, contract and style. The Scout Assistant searches {meta ? meta.active_players.toLocaleString("en-GB") : "about 22,000"} active
          players, explains every pick with database numbers and cited sources, and reads the files you attach.
        </p>
        {composer}
        {meta && (
          <ul className="examples" aria-label="Example questions">
            {meta.examples.map((ex) => (
              <li key={ex}><button className="example" disabled={!!disabledReason || running} onClick={() => send(ex, [])}>{ex}</button></li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const last = turns.length - 1;
  return (
    <div className="chat">
      <div className="chat-scroll">
        {loadError && <p className="error">{loadError}</p>}
        {turns.map((t, i) => (
          <section key={`${t.turn}-${i}`} className="turn-pair">
            <div className="msg msg-user">
              {editing?.turn === i ? (
                <div className="edit-box">
                  <label htmlFor={`edit-${i}`} className="sr-only">Edit your message</label>
                  <textarea id={`edit-${i}`} className="input" rows={3} value={editing.text} autoFocus
                            onChange={(e) => setEditing({ turn: i, text: e.target.value })} />
                  <div className="edit-actions">
                    <button className="btn btn-quiet" onClick={() => setEditing(null)}>Cancel</button>
                    <button className="btn btn-primary" disabled={!editing.text.trim() || running}
                            onClick={() => send(editing.text.trim(), [], i)}>Save and resend</button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="bubble">
                    {t.attachments.length > 0 && (
                      <ul className="bubble-atts">{t.attachments.map((a) => <li key={a}>{a}</li>)}</ul>
                    )}
                    <p>{t.text}</p>
                  </div>
                  <div className="acts acts-user">
                    <CopyButton text={t.text} />
                    {!running && t.attachments.length === 0 && (
                      <button className="act" onClick={() => setEditing({ turn: i, text: t.text })}>Edit</button>
                    )}
                  </div>
                </>
              )}
            </div>

            <div className="msg msg-assistant">
              {t.steps.length > 0 && (
                <details className="tools-used" open={t.live}>
                  <summary>{t.live && running && i === last ? "Working…" : `Used ${t.steps.length} tool${t.steps.length === 1 ? "" : "s"}`}</summary>
                  <StepLog steps={t.steps} running={!!t.live && running && i === last} />
                </details>
              )}
              {t.live && running && i === last && t.steps.length === 0 && <p className="thinking">Thinking…</p>}
              {t.pending && <ShortlistApproval candidates={t.pending} busy={running} onDecide={decide} />}
              {t.reports.map((r) => <ReportView key={r.player_id} report={r} />)}
              {t.answer && (
                <div className="answer prose"><ReactMarkdown remarkPlugins={[remarkGfm]}>{t.answer}</ReactMarkdown></div>
              )}
              {t.table && (
                <details className="turn-table">
                  <summary>{t.table.name === "similar_players" ? "Similar players" : "Search results"} ({t.table.rows.length} shown)</summary>
                  <PlayerTable rows={t.table.rows} />
                </details>
              )}
              {t.error && <p className="error">{t.error}</p>}
              {(t.answer || t.reports.length > 0) && !(t.live && running) && (
                <div className="acts">
                  <CopyButton text={[t.answer ?? "", ...t.reports.map(reportPlainText)].filter(Boolean).join("\n\n")} />
                  {t.answer && <ReadAloud text={t.answer} />}
                  {i === last && !running && t.attachments.length === 0 && (
                    <button className="act" onClick={() => send(t.text, [], i)}>Regenerate</button>
                  )}
                  {t.runId && (t.rated == null ? (["Yes", "No"] as const).map((l) => (
                    <button key={l} className="act" aria-label={l === "Yes" ? "Helpful" : "Not helpful"} onClick={() => {
                      const score = l === "Yes" ? 1 : 0;
                      api.feedback(t.runId!, score).catch(() => undefined);
                      setTurns((ts) => ts.map((x, j) => (j === i ? { ...x, rated: score } : x)));
                    }}>{l === "Yes" ? "👍" : "👎"}</button>
                  )) : <span className="hint">Thanks for the feedback.</span>)}
                </div>
              )}
            </div>
          </section>
        ))}
        <div ref={bottom} />
      </div>
      <div className="chat-composer">{composer}</div>
    </div>
  );
}
