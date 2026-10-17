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
- [x] Pydantic schemas (`agent/schemas.py`) → strict JSON schemas (limits enforced client-side)
- [x] `player_performance` table: one headline event profile per TM player (594 players)
- [x] `find_player` (added: name → id lookup), `search_players`, `get_player_profile`, `compare_players`
- [x] `similar_players` v1 (z-scored cosine; TacticalDNA engine replaces it in M6)
- [x] Registry + `run_tool()` dispatcher (validation errors → `is_error` results), CLI `python -m agent.tools`
- [x] Unit tests per tool on a fixture warehouse (31 passing)
- [ ] `estimate_value` → registers in M6 · `search_notes` → registers in M5

## M3 · Agent
- [x] `agent/claude.py`: claude-opus-5-5, effort medium, `fallbacks: "default"`, system + conversation caching, traced to LangSmith with token usage
- [x] `agent/prompts/system.md` (grounding rules, data coverage, role glossary, metric dictionary, answer format)
- [x] `agent/graph.py` LangGraph loop: parallel tools, one tool_result message per turn, 8-round cap, append-only history
- [x] Terminal CLI `python -m agent.cli` with live step output and cache stats
- [x] Graph tests with a fake Claude + request-shape tests on a mocked HTTP transport (40 passing)
- [ ] **You:** add `ANTHROPIC_API_KEY` to `.env`, then first live run; check traces in LangSmith `touchline-dev` and `cache_read_input_tokens > 0` from the 2nd call

## M4 · Golden set + eval v1
- [x] `eval/golden_spec.py` (120 hand-written queries: 50 filter, 20 similar, 25 fact, 15 report, 10 trap; 30 tagged CI)
- [x] `eval/build_golden.py` computes every gold answer from the warehouse → `eval/golden.jsonl`
- [x] Evaluators: filter accuracy, P@10/R@10, numeric grounding, hallucinated + ungrounded players, fact correct, trap handled, tool error rate, cost, latency
- [x] Evaluator sanity check: 0/70 false alarms on perfect answers; corrupted answer caught
- [x] Runner `eval/run_experiment.py` (local results or LangSmith experiment, `--ci`, `--max-cost`)
- [x] LangSmith dataset `touchline-golden` uploaded (120 examples)
- [x] Fixed on the way: ages were rounded (Yamal 19 → 18); Dani Olmo was linked to Daniel Carvajal
- [ ] **You:** review the 120 queries and gold answers in `eval/golden_spec.py` / `eval/golden.jsonl`
- [ ] Baseline experiment `v1-baseline` (needs `ANTHROPIC_API_KEY`), fill the results table

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
