"""SQLite cache of BDL data, flattened from the documented response shapes."""
import sqlite3
from datetime import datetime, timezone

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (team_id INTEGER PRIMARY KEY, abbr TEXT, full_name TEXT,
    conference TEXT, division TEXT);
CREATE TABLE IF NOT EXISTS games (game_id INTEGER PRIMARY KEY, date TEXT, datetime TEXT,
    season INTEGER, status TEXT, status_state TEXT, postseason INTEGER, postponed INTEGER,
    home_team_id INTEGER, visitor_team_id INTEGER, home_score INTEGER, visitor_score INTEGER);
CREATE TABLE IF NOT EXISTS player_stats (stat_id INTEGER PRIMARY KEY, game_id INTEGER,
    date TEXT, season INTEGER, postseason INTEGER, player_id INTEGER, team_id INTEGER,
    opp_id INTEGER, is_home INTEGER, first_name TEXT, last_name TEXT, position TEXT,
    min REAL, fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER, ftm INTEGER, fta INTEGER,
    oreb INTEGER, dreb INTEGER, reb INTEGER, ast INTEGER, stl INTEGER, blk INTEGER,
    tov INTEGER, pf INTEGER, pts INTEGER, plus_minus INTEGER);
CREATE INDEX IF NOT EXISTS ix_ps_date ON player_stats(date);
CREATE TABLE IF NOT EXISTS player_stats_q1 (stat_id INTEGER, game_id INTEGER,
    date TEXT, season INTEGER, postseason INTEGER, player_id INTEGER, team_id INTEGER,
    opp_id INTEGER, is_home INTEGER, first_name TEXT, last_name TEXT, position TEXT,
    min REAL, fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER, ftm INTEGER, fta INTEGER,
    oreb INTEGER, dreb INTEGER, reb INTEGER, ast INTEGER, stl INTEGER, blk INTEGER,
    tov INTEGER, pf INTEGER, pts INTEGER, plus_minus INTEGER, PRIMARY KEY (game_id, player_id));
CREATE TABLE IF NOT EXISTS active_players (player_id INTEGER PRIMARY KEY, first_name TEXT,
    last_name TEXT, position TEXT, team_id INTEGER, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS injuries (player_id INTEGER, team_id INTEGER, status TEXT,
    return_date TEXT, description TEXT, fetched_at TEXT);
"""


def parse_min(v):
    """BDL `min` is a string: '30', '30:12', '', '00', or null."""
    if v is None:
        return 0.0
    s = str(v).strip()
    if not s:
        return 0.0
    if ":" in s:
        a, b = s.split(":", 1)
        try:
            return float(a) + float(b) / 60.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _tid(obj, key_obj, key_id):
    if obj.get(key_obj) and isinstance(obj[key_obj], dict):
        return obj[key_obj].get("id")
    return obj.get(key_id)


def flatten_game(g):
    return dict(
        game_id=g["id"], date=g["date"][:10], datetime=g.get("datetime"), season=g["season"],
        status=g.get("status"), status_state=g.get("status_state"),
        postseason=int(bool(g.get("postseason"))), postponed=int(bool(g.get("postponed"))),
        home_team_id=_tid(g, "home_team", "home_team_id"),
        visitor_team_id=_tid(g, "visitor_team", "visitor_team_id"),
        home_score=g.get("home_team_score"), visitor_score=g.get("visitor_team_score"),
    )


def flatten_stat(s):
    g, p, t = s["game"], s["player"], s.get("team") or {}
    team_id = t.get("id") or p.get("team_id")
    home, vis = g.get("home_team_id"), g.get("visitor_team_id")
    is_home = int(team_id == home)
    return dict(
        stat_id=s["id"], game_id=g["id"], date=g["date"][:10], season=g["season"],
        postseason=int(bool(g.get("postseason"))), player_id=p["id"], team_id=team_id,
        opp_id=vis if is_home else home, is_home=is_home,
        first_name=p.get("first_name"), last_name=p.get("last_name"), position=p.get("position") or "",
        min=parse_min(s.get("min")),
        **{k: (s.get(k) or 0) for k in ["fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb",
                                        "dreb", "reb", "ast", "stl", "blk", "pf", "pts"]},
        tov=s.get("turnover") or 0, plus_minus=s.get("plus_minus"),
    )


class Store:
    def __init__(self, path):
        self.con = sqlite3.connect(path)
        self.con.executescript(SCHEMA)

    def _upsert(self, table, rows):
        if not rows:
            return 0
        cols = list(rows[0].keys())
        q = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        self.con.executemany(q, [tuple(r[c] for c in cols) for r in rows])
        self.con.commit()
        return len(rows)

    def upsert_teams(self, teams):
        return self._upsert("teams", [dict(team_id=t["id"], abbr=t["abbreviation"],
                            full_name=t["full_name"], conference=t.get("conference"),
                            division=t.get("division")) for t in teams])

    def upsert_games(self, games):
        return self._upsert("games", [flatten_game(g) for g in games])

    def upsert_stats(self, stats, table="player_stats"):
        return self._upsert(table, [flatten_stat(s) for s in stats])

    def replace_active(self, players):
        now = datetime.now(timezone.utc).isoformat()
        self.con.execute("DELETE FROM active_players")
        return self._upsert("active_players", [dict(player_id=p["id"], first_name=p.get("first_name"),
                            last_name=p.get("last_name"), position=p.get("position") or "",
                            team_id=(p.get("team") or {}).get("id"), fetched_at=now) for p in players])

    def replace_injuries(self, inj):
        now = datetime.now(timezone.utc).isoformat()
        self.con.execute("DELETE FROM injuries")
        return self._upsert("injuries", [dict(player_id=i["player"]["id"], team_id=i["player"].get("team_id"),
                            status=i.get("status"), return_date=i.get("return_date"),
                            description=i.get("description"), fetched_at=now) for i in inj])

    def df(self, sql, params=()):
        return pd.read_sql_query(sql, self.con, params=params)

    def max_stat_date(self, season, table="player_stats"):
        r = self.con.execute(f"SELECT MAX(date) FROM {table} WHERE season=?", (season,)).fetchone()
        return r[0]
