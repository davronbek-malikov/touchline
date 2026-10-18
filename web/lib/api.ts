// Local development falls back to the API on :8000; a production build without
// NEXT_PUBLIC_API_URL has no backend and says so instead of calling localhost.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL
  || (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "")).replace(/\/$/, "");

const NOT_CONNECTED = "This site isn't connected to the Touchline server yet, so live player data and the assistant are unavailable.";

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

export interface ModelOption {
  id: string;
  label: string;
  provider: "anthropic" | "ollama";
  available: boolean;
  note: string;
  reason: string | null;
}

export interface Folder { folder_id: string; name: string; created_at: string }

export interface ChatSummary {
  chat_id: string;
  title: string;
  folder_id: string | null;
  model: string | null;
  created_at: string;
  updated_at: string;
}

export interface StepState {
  id: string;
  name: string;
  input: Record<string, unknown>;
  summary?: string | null;
  is_error?: boolean;
  done?: boolean;
}

export interface TurnData {
  turn: number;
  text: string;
  attachments: string[];
  steps: StepState[];
  table: { name: string; rows: PlayerRow[] } | null;
  answer: string | null;
  reports: Report[];
}

export interface ChatFull extends ChatSummary {
  turns: TurnData[];
  pending: { candidates: Candidate[] } | null;
}

export interface UploadedFile {
  file_id: string;
  name: string;
  kind: "image" | "pdf" | "text";
  size: number;
  note: string | null;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const CLIENT_KEY = "touchline.client";

/** Anonymous id that scopes this browser's chats, folders and uploads. Not authentication. */
export function clientId(): string {
  try {
    let id = localStorage.getItem(CLIENT_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(CLIENT_KEY, id);
    }
    return id;
  } catch {
    // Storage blocked: keep one id for this page load.
    const w = window as unknown as { __touchlineClient?: string };
    w.__touchlineClient ??= crypto.randomUUID();
    return w.__touchlineClient;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!API_URL) throw new ApiError(0, NOT_CONNECTED);
  let res: Response;
  const headers = new Headers(init.headers);
  headers.set("X-Client-Id", clientId());
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Can't reach the Touchline server. Check your connection and try again.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail || `Request failed (${res.status}).`);
  }
  return res.json();
}

const json = (method: string, body: unknown): RequestInit =>
  ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  meta: () => request<Meta>("/api/meta"),
  models: () => request<{ default: string; models: ModelOption[] }>("/api/models"),
  find: (q: string) => request<{ candidates: (PlayerRow & { match_score: number })[] }>(
    `/api/players/find?q=${encodeURIComponent(q)}`),
  profile: (id: number) => request<Profile>(`/api/players/${id}`),
  similar: (id: number) => request<{ players: PlayerRow[]; notes: string[] }>(`/api/players/${id}/similar`),
  compare: (ids: number[]) => request<{ players: (PlayerRow & { event_profile: EventProfile | null })[]; notes: string[] }>(
    `/api/compare?ids=${ids.join(",")}`),
  notes: (id: number) => request<{ notes: Note[] }>(`/api/players/${id}/notes`),
  addNote: (note: { player_id: number; text: string; author: string; context?: string }) =>
    request<Note>("/api/notes", json("POST", note)),
  evalSummary: () => request<{ results: Record<string, unknown>[] }>("/api/eval/summary"),
  feedback: (run_id: string, score: 0 | 1) => request("/api/feedback", json("POST", { run_id, score })),

  chats: () => request<{ folders: Folder[]; chats: ChatSummary[] }>("/api/chats"),
  chat: (id: string) => request<ChatFull>(`/api/chats/${id}`),
  renameChat: (id: string, title: string) => request<ChatSummary>(`/api/chats/${id}`, json("PATCH", { title })),
  moveChat: (id: string, folder_id: string | null) =>
    request<ChatSummary>(`/api/chats/${id}`, json("PATCH", { folder_id, move: true })),
  deleteChat: (id: string) => request(`/api/chats/${id}`, { method: "DELETE" }),
  addFolder: (name: string) => request<Folder>("/api/folders", json("POST", { name })),
  renameFolder: (id: string, name: string) => request(`/api/folders/${id}`, json("PATCH", { name })),
  deleteFolder: (id: string) => request(`/api/folders/${id}`, { method: "DELETE" }),
  shortlists: () => request<{
    waiting: (ChatSummary & { candidates: Candidate[] })[];
    written: (ChatSummary & { reports: { player_id: number; name: string }[] })[];
  }>("/api/shortlists"),
  upload: (file: Blob, name: string) => {
    const form = new FormData();
    form.append("file", file, name);
    return request<UploadedFile>("/api/files", { method: "POST", body: form });
  },
};

export type AgentEvent =
  | { event: "meta"; data: { chat_id: string; run_id: string; turn: number; title: string } }
  | { event: "step"; data: { id: string; name: string; input: Record<string, unknown> } }
  | { event: "result"; data: { id: string; name: string; is_error: boolean; summary: string | null; data: PlayerRow[] | null } }
  | { event: "shortlist"; data: { chat_id: string; candidates: Candidate[] } }
  | { event: "report"; data: Report }
  | { event: "answer"; data: { text: string } }
  | { event: "error"; data: { message: string } }
  | { event: "done"; data: { status: string; cost_usd: number } };

/** POST to an SSE endpoint and call onEvent for each event until the stream ends. */
export async function streamAgent(path: string, body: unknown, onEvent: (e: AgentEvent) => void,
                                  signal?: AbortSignal): Promise<void> {
  if (!API_URL) throw new ApiError(0, NOT_CONNECTED);
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: "POST", body: JSON.stringify(body), signal,
      headers: { "Content-Type": "application/json", "X-Client-Id": clientId() },
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
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
    const { done, value } = await reader.read().catch((e) => {
      if ((e as Error).name === "AbortError") return { done: true, value: undefined };
      throw e;
    });
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
