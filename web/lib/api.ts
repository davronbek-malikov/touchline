export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export type Coverage = "market only" | "market + events";

export interface PlayerRow {
  player_id: number;
  name: string;
  age?: number | null;
  position_group?: string | null;
  sub_position?: string | null;
  foot?: string | null;
  club_name?: string | null;
  league_id?: string | null;
  market_value_eur?: number | null;
  contract_until?: string | null;
  minutes_2025_26?: number | null;
  coverage?: Coverage;
  similarity?: number;
  shared_traits?: string[];
  event_competition?: string;
  [metric: string]: unknown;
}

export interface Metric {
  value: number | null;
  percentile: number | null;
  description: string;
}

export interface EventProfile {
  competition: string;
  minutes: number;
  matches: number;
  position_group: string;
  metrics: Record<string, Metric>;
}

export interface Profile {
  player: PlayerRow & {
    date_of_birth?: string;
    height_in_cm?: number;
    nationality?: string;
    league?: string;
    highest_market_value_eur?: number;
    international_caps?: number;
    is_active?: boolean;
  };
  seasons: { season: string; appearances: number; minutes: number; goals: number; assists: number }[];
  market_value_history: { date: string; market_value_eur: number; club_name: string }[];
  event_profile: EventProfile | null;
  data_as_of: string;
  notes: string[];
}

export interface Citation {
  cited_text: string;
  source_id: string | null;
  title: string;
  url: string | null;
  source: string | null;
}

export interface Report {
  player_id: number;
  name: string;
  blocks: { text: string; citations: Citation[] }[];
  sources?: { source_id: string; title: string; url: string | null; licence: string }[];
  error?: string;
}

export interface Candidate {
  player_id: number;
  name: string;
  age: number | null;
  position_group: string | null;
  club_name: string | null;
  market_value_eur: number | null;
  reason: string;
}

export interface Note {
  note_id: string;
  player_id: number;
  author: string;
  created_at: string;
  context: string | null;
  text: string;
}

export interface Meta {
  data_as_of: string;
  active_players: number;
  event_players: number;
  examples: string[];
  llm: boolean;
  model: string;
  effort: string;
  prompt_version: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(0, "Can't reach the Touchline server. Check your connection and try again.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail || `Request failed (${res.status}).`);
  }
  return res.json();
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  find: (q: string) => request<{ candidates: (PlayerRow & { match_score: number })[] }>(
    `/api/players/find?q=${encodeURIComponent(q)}`),
  profile: (id: number) => request<Profile>(`/api/players/${id}`),
  similar: (id: number) => request<{ players: PlayerRow[]; notes: string[] }>(`/api/players/${id}/similar`),
  compare: (ids: number[]) => request<{ players: (PlayerRow & { event_profile: EventProfile | null })[]; notes: string[] }>(
    `/api/compare?ids=${ids.join(",")}`),
  notes: (id: number) => request<{ notes: Note[] }>(`/api/players/${id}/notes`),
  addNote: (note: { player_id: number; text: string; author: string; context?: string }) =>
    request<Note>("/api/notes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(note) }),
  thread: (id: string) => request<{ messages: { role: string; text: string }[]; pending: { candidates: Candidate[] } | null; reports: Report[] }>(
    `/api/threads/${id}`),
  evalSummary: () => request<{ results: Record<string, unknown>[] }>("/api/eval/summary"),
  feedback: (run_id: string, score: 0 | 1) =>
    request("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ run_id, score }) }),
};

export type AgentEvent =
  | { event: "meta"; data: { thread_id: string; run_id: string } }
  | { event: "step"; data: { id: string; name: string; input: Record<string, unknown> } }
  | { event: "result"; data: { id: string; name: string; is_error: boolean; summary: string | null; data: PlayerRow[] | null } }
  | { event: "shortlist"; data: { thread_id: string; candidates: Candidate[] } }
  | { event: "report"; data: Report }
  | { event: "answer"; data: { text: string } }
  | { event: "error"; data: { message: string } }
  | { event: "done"; data: { status: string; cost_usd: number } };

/** POST to an SSE endpoint and call onEvent for each event until the stream ends. */
export async function streamAgent(path: string, body: unknown, onEvent: (e: AgentEvent) => void,
                                  signal?: AbortSignal): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
    });
  } catch {
    throw new ApiError(0, "Can't reach the Touchline server. Check your connection and try again.");
  }
  if (!res.ok || !res.body) {
    const detail = await res.json().catch(() => ({}));
    throw new ApiError(res.status, detail.detail || `Request failed (${res.status}).`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      let event = "message";
      let data = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) onEvent({ event, data: JSON.parse(data) } as AgentEvent);
    }
  }
}

export function euros(v: number | null | undefined): string {
  if (v == null) return "–";
  if (v >= 1e6) return `€${(v / 1e6).toFixed(v % 1e6 === 0 ? 0 : 1)}M`;
  if (v >= 1e3) return `€${Math.round(v / 1e3)}k`;
  return `€${v}`;
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export const POSITION_NAMES: Record<string, string> = {
  GK: "Goalkeeper", CB: "Centre-back", FB: "Full-back", DM: "Defensive midfielder",
  CM: "Central midfielder", AM: "Attacking midfielder", W: "Winger", ST: "Striker",
};

const THREADS_KEY = "touchline.threads";

/** Thread ids this browser has started, newest first (a per-viewer convenience). */
export function rememberThread(id: string, title: string): void {
  try {
    const list = recentThreads().filter((t) => t.id !== id);
    list.unshift({ id, title, at: new Date().toISOString() });
    localStorage.setItem(THREADS_KEY, JSON.stringify(list.slice(0, 30)));
  } catch {
    /* storage unavailable: threads just aren't remembered */
  }
}

export function recentThreads(): { id: string; title: string; at: string }[] {
  try {
    return JSON.parse(localStorage.getItem(THREADS_KEY) || "[]");
  } catch {
    return [];
  }
}
