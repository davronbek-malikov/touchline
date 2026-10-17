import duckdb

from data.build_warehouse import build_market_layer


def _fake_tm(path):
    con = duckdb.connect(str(path))
    con.execute("""CREATE TABLE competitions AS SELECT * FROM (VALUES
        ('GB1', 'premier-league', 'England', 'domestic_league', 'europa'),
        ('CL', 'uefa-champions-league', NULL, 'international_cup', 'europa'))
        t(competition_id, name, country_name, type, confederation)""")
    con.execute("""CREATE TABLE players AS SELECT * FROM (VALUES
        (1, 'Left Back Kid', TIMESTAMP '2004-03-01', 'Defender', 'Left-Back', 'left', 178, 'England', 'England',
         '5', 'Some FC', 'GB1', TIMESTAMP '2027-06-30', 8000000, 9000000, 2, 0, '2025', 'img', 'url'),
        (3, 'Birthday Next Week', TIMESTAMP '2007-07-13', 'Attack', 'Right Winger', 'left', 180, 'Spain', 'Spain',
         '5', 'Some FC', 'GB1', NULL, 1, 1, NULL, NULL, '2025', 'img', 'url'),
        (4, 'Late In Year', TIMESTAMP '1985-09-09', 'Midfield', 'Central Midfield', 'right', 172, 'Croatia', 'Croatia',
         '5', 'Some FC', 'GB1', NULL, 1, 1, NULL, NULL, '2025', 'img', 'url'),
        (2, 'Old Striker', TIMESTAMP '1990-01-01', 'Attack', 'Centre-Forward', '', 185, 'Spain', 'Spain',
         '6', 'Other FC', 'GB1', NULL, 500000, 40000000, NULL, NULL, '2022', 'img', 'url'))
        t(player_id, name, date_of_birth, position, sub_position, foot, height_in_cm, country_of_citizenship,
          country_of_birth, current_club_id, current_club_name, current_club_domestic_competition_id,
          contract_expiration_date, market_value_in_eur, highest_market_value_in_eur, international_caps,
          international_goals, last_season, image_url, url)""")
    con.execute("""CREATE TABLE appearances AS SELECT * FROM (VALUES
        (1, DATE '2025-08-20', 'GB1', 90, 0, 1, 0, 0),
        (1, DATE '2026-02-10', 'GB1', 70, 1, 0, 1, 0),
        (1, DATE '2025-05-01', 'CL', 90, 0, 0, 0, 0))
        t(player_id, date, competition_id, minutes_played, goals, assists, yellow_cards, red_cards)""")
    con.execute("""CREATE TABLE player_valuations AS SELECT * FROM (VALUES
        (1, DATE '2025-12-01', 8000000, 'Some FC', 5, 'GB1'))
        t(player_id, date, market_value_in_eur, current_club_name, current_club_id, player_club_domestic_competition_id)""")
    con.close()


def test_market_layer(tmp_path):
    tm = tmp_path / "tm.duckdb"
    _fake_tm(tm)
    con = duckdb.connect(str(tmp_path / "wh.duckdb"))
    build_market_layer(con, tm)

    p = con.execute("SELECT age, position_group, foot, is_active, league_country FROM players WHERE player_id = 1").fetchone()
    assert p == (22, "FB", "left", True, "England")
    q = con.execute("SELECT position_group, foot, is_active FROM players WHERE player_id = 2").fetchone()
    assert q == ("ST", None, False)

    # Ages are whole years on the data date (2026-07-06), not rounded.
    ages = dict(con.execute("SELECT player_id, age FROM players WHERE player_id IN (3, 4)").fetchall())
    assert ages == {3: 18, 4: 40}

    seasons = con.execute(
        "SELECT season, competition_id, minutes, goals FROM player_seasons WHERE player_id = 1 ORDER BY season, competition_id"
    ).fetchall()
    assert seasons == [(2024, "CL", 90, 0), (2025, "GB1", 160, 1)]
    assert con.execute("SELECT value FROM meta WHERE key = 'data_as_of'").fetchone() == ("2026-07-06",)
