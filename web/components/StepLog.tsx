"use client";

export interface Step {
  id: string;
  name: string;
  input: Record<string, unknown>;
  summary?: string | null;
  is_error?: boolean;
  done?: boolean;
}

function describe(step: Step): string {
  const i = step.input;
  switch (step.name) {
    case "find_player": return `Looking up “${i.name}”`;
    case "search_players": return "Searching the player database";
    case "get_player_profile": return "Reading a player profile";
    case "similar_players": return "Finding players with a similar profile";
    case "compare_players": return `Comparing ${(i.player_ids as number[] | undefined)?.length ?? ""} players`;
    case "search_notes": return `Searching notes for “${i.query}”`;
    case "propose_shortlist": return "Proposing a shortlist for your approval";
    default: return step.name;
  }
}

function filters(step: Step): string | null {
  if (step.name !== "search_players") return null;
  const parts = Object.entries(step.input)
    .filter(([k]) => k !== "limit")
    .map(([k, v]) => {
      if (k === "metric_filters" && Array.isArray(v)) {
        return v.map((f: { metric: string; percentile_min: number }) => `${f.metric.replaceAll("_", " ")} ≥ ${f.percentile_min}th`).join(", ");
      }
      return `${k.replaceAll("_", " ")}: ${Array.isArray(v) ? v.join("/") : String(v)}`;
    });
  return parts.length ? parts.join("; ") : null;
}

/** The agent's tool calls in order, like a match log: what it did and what came back. */
export default function StepLog({ steps, running }: { steps: Step[]; running: boolean }) {
  if (!steps.length && !running) return null;
  return (
    <section className="steplog" aria-label="What the agent did" aria-live="polite">
      <h3>What the agent did</h3>
      <ol>
        {steps.map((s, n) => (
          <li key={s.id} className={s.is_error ? "is-error" : s.done ? "is-done" : "is-running"}>
            <span className="steplog-n">{n + 1}</span>
            <div>
              <div className="steplog-what">{describe(s)}</div>
              {filters(s) && <div className="steplog-detail">{filters(s)}</div>}
              <div className="steplog-detail">
                {s.done ? (s.is_error ? `Failed: ${s.summary}` : s.summary) : "Working…"}
              </div>
            </div>
          </li>
        ))}
        {running && steps.every((s) => s.done) && (
          <li className="is-running"><span className="steplog-n">·</span><div className="steplog-what">Thinking…</div></li>
        )}
      </ol>
    </section>
  );
}
