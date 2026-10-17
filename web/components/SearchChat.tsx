"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import PlayerTable from "@/components/PlayerTable";
import ReportView from "@/components/ReportView";
import ShortlistApproval from "@/components/Shortlist";
import StepLog, { Step } from "@/components/StepLog";
import { AgentEvent, api, Candidate, Meta, PlayerRow, rememberThread, Report, streamAgent } from "@/lib/api";

interface Turn {
  question: string;
  steps: Step[];
  tables: { name: string; rows: PlayerRow[] }[];
  shortlist?: { candidates: Candidate[]; decided: boolean };
  reports: Report[];
  answer?: string;
  error?: string;
  runId?: string;
  rated?: 0 | 1;
}

export default function SearchChat() {
  const params = useSearchParams();
  const router = useRouter();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [threadId, setThreadId] = useState<string | null>(params.get("thread"));
  const [running, setRunning] = useState(false);
  const [draft, setDraft] = useState("");
  const started = useRef(false);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => { api.meta().then(setMeta).catch(() => setMeta(null)); }, []);

  const update = useCallback((fn: (t: Turn) => Turn) => {
    setTurns((ts) => (ts.length ? [...ts.slice(0, -1), fn(ts[ts.length - 1])] : ts));
  }, []);

  const onEvent = useCallback((e: AgentEvent) => {
    switch (e.event) {
      case "meta":
        setThreadId(e.data.thread_id);
        update((t) => ({ ...t, runId: e.data.run_id }));
        break;
      case "step":
        update((t) => ({ ...t, steps: [...t.steps, { ...e.data }] }));
        break;
      case "result":
        update((t) => ({
          ...t,
          steps: t.steps.map((s) => (s.id === e.data.id ? { ...s, done: true, summary: e.data.summary, is_error: e.data.is_error } : s)),
          tables: e.data.data?.length ? [...t.tables, { name: e.data.name, rows: e.data.data }] : t.tables,
        }));
        break;
      case "shortlist":
        update((t) => ({
          ...t,
          shortlist: { candidates: e.data.candidates, decided: false },
          steps: t.steps.map((s) => (s.name === "propose_shortlist" && !s.done
            ? { ...s, done: true, summary: "Waiting for your approval" } : s)),
        }));
        break;
      case "report":
        update((t) => ({ ...t, reports: [...t.reports, e.data] }));
        break;
      case "answer":
        update((t) => ({ ...t, answer: e.data.text }));
        break;
      case "error":
        update((t) => ({ ...t, error: e.data.message }));
        break;
    }
  }, [update]);

  const ask = useCallback(async (question: string) => {
    const q = question.trim();
    if (!q || running) return;
    setDraft("");
    setTurns((ts) => [...ts, { question: q, steps: [], tables: [], reports: [] }]);
    setRunning(true);
    try {
      let tid = threadId;
      await streamAgent("/api/chat", { message: q, thread_id: threadId }, (e) => {
        if (e.event === "meta") { tid = e.data.thread_id; rememberThread(tid, q); }
        onEvent(e);
      });
      if (tid) router.replace(`/?thread=${tid}`, { scroll: false });
    } catch (err) {
      update((t) => ({ ...t, error: (err as Error).message }));
    } finally {
      setRunning(false);
    }
  }, [running, threadId, onEvent, update, router]);

  const decide = useCallback(async (approved: number[], comment: string | null) => {
    if (!threadId) return;
    update((t) => ({ ...t, shortlist: t.shortlist && { ...t.shortlist, decided: true } }));
    setRunning(true);
    try {
      await streamAgent("/api/chat/resume", { thread_id: threadId, approved, comment }, onEvent);
    } catch (err) {
      update((t) => ({ ...t, error: (err as Error).message }));
    } finally {
      setRunning(false);
    }
  }, [threadId, onEvent, update]);

  // Reopen a thread (e.g. from the shortlists page) or run ?q= once.
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const q = params.get("q");
    const thread = params.get("thread");
    if (q) { ask(q); return; }
    if (thread) {
      api.thread(thread).then((t) => {
        const restored: Turn[] = [];
        for (const m of t.messages) {
          if (m.role === "user") restored.push({ question: m.text, steps: [], tables: [], reports: [] });
          else if (restored.length) restored[restored.length - 1].answer = m.text;
        }
        if (t.pending && restored.length) restored[restored.length - 1].shortlist = { candidates: t.pending.candidates, decided: false };
        if (t.reports.length && restored.length) restored[restored.length - 1].reports = t.reports;
        setTurns(restored);
      }).catch(() => undefined);
    }
  }, [params, ask]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns.length]);

  const submit = (e: FormEvent) => { e.preventDefault(); ask(draft); };
  const newSearch = () => { setTurns([]); setThreadId(null); router.replace("/", { scroll: false }); };
  const current = turns[turns.length - 1];
  const offline = meta !== null && !meta.llm;

  if (!turns.length) {
    return (
      <div className="page search-empty">
        <h1>Describe the player you need.</h1>
        <p className="lede">
          Position, age, budget, contract, style. Touchline searches {meta ? meta.active_players.toLocaleString("en-GB") : "about 22,000"} active
          players and explains every pick with numbers from the database and cited sources.
        </p>
        {offline && (
          <p className="notice">
            The agent isn&apos;t switched on for this demo yet. You can still open player profiles, compare players and add notes.
          </p>
        )}
        <form onSubmit={submit} className="composer composer-hero">
          <label htmlFor="q" className="sr-only">Your scouting brief</label>
          <textarea id="q" rows={3} className="input" value={draft} onChange={(e) => setDraft(e.target.value)}
                    placeholder="A left-footed centre-back under 23, under €10M, comfortable in build-up, contract ending by 2027"
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(draft); } }} />
          <button className="btn btn-primary" disabled={!draft.trim() || offline}>Search</button>
        </form>
        <div className="examples">
          <p className="hint">Try one of these:</p>
          <ul>
            {(meta?.examples ?? []).map((ex) => (
              <li key={ex}><button className="example" disabled={offline} onClick={() => ask(ex)}>{ex}</button></li>
            ))}
          </ul>
        </div>
        <p className="hint coverage-note">
          Detailed event metrics exist for {meta ? meta.event_players : "about 600"} players who appeared in recent
          StatsBomb competitions; everyone else has market data only. Each result says which.
        </p>
      </div>
    );
  }

  return (
    <div className="page search-live">
      <div className="convo">
        <div className="convo-head">
          <h2>Search</h2>
          <button className="btn btn-quiet" onClick={newSearch} disabled={running}>New search</button>
        </div>
        {turns.map((t, i) => (
          <section key={i} className="turn">
            <p className="turn-q">{t.question}</p>
            {t.tables.length > 0 && (
              <details className="turn-table" open={i === turns.length - 1}>
                <summary>
                  {t.tables[t.tables.length - 1].name === "similar_players" ? "Similar players" : "Search results"} ({t.tables[t.tables.length - 1].rows.length} shown)
                </summary>
                <PlayerTable rows={t.tables[t.tables.length - 1].rows} />
              </details>
            )}
            {t.shortlist && !t.shortlist.decided && (
              <ShortlistApproval candidates={t.shortlist.candidates} busy={running} onDecide={decide} />
            )}
            {t.reports.map((r) => <ReportView key={r.player_id} report={r} />)}
            {t.answer && (
              <div className="answer prose">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{t.answer}</ReactMarkdown>
                {t.runId && (
                  <div className="rate">
                    <span className="hint">{t.rated == null ? "Was this useful?" : "Thanks, noted."}</span>
                    {t.rated == null && (["Yes", "No"] as const).map((label) => (
                      <button key={label} className="btn btn-quiet" onClick={() => {
                        const score = label === "Yes" ? 1 : 0;
                        api.feedback(t.runId!, score).catch(() => undefined);
                        setTurns((ts) => ts.map((x, j) => (j === i ? { ...x, rated: score } : x)));
                      }}>{label === "Yes" ? "👍 Yes" : "👎 No"}</button>
                    ))}
                  </div>
                )}
              </div>
            )}
            {t.error && <p className="error">{t.error}</p>}
          </section>
        ))}
        <div ref={bottom} />
        <form onSubmit={submit} className="composer">
          <label htmlFor="q2" className="sr-only">Follow-up</label>
          <textarea id="q2" rows={2} className="input" value={draft} onChange={(e) => setDraft(e.target.value)}
                    placeholder="Refine it: cheaper, younger, a different league, or ask for reports"
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(draft); } }} />
          <button className="btn btn-primary" disabled={!draft.trim() || running}>{running ? "Working…" : "Send"}</button>
        </form>
      </div>
      <aside className="log-col">
        <StepLog steps={current?.steps ?? []} running={running} />
      </aside>
    </div>
  );
}
