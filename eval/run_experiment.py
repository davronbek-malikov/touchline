"""Run the golden set against the agent and score it.

    python -m eval.run_experiment --label v1-baseline              # local: eval/results/<label>.jsonl
    python -m eval.run_experiment --label v1-baseline --langsmith  # LangSmith experiment on touchline-golden
    python -m eval.run_experiment --ci --max-cost 3                # the 30-query CI subset, capped spend

Every run spends API credit. --max-cost stops a local run once the running total passes it.
"""
import argparse
import json
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from agent.claude import EFFORT, MODEL, PROMPT_VERSION, AnthropicClaude  # noqa: E402
from agent.graph import build_graph  # noqa: E402
from eval.evaluators import score_all  # noqa: E402
from eval.target import run_query  # noqa: E402

GOLDEN = Path(__file__).parent / "golden.jsonl"
RESULTS = Path(__file__).parent / "results"
DATASET = "touchline-golden"
LOWER_IS_BETTER = {"hallucinated_players", "ungrounded_players", "tool_error_rate", "cost_usd", "latency_s"}


def load_items(ci: bool = False, types: list[str] | None = None, limit: int | None = None) -> list[dict]:
    items = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    if ci:
        items = [it for it in items if it["ci"]]
    if types:
        items = [it for it in items if it["type"] in types]
    return items[:limit] if limit else items


def summarise(scored: list[dict]) -> dict:
    """Mean of each metric overall and by query type; p50/p95 latency."""
    by_metric, by_type = defaultdict(list), defaultdict(lambda: defaultdict(list))
    for s in scored:
        for k, v in s["scores"].items():
            by_metric[k].append(v)
            by_type[s["type"]][k].append(v)
    out = {k: round(statistics.mean(v), 4) for k, v in by_metric.items()}
    out["cost_usd_total"] = round(sum(by_metric.get("cost_usd", [])), 4)
    lat = sorted(by_metric.get("latency_s", []))
    if lat:
        out["latency_p50"] = round(statistics.median(lat), 2)
        out["latency_p95"] = round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 2)
    out["by_type"] = {t: {k: round(statistics.mean(v), 4) for k, v in m.items()} for t, m in by_type.items()}
    out["n"] = len(scored)
    return out


def run_local(items: list[dict], label: str, concurrency: int, max_cost: float | None) -> dict:
    graph = build_graph(AnthropicClaude())
    meta = {"prompt_version": PROMPT_VERSION, "effort": EFFORT, "model": MODEL, "experiment": label}
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{label}.jsonl"
    scored, spent = [], 0.0
    with ThreadPoolExecutor(concurrency) as pool, path.open("w", encoding="utf-8") as f:
        futures = [(it, pool.submit(run_query, graph, it["query"], meta | {"item_id": it["id"]})) for it in items]
        for it, fut in futures:
            if max_cost is not None and spent > max_cost:
                fut.cancel()
                continue
            try:
                outputs = fut.result()
            except Exception as e:  # keep going; a crashed item scores as an error row
                outputs = {"final_text": "", "tool_calls": [], "usage": [], "latency_s": None, "error": repr(e)}
            result = score_all(it, outputs)
            spent += result["scores"].get("cost_usd", 0.0)
            row = {"id": it["id"], "type": it["type"], "query": it["query"], **result, "outputs": outputs}
            scored.append(row)
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            print(f"{it['id']:12s} " + " ".join(f"{k}={v}" for k, v in result["scores"].items()
                                                 if k not in ("cost_usd", "latency_s")))
    summary = summarise(scored) | {"label": label, **meta}
    (RESULTS / f"{label}.summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def sync_dataset(client, items: list[dict]) -> str:
    """Create the LangSmith dataset on first use; add any golden items it lacks."""
    if client.has_dataset(dataset_name=DATASET):
        ds = client.read_dataset(dataset_name=DATASET)
    else:
        ds = client.create_dataset(DATASET, description="Touchline golden scouting queries (eval/golden.jsonl)")
    existing = {ex.metadata.get("id") for ex in client.list_examples(dataset_id=ds.id)}
    new = [it for it in items if it["id"] not in existing]
    if new:
        client.create_examples(
            dataset_id=ds.id,
            inputs=[{"query": it["query"]} for it in new],
            outputs=[{"type": it["type"], "reference": it["reference"]} for it in new],
            metadata=[{"id": it["id"], "type": it["type"], "tags": it["tags"], "ci": it["ci"]} for it in new],
        )
    return ds.name


def run_langsmith(items: list[dict], label: str, concurrency: int) -> None:
    from langsmith import Client, evaluate

    client = Client()
    sync_dataset(client, load_items())
    wanted = {it["id"] for it in items}
    examples = [ex for ex in client.list_examples(dataset_name=DATASET) if ex.metadata.get("id") in wanted]
    graph = build_graph(AnthropicClaude())

    def target(inputs: dict) -> dict:
        return run_query(graph, inputs["query"])

    def touchline_scores(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
        item = {"type": reference_outputs["type"], "query": inputs["query"],
                "reference": reference_outputs["reference"]}
        r = score_all(item, outputs)
        return {"results": [{"key": k, "score": v, "comment": r["comments"].get(k)}
                            for k, v in r["scores"].items()]}

    evaluate(target, data=examples, evaluators=[touchline_scores], experiment_prefix=label,
             max_concurrency=concurrency,
             metadata={"prompt_version": PROMPT_VERSION, "effort": EFFORT, "model": MODEL})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=f"{PROMPT_VERSION}-{EFFORT}")
    ap.add_argument("--ci", action="store_true", help="30-query CI subset")
    ap.add_argument("--types", nargs="*", choices=["filter", "similar", "fact", "report", "trap"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--max-cost", type=float, help="stop a local run once spend passes this many dollars")
    ap.add_argument("--langsmith", action="store_true", help="run as a LangSmith experiment")
    args = ap.parse_args()

    items = load_items(args.ci, args.types, args.limit)
    print(f"{len(items)} items · model={MODEL} effort={EFFORT} prompt={PROMPT_VERSION}")
    if args.langsmith:
        run_langsmith(items, args.label, args.concurrency)
        return
    summary = run_local(items, args.label, args.concurrency, args.max_cost)
    print(json.dumps({k: v for k, v in summary.items() if k != "by_type"}, indent=2))


if __name__ == "__main__":
    main()
