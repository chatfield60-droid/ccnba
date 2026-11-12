"""GOAT-tier BDL data for the rate and minutes upgrades.

Tables:
  adv           per player-game advanced box (period 0 = full game): rebound chances, touches,
                passes, secondary assists, usage, possessions
  starters      actual starters per game (BDL /nba/v1/lineups, 2025-26 season on, after tip)
  proj_starters projected/confirmed starting fives (BDL /nba/v1/projected_lineups)
  game_periods  quarter scores per game (BDL /v1/games home_q1..q4, visitor_q1..q4)
"""
import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS adv (game_id INTEGER, player_id INTEGER, team_id INTEGER, date TEXT,
    season INTEGER, reb_ch INTEGER, reb_ch_off INTEGER, reb_ch_def INTEGER, touches INTEGER,
    passes INTEGER, sec_ast INTEGER, usage REAL, poss INTEGER, PRIMARY KEY (game_id, player_id));
CREATE TABLE IF NOT EXISTS starters (game_id INTEGER, player_id INTEGER, team_id INTEGER,
    starter INTEGER, PRIMARY KEY (game_id, player_id));
CREATE TABLE IF NOT EXISTS proj_starters (game_id INTEGER, team_id INTEGER, player_id INTEGER,
    pos TEXT, status TEXT, updated_at TEXT, PRIMARY KEY (game_id, team_id, player_id));
CREATE TABLE IF NOT EXISTS game_periods (game_id INTEGER PRIMARY KEY, home_q1 INTEGER, home_q2 INTEGER,
    home_q3 INTEGER, home_q4 INTEGER, vis_q1 INTEGER, vis_q2 INTEGER, vis_q3 INTEGER, vis_q4 INTEGER);
"""


def init(store):
    store.con.executescript(SCHEMA)


def sync_game_periods(client, store, seasons):
    init(store)
    rows = []
    for s in seasons:
        for g in client.games(seasons=[s]):
            if g.get("home_q1") is None:
                continue
            rows.append(dict(game_id=g["id"], home_q1=g.get("home_q1"), home_q2=g.get("home_q2"),
                             home_q3=g.get("home_q3"), home_q4=g.get("home_q4"), vis_q1=g.get("visitor_q1"),
                             vis_q2=g.get("visitor_q2"), vis_q3=g.get("visitor_q3"), vis_q4=g.get("visitor_q4")))
    return store._upsert("game_periods", rows)


def sync_advanced(client, store, seasons, start_date=None):
    init(store)
    n = 0
    for s in seasons:
        p = {"seasons[]": [s], "period": 0}
        if start_date:
            p["start_date"] = start_date
        rows = []
        for r in client.paginate("/nba/v2/stats/advanced", p):
            if r.get("period", 0) != 0 or (r.get("game") or {}).get("postseason"):
                continue
            g = r.get("game") or {}
            rows.append(dict(game_id=g.get("id"), player_id=(r.get("player") or {}).get("id"),
                             team_id=(r.get("team") or {}).get("id"), date=str(g.get("date", ""))[:10],
                             season=g.get("season"), reb_ch=r.get("rebound_chances_total"),
                             reb_ch_off=r.get("rebound_chances_off"), reb_ch_def=r.get("rebound_chances_def"),
                             touches=r.get("touches"), passes=r.get("passes"), sec_ast=r.get("secondary_assists"),
                             usage=r.get("usage_percentage"), poss=r.get("possessions")))
        n += store._upsert("adv", [x for x in rows if x["game_id"] and x["player_id"]])
    return n


def sync_starters(client, store, game_ids, batch=25):
    init(store)
    rows = []
    ids = list(game_ids)
    for i in range(0, len(ids), batch):
        for r in client.paginate("/nba/v1/lineups", {"game_ids[]": ids[i:i + batch]}):
            rows.append(dict(game_id=r["game_id"], player_id=r["player"]["id"],
                             team_id=(r.get("team") or {}).get("id") or r["player"].get("team_id"),
                             starter=int(bool(r.get("starter")))))
    return store._upsert("starters", rows)


def sync_projected(client, store, game_ids, batch=25):
    init(store)
    rows = []
    ids = list(game_ids)
    for i in range(0, len(ids), batch):
        for r in client.paginate("/nba/v1/projected_lineups", {"game_ids[]": ids[i:i + batch]}):
            for slot in r.get("lineup") or []:
                rows.append(dict(game_id=r["game_id"], team_id=r["team_id"], player_id=slot["player"]["id"],
                                 pos=slot.get("position"), status=r.get("status"), updated_at=r.get("updated_at")))
    return store._upsert("proj_starters", rows)


def load(store, table):
    init(store)
    return pd.read_sql_query(f"SELECT * FROM {table}", store.con)
