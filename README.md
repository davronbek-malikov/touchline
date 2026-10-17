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

Linking accuracy: label `data/labels/link_sample.csv` (fill `is_correct`), then `python -m data.eval_links`.

## Data credits

- **StatsBomb Open Data:** event data © StatsBomb, used under the [StatsBomb open data user agreement](https://github.com/statsbomb/open-data). StatsBomb logo to appear wherever their metrics are shown.
- **Transfermarkt** via [transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets) (CC0). Data originates from Transfermarkt and is current to 6 July 2026. Non-commercial use.
- **Wikipedia** text (milestone 5) under CC BY-SA 4.0.
