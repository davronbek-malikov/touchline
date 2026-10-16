"""Pydantic input models for every tool, and their strict JSON schemas for Claude.

Strict tool use supports enums and nested objects but not numeric or length
constraints (minimum, maxItems, ...). Those limits are stated in the field
descriptions for Claude and enforced here by Pydantic when a call is validated.
"""
from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from data.statsbomb_per90 import ALL_METRICS


class PositionGroup(str, Enum):
    GK = "GK"
    CB = "CB"
    FB = "FB"
    DM = "DM"
    CM = "CM"
    AM = "AM"
    W = "W"
    ST = "ST"


class SubPosition(str, Enum):
    goalkeeper = "Goalkeeper"
    centre_back = "Centre-Back"
    left_back = "Left-Back"
    right_back = "Right-Back"
    defensive_midfield = "Defensive Midfield"
    central_midfield = "Central Midfield"
    left_midfield = "Left Midfield"
    right_midfield = "Right Midfield"
    attacking_midfield = "Attacking Midfield"
    left_winger = "Left Winger"
    right_winger = "Right Winger"
    second_striker = "Second Striker"
    centre_forward = "Centre-Forward"


# Transfermarkt ids of the domestic leagues in the snapshot.
LEAGUES = {
    "GB1": "Premier League (England)", "ES1": "LaLiga (Spain)", "IT1": "Serie A (Italy)",
    "L1": "Bundesliga (Germany)", "FR1": "Ligue 1 (France)", "PO1": "Liga Portugal",
    "NL1": "Eredivisie (Netherlands)", "BE1": "Pro League (Belgium)", "TR1": "Süper Lig (Türkiye)",
    "SC1": "Scottish Premiership", "A1": "Bundesliga (Austria)", "C1": "Super League (Switzerland)",
    "DK1": "Superliga (Denmark)", "GR1": "Super League 1 (Greece)", "NO1": "Eliteserien (Norway)",
    "SE1": "Allsvenskan (Sweden)", "PL1": "Ekstraklasa (Poland)", "TS1": "Chance Liga (Czech Republic)",
    "KR1": "SuperSport HNL (Croatia)", "SER1": "Super Liga (Serbia)", "RO1": "Superliga (Romania)",
    "UKR1": "Premier Liga (Ukraine)", "RU1": "Premier Liga (Russia)", "SA1": "Saudi Pro League",
    "MLS1": "MLS (United States)", "BRA1": "Série A (Brazil)", "ARG1": "Torneo Apertura (Argentina)",
    "MEX1": "Liga MX (Mexico)", "JAP1": "J1 League (Japan)", "RSK1": "K League 1 (South Korea)",
    "AUS1": "A-League Men (Australia)",
}
League = Enum("League", {k: k for k in LEAGUES}, type=str)
Metric = Enum("Metric", {m: m for m in ALL_METRICS}, type=str)

