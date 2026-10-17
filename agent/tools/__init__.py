"""Tool registry: Claude-facing definitions and a single dispatcher.

estimate_value registers here in milestone 6. propose_shortlist is defined here for
Claude but executed by the graph (it pauses for the scout's approval).
"""
import json
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ValidationError

from agent.schemas import (ComparePlayersInput, FindPlayerInput, PlayerIdInput, ProposeShortlistInput,
                           SearchNotesInput, SearchPlayersInput, SimilarPlayersInput, strict_schema)
from agent.tools.db import ToolError
from agent.tools.notes import search_notes
from agent.tools.players import compare_players, find_player, get_player_profile, search_players
from agent.tools.similar import similar_players


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    fn: Callable[[BaseModel], dict]

    def definition(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": strict_schema(self.input_model), "strict": True}


REGISTRY: dict[str, Tool] = {t.name: t for t in [
    Tool("find_player",
         "Resolve a player's name to Transfermarkt player ids. Call this before get_player_profile, "
         "similar_players or compare_players whenever the scout names a player. Returns ranked candidates "
         "with club and value so you can pick the right person; ask the scout if it is ambiguous.",
         FindPlayerInput, find_player),
    Tool("search_players",
         "Search active players with typed filters (position, age, value, foot, height, contract, league, "
         "nationality, minutes, event-metric percentiles) and a sort order. Returns rows with a coverage "
         "badge ('market only' or 'market + events') and the total match count. Use for any 'find me a ...' "
         "request. Only pass filters the scout asked for or clearly implied.",
         SearchPlayersInput, search_players),
    Tool("get_player_profile",
         "Full profile for one player: bio, contract, market value and its history, the last four seasons "
         "of minutes/goals/assists, and the StatsBomb event profile with per-90 values and position-group "
         "percentiles when available.",
         PlayerIdInput, get_player_profile),
    Tool("similar_players",
         "Players whose StatsBomb event profile is most similar to a reference player (cosine similarity "
         "on position-normalised per-90 metrics), optionally capped by value and age. Returns similarity "
         "scores and the traits they share. Only works for players with event data.",
         SimilarPlayersInput, similar_players),
    Tool("compare_players",
         "Side-by-side comparison of 2-4 players: market fields plus event metrics and percentiles.",
         ComparePlayersInput, compare_players),
    Tool("search_notes",
         "Search qualitative evidence: the scouts' own match notes and Wikipedia 'Style of play' text "
         "(CC BY-SA). Use for how a player plays, strengths and weaknesses, and anything the numbers "
         "don't show. Pass player_id to search one player's passages. Returns passages with source ids.",
         SearchNotesInput, search_notes),
]}

SHORTLIST_TOOL = "propose_shortlist"
SHORTLIST_DEFINITION = {
    "name": SHORTLIST_TOOL,
    "description": "Propose a ranked shortlist (1-8 players) for the scout to approve before full scouting "
                   "reports are written. Use it when the scout asks for reports, a dossier, or a shortlist "
                   "with reports; for a single named player, propose just that player. The scout approves "
                   "or removes names, and a cited report is then written for each approved player.",
    "input_schema": strict_schema(ProposeShortlistInput),
    "strict": True,
}

TOOLS: list[dict] = [t.definition() for t in REGISTRY.values()] + [SHORTLIST_DEFINITION]


def run_tool(name: str, tool_input: dict) -> tuple[str, bool]:
    """Execute a tool call. Returns (json_content, is_error) ready for a tool_result block."""
    tool = REGISTRY.get(name)
    if tool is None:
        return json.dumps({"error": f"unknown tool {name}"}), True
    try:
        args = tool.input_model.model_validate(tool_input)
        return json.dumps(tool.fn(args), ensure_ascii=False, default=str), False
    except ValidationError as e:
        errs = [{"field": ".".join(map(str, x["loc"])), "problem": x["msg"]} for x in e.errors()]
        return json.dumps({"error": "invalid arguments", "details": errs}), True
    except ToolError as e:
        return json.dumps({"error": str(e)}), True
