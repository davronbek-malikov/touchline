# Touchline

**An AI scouting copilot for football.** Describe the player you need in plain language and get a ranked, evidence-backed shortlist and cited scouting reports.

> *"A left-footed centre-back under 23, under €10M, comfortable in build-up, contract ending by 2027."*

Claude (`claude-opus-5-5`) reasons over six typed tools and never writes SQL, so every number comes from a database query. LangGraph runs the agent with a human approval step, Qdrant hybrid RAG supplies cited evidence, and LangSmith tracks every run against a fixed golden test set.

Full design: [docs/PLAN.md](docs/PLAN.md) · Progress: [TODO.md](TODO.md)

## Status

**Milestone 1 (warehouse) is built.** `warehouse/touchline.duckdb`:

| Table | Rows | What |
|---|---|---|
| `players` | 50,149 | Transfermarkt bio, position group, foot, club, contract, market value |
| `player_seasons` | 193,537 | Minutes, goals, assists per player · season · competition |
| `value_history` | 656,301 | Market valuations over time |
| `sb_players` | 3,230 | StatsBomb players per competition season (8 competitions, 297 matches) |
| `sb_player_per90` | 778 | Per-90 event metrics, ≥ 270 minutes |
| `sb_percentiles` | 688 | Percentiles within position group (outfield) |
| `player_links` | 2,497 | StatsBomb ↔ Transfermarkt matches (87.5% linked; 93.7% of per-90 players) |

## Quick start

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m data.download          # ~210 MB Transfermarkt + StatsBomb JSON
.venv/Scripts/python -m data.build_warehouse   # ~2 min
.venv/Scripts/python -m pytest
```

**Milestone 2 (tools) is built.** Five strict-schema tools Claude can call, in [agent/tools/](agent/tools/):
`find_player`, `search_players`, `get_player_profile`, `similar_players`, `compare_players`.

```bash
.venv/Scripts/python -m agent.tools search_players '{"position_groups": ["CB"], "foot": "left", "age_max": 22, "value_max_eur": 10000000}'
```

**Milestone 3 (agent) is built.** A LangGraph loop around Claude with the tools above:

```bash
cp .env.example .env    # add ANTHROPIC_API_KEY and LANGSMITH_API_KEY
.venv/Scripts/python -m agent.cli "left-footed centre-back under 23, under €10M, good in build-up"
```

**Milestone 4 (evaluation) is built.** 120 golden queries with gold answers computed from the warehouse, deterministic evaluators, and a LangSmith dataset:

```bash
.venv/Scripts/python -m eval.run_experiment --ci --max-cost 3 --label smoke       # 30 queries, local
.venv/Scripts/python -m eval.run_experiment --label v1-baseline --langsmith       # full set as a LangSmith experiment
```

**Milestone 5 (RAG + cited reports) is built.** Scout notes and Wikipedia "Style of play" passages are indexed in Qdrant (dense + BM25, fused with RRF). Asking for a report pauses the agent for shortlist approval; each approved player gets a report whose qualitative claims cite their source passage.

```bash
.venv/Scripts/python -m data.wikipedia_fetch            # ~1,400 player pages via Wikidata
.venv/Scripts/python -m rag.index_notes                 # build the passage index
.venv/Scripts/python -m rag.index_notes add 937958 "Great first touch, drifts inside early" --context "vs Real Madrid"
.venv/Scripts/python -m agent.cli "Scouting reports on left-footed centre-backs under 23"
```

**Milestones 7–8 (web app, deploy).** The web app is live at **https://touchline-pi-lime.vercel.app**. The backend (`Dockerfile`, `railway.json`) is ready for Railway but not yet deployed, so the live site currently says it isn't connected.

```bash
.venv/Scripts/python -m uvicorn api.main:app --port 8000     # API locally
cd web && npm install && npm run dev                          # web app on :3000
```

### Deploy the backend on Render (free)

`render.yaml` + `Dockerfile.render` run the API on Render's free tier (512 MB, no persistent disk): state lives in Postgres, passage search is BM25-only with the index rebuilt in memory at startup (about 230 MB at peak), and the warehouse comes from the [data release](https://github.com/davronbek-malikov/touchline/releases/tag/data-2026-07-06).

1. Create a free Postgres database at [neon.tech](https://neon.tech) (region: Singapore) and copy its connection string.
2. In Render: **New → Blueprint →** this repository. Fill in `DATABASE_URL`, `ANTHROPIC_API_KEY` and `LANGSMITH_API_KEY`.
3. Point the web app at it: set `NEXT_PUBLIC_API_URL` on Vercel to the Render URL and redeploy.

The free service sleeps after 15 idle minutes; the first request after that takes about a minute.

Linking accuracy: label `data/labels/link_sample.csv` (fill `is_correct`), then `python -m data.eval_links`.

## Data credits

- **StatsBomb Open Data:** event data © StatsBomb, used under the [StatsBomb open data user agreement](https://github.com/statsbomb/open-data). StatsBomb logo to appear wherever their metrics are shown.
- **Transfermarkt** via [transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets) (CC0). Data originates from Transfermarkt and is current to 6 July 2026. Non-commercial use.
- **Wikipedia** "Style of play" text under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); each passage keeps its article URL and revision id, and reports link back to them.