METRIC_DESCRIPTIONS = {
    "np_goals": "non-penalty goals per 90",
    "np_xg": "non-penalty expected goals per 90",
    "xa": "expected assists per 90 (xG of shots created)",
    "shots": "shots per 90 (excl. penalties)",
    "key_passes": "passes leading to a shot, per 90",
    "prog_passes": "completed passes moving the ball >= 25% closer to goal, per 90",
    "prog_carries": "carries of >= 5 m moving the ball >= 25% closer to goal, per 90",
    "final_third_passes": "completed passes into the final third, per 90",
    "box_passes": "completed passes into the penalty box, per 90",
    "dribbles_cmp": "successful dribbles per 90",
    "pressures": "pressures on the ball carrier per 90",
    "tackles_interceptions": "tackles + interceptions per 90",
    "recoveries": "ball recoveries per 90",
    "pass_cmp_pct": "pass completion % (open play)",
    "pass_cmp_under_pressure_pct": "pass completion % while under pressure",
    "aerial_win_pct": "aerial duels won %",
    "ground_duel_win_pct": "ground duels won % (tackles and dribbles)",
    "dribble_success_pct": "dribble success %",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class FindPlayerInput(_Strict):
    """Resolve a player name to Transfermarkt player ids."""
    name: str = Field(description="Player name as the scout wrote it, e.g. 'Lamine Yamal' or 'Rodri'.")
    limit: int = Field(5, ge=1, le=10, description="Max candidates, 1-10. Default 5.")


class MetricFilter(_Strict):
    metric: Metric = Field(description="Event metric to filter on.")
    percentile_min: int = Field(ge=0, le=100, description="Minimum percentile (0-100) within the player's position group.")


SortBy = Literal["market_value_desc", "market_value_asc", "age_asc", "minutes_desc", "metric_filters_desc"]


class SearchPlayersInput(_Strict):
    """Filter the player database. Every field is optional; omit what the scout didn't ask for."""
    position_groups: list[PositionGroup] | None = Field(
        None, description="Position groups: GK, CB, FB (full/wing-backs), DM, CM, AM, W (wingers/wide mids), ST.")
    sub_positions: list[SubPosition] | None = Field(
        None, description="Exact Transfermarkt positions, e.g. 'Left-Back'. Use for side-specific requests.")
    age_min: int | None = Field(None, ge=15, le=45, description="Minimum age in years (as of the data date).")
    age_max: int | None = Field(None, ge=15, le=45, description="Maximum age in years; 'under 23' means age_max 22.")
    value_min_eur: int | None = Field(None, ge=0, description="Minimum market value in euros.")
    value_max_eur: int | None = Field(None, ge=0, description="Maximum market value in euros; '€10M' is 10000000.")
    foot: Literal["left", "right", "both"] | None = Field(None, description="Preferred foot.")
    height_min_cm: int | None = Field(None, ge=150, le=210, description="Minimum height in cm.")
    contract_until_max: date | None = Field(
        None, description="Latest contract expiry (YYYY-MM-DD); 'contract ending by 2027' means 2027-12-31.")
    leagues: list[League] | None = Field(None, description="Current-club league ids: " + ", ".join(
        f"{k}={v}" for k, v in LEAGUES.items()))
    nationalities: list[str] | None = Field(None, description="Nationalities in English, e.g. 'Spain', 'Cote d\\'Ivoire'.")
    min_minutes: int | None = Field(None, ge=0, description="Minimum minutes played in 2025/26, all competitions.")
    metric_filters: list[MetricFilter] | None = Field(
        None, description="Event-metric percentile filters (max 6). Only players with StatsBomb event data can match.")
    sort_by: SortBy = Field("market_value_desc", description="Sort order. metric_filters_desc ranks by the mean "
                            "percentile of the metric filters.")
    limit: int = Field(10, ge=1, le=25, description="Rows to return, 1-25. Default 10.")


class PlayerIdInput(_Strict):
    player_id: int = Field(description="Transfermarkt player id from find_player or search_players.")


class SimilarPlayersInput(_Strict):
    player_id: int = Field(description="Transfermarkt player id of the reference player.")
    same_position: bool = Field(True, description="Only compare within the reference player's position group.")
    value_max_eur: int | None = Field(None, ge=0, description="Only return players valued at or below this.")
    age_max: int | None = Field(None, ge=15, le=45, description="Only return players at or below this age.")
    limit: int = Field(10, ge=1, le=15, description="Rows to return, 1-15. Default 10.")


class ComparePlayersInput(_Strict):
    player_ids: list[int] = Field(min_length=2, max_length=4, description="2 to 4 Transfermarkt player ids.")


_UNSUPPORTED = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
                "minLength", "maxLength", "minItems", "maxItems", "title", "default"}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema for strict tool use: unsupported keywords removed, every object closed."""
    def clean(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: clean(v) for k, v in node.items() if k not in _UNSUPPORTED}
            if out.get("type") == "object":
                out["additionalProperties"] = False
                out.setdefault("required", [])
            return out
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node

    schema = clean(model.model_json_schema())
    schema.pop("description", None)
    return schema
