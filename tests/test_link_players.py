import pandas as pd

from data.link_players import country, link, name_score, norm


def test_norm_strips_accents_and_punctuation():
    assert norm("Éder Militão") == "eder militao"
    assert norm("Salem Al-Dawsari") == "salem al dawsari"
    assert norm("Martin Ødegaard") == "martin odegaard"
    assert norm(None) == ""


def test_country_aliases():
    assert country("Côte d'Ivoire") == "Cote d'Ivoire"
    assert country("Korea\xa0(South)") == "Korea, South"
    assert country("Spain") == "Spain"


def test_name_score_prefers_exact_over_one_token_overlap():
    assert name_score(["Alisson", "Alisson Ramsés Becker"], "Alisson") > name_score(
        ["Alisson", "Alisson Ramsés Becker"], "Alisson Santos")
    assert name_score(["Lamine Yamal Nasraoui Ebana"], "Lamine Yamal") >= 100
    assert name_score(["Dayotchanculle Upamecano"], "Dayot Upamecano") >= 92


def _tm():
    return pd.DataFrame([
        {"player_id": 10, "name": "Luis Díaz", "nationality": "Colombia", "international_caps": 60,
         "highest_market_value_eur": 85_000_000},
        {"player_id": 11, "name": "Luis Díaz", "nationality": "Colombia", "international_caps": 0,
         "highest_market_value_eur": 300_000},
        {"player_id": 20, "name": "Rodri", "nationality": "Spain", "international_caps": 50,
         "highest_market_value_eur": 130_000_000},
        {"player_id": 30, "name": "Jan Novak", "nationality": "Slovakia", "international_caps": 3,
         "highest_market_value_eur": 1_000_000},
    ])


def _sb(rows):
    return pd.DataFrame(rows)


def test_link_breaks_namesake_ties_with_caps_and_matches_nickname():
    sb = _sb([
        {"sb_player_id": 1, "player_name": "Luis Fernando Díaz Marulanda", "player_nickname": "Luis Díaz",
         "country": "Colombia", "teams": ["Colombia"]},
        {"sb_player_id": 2, "player_name": "Rodrigo Hernández Cascante", "player_nickname": "Rodri",
         "country": "Spain", "teams": ["Spain"]},
        {"sb_player_id": 3, "player_name": "Nobody Known", "player_nickname": None,
         "country": "Spain", "teams": ["Spain"]},
    ])
    out = link(sb, _tm(), {}).set_index("sb_player_id")
    assert out.loc[1, "tm_player_id"] == 10
    assert out.loc[2, "tm_player_id"] == 20
    assert out.loc[3, "method"] == "unmatched"


def test_nickname_beats_surname_hidden_in_full_name():
    tm = pd.DataFrame([
        {"player_id": 40, "name": "Dani Olmo", "nationality": "Spain", "international_caps": 50,
         "highest_market_value_eur": 60_000_000},
        {"player_id": 41, "name": "Daniel Carvajal", "nationality": "Spain", "international_caps": 50,
         "highest_market_value_eur": 60_000_000},
    ])
    sb = _sb([
        {"sb_player_id": 5, "player_name": "Daniel Olmo Carvajal", "player_nickname": "Daniel Olmo",
         "country": "Spain", "teams": ["Spain"]},
        {"sb_player_id": 6, "player_name": "Daniel Carvajal Ramos", "player_nickname": "Dani Carvajal",
         "country": "Spain", "teams": ["Spain"]},
    ])
    out = link(sb, tm, {}).set_index("sb_player_id")
    assert out.loc[5, "tm_player_id"] == 40
    assert out.loc[6, "tm_player_id"] == 41


def test_one_tm_player_is_never_claimed_twice():
    tm = _tm()
    sb = _sb([
        {"sb_player_id": 7, "player_name": "Rodrigo Hernández Cascante", "player_nickname": "Rodri",
         "country": "Spain", "teams": ["Spain"]},
        {"sb_player_id": 8, "player_name": "Rodri", "player_nickname": None, "country": "Spain", "teams": ["Spain"]},
    ])
    out = link(sb, tm, {})
    assert out["tm_player_id"].dropna().tolist() == [20]
    assert out.set_index("sb_player_id").loc[8, "method"] == "conflict"


def test_link_without_country_needs_club_agreement():
    sb = _sb([{"sb_player_id": 4, "player_name": "Jan Novak", "player_nickname": None,
               "country": "Atlantis", "teams": ["FC Slovan"]}])
    assert link(sb, _tm(), {}).loc[0, "method"] == "unmatched"
    out = link(sb, _tm(), {30: {"slovan bratislava"}})
    assert out.loc[0, "tm_player_id"] == 30 and out.loc[0, "method"] == "name+club"
