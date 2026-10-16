# Touchline — to-do

Full plan: [docs/PLAN.md](docs/PLAN.md)

## M0 · Scaffold
- [x] Standalone git repo, Python 3.12 venv
- [x] Plan renamed to Touchline
- [x] pyproject, .gitignore, .env.example, README skeleton, folder layout

## M1 · Warehouse
- [x] Download Transfermarkt DuckDB (`data/download.py`)
- [x] Download StatsBomb open data for target competitions (8 comps, 297 matches)
- [x] `build_warehouse.py`: `players`, `player_seasons`, `value_history` from Transfermarkt
- [x] `statsbomb_per90.py`: per-90 event metrics (≥ 270 min) + position groups
- [x] `sb_percentiles` per position group
- [x] `link_players.py`: SB ↔ TM matching (name + nationality + club; SB has no DOB)
- [ ] **You:** hand-label `data/labels/link_sample.csv` (150 rows), run `python -m data.eval_links`
- [x] Tests on small fixtures (9 passing)

## M2 · Tools
- [ ] Pydantic schemas (`agent/schemas.py`) → strict JSON schemas
- [ ] `search_players`, `get_player_profile`, `compare_players`
- [ ] `similar_players`, `estimate_value` (stub until M6), `search_notes` (stub until M5)
- [ ] Unit tests per tool

## M3 · Agent
- [ ] `agent/claude.py` (caching, stop_reason handling, refusals)
- [ ] `agent/prompts/system.md` (role glossary, metric dictionary, rules)
- [ ] `agent/graph.py` LangGraph loop, 8-round cap
- [ ] Terminal CLI; LangSmith tracing
- [ ] Graph tests with a fake Claude client

## M4 · Golden set + eval v1
- [ ] `eval/golden.jsonl` (120 queries)
- [ ] Deterministic evaluators (filter acc., P@10/R@10, numeric grounding, hallucinated players, traps)
- [ ] LangSmith dataset + baseline experiment

## M5 · RAG + reports
- [ ] Wikipedia "Playing style" fetch
- [ ] Qdrant hybrid index (bge-small + BM25, RRF)
- [ ] Cited reports; `review_shortlist` interrupt; Postgres checkpointer

## M6 · ML
- [ ] LightGBM value model (group k-fold) + SHAP
- [ ] Similarity engine (TacticalDNA port)

## M7 · UI (Next.js)
- [ ] Search, Dossier, Compare, Shortlist, Notes, About/Eval
- [ ] FastAPI SSE backend

## M8 · Deploy + hardening
- [ ] Railway + Vercel, rate/spend limits, CI eval gate, README GIF

## M9 · Experiments write-up
- [ ] Effort / glossary / RAG experiments, results table
