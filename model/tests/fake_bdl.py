"""Synthetic league served in the exact BDL JSON shapes, through a fake requests.Session.

This is plumbing/recovery test data only. None of it is real NBA data.
"""
import math
from datetime import date, timedelta
from urllib.parse import urlparse

import numpy as np

POS = ["G", "G", "F", "F", "C", "G", "F", "C", "G", "F", "C", "G", "F", "F"]
BASE_MIN = [34, 33, 32, 30, 28, 24, 22, 18, 14, 10, 8, 5, 3, 2]
RATE = {  # per on-floor possession, by position (synthetic)
    "G": dict(fg2a=.13, fg3a=.11, fta=.05, oreb=.01, dreb=.06, ast=.08, stl=.012, blk=.004, tov=.025, pf=.03),
    "F": dict(fg2a=.12, fg3a=.08, fta=.045, oreb=.025, dreb=.09, ast=.035, stl=.01, blk=.009, tov=.018, pf=.035),
    "C": dict(fg2a=.15, fg3a=.03, fta=.06, oreb=.05, dreb=.13, ast=.03, stl=.008, blk=.022, tov=.02, pf=.042),
}
PCT = {"G": (.52, .36, .82), "F": (.53, .355, .77), "C": (.60, .33, .68)}


class Resp:
    def __init__(self, code, body):
        self.status_code, self._b, self.text = code, body, ""

    def json(self):
        return self._b


class FakeLeague:
    def __init__(self, seed=1):
        rng = self.rng = np.random.default_rng(seed)
        self.teams = [dict(id=i + 1, conference="East" if i < 15 else "West", division="D", city=f"City{i+1}",
                           name=f"Team{i+1}", full_name=f"City{i+1} Team{i+1}", abbreviation=f"T{i+1:02d}")
                      for i in range(30)]
        self.tpace = {t["id"]: rng.normal(99, 2.5) for t in self.teams}
        self.tdef = {t["id"]: rng.normal(1.0, 0.04) for t in self.teams}
        self.players = []
        pid = 100
        for t in self.teams:
            for j in range(14):
                pos = POS[j]
                skill = {k: v * rng.lognormal(0, 0.25) * (0.74 if k in ("fg2a", "fg3a", "fta", "tov") else 1)
                         for k, v in RATE[pos].items()}
                if j < 2:  # stars use more
                    for k in ("fg2a", "fg3a", "fta", "ast"):
                        skill[k] *= 1.3
                pct = [min(.95, max(.05, p + rng.normal(0, .025))) for p in PCT[pos]]
                self.players.append(dict(id=pid, first_name=f"P{pid}", last_name=f"L{pid}", position=pos,
                                         team_id=t["id"], min=BASE_MIN[j] * rng.uniform(.9, 1.1),
                                         rate=skill, pct=pct))
                pid += 1
        self.games, self.stats = [], []
        self._play_season(2025, date(2025, 10, 21), 82)
        self._schedule_only(2026, date(2026, 10, 20))
        # offseason: trade player 100 (T01 star) to T02, add rookie to T03
        self.active = [dict(p, team_id=p["team_id"]) for p in self.players]
        self.active[0]["team_id"] = 2
        self.active.append(dict(id=99999, first_name="Rook", last_name="Ie", position="G", team_id=3))
        self.injuries = [dict(player={"id": 115, "first_name": "P115", "last_name": "L115",
                                      "position": "G", "team_id": 2},
                              return_date="Nov 1", description="synthetic", status="Out"),
                         dict(player={"id": 129, "first_name": "P129", "last_name": "L129",
                                      "position": "G", "team_id": 3},
                              return_date=None, description="synthetic", status="Questionable")]

    def _team_obj(self, tid):
        return dict(self.teams[tid - 1])

    def _pairings(self, start, n_days):
        rng = self.rng
        ids = [t["id"] for t in self.teams]
        for d in range(n_days):
            day = start + timedelta(days=d)
            k = int(rng.integers(4, 8))
            perm = rng.permutation(ids)[: 2 * k]
            for i in range(k):
                yield day, int(perm[2 * i]), int(perm[2 * i + 1])

    def _schedule_only(self, season, start):
        gid = 900000
        # pinned opening-night games so trade (T01->T02), injury (T02, T03) and rookie (T03) cases are on the slate
        pinned = [(start, 2, 1), (start, 3, 4)]
        rest = [(d, h, v) for d, h, v in self._pairings(start, 3) if not (d == start and {h, v} & {1, 2, 3, 4})]
        for day, h, v in pinned + rest:
            gid += 1
            self.games.append(self._game(gid, day, season, h, v, None, None, "7:00 pm ET", "scheduled"))

    def _game(self, gid, day, season, h, v, hs, vs, status, state):
        return dict(id=gid, date=day.isoformat(), season=season, status=status, status_state=state,
                    period=4 if state == "final" else 0, time="Final" if state == "final" else " ",
                    postseason=False, postponed=False, home_team_score=hs or 0, visitor_team_score=vs or 0,
                    datetime=f"{day.isoformat()}T23:00:00.000Z", home_team=self._team_obj(h),
                    visitor_team=self._team_obj(v), ist_stage=None)

    def _play_season(self, season, start, n_games):
        rng = self.rng
        roster = {t["id"]: [p for p in self.players if p["team_id"] == t["id"]] for t in self.teams}
        gid, sid = 500000, 1
        for day, h, v in self._pairings(start, 172):
            gid += 1
            pace = self.tpace[h] * self.tpace[v] / 99 + rng.normal(0, 4)
            ot = 5 if rng.random() < 0.06 else 0
            lines, score = {}, {}
            for tid, opp, home in ((h, v, True), (v, h, False)):
                pl = roster[tid]
                mins = np.array([max(0, p["min"] + rng.normal(0, 4)) for p in pl])
                mins[rng.random(len(pl)) < 0.07] = 0
                mins *= (240 + ot * 5) / mins.sum()
                mins = np.minimum(mins, 46)
                poss = pace * (48 + ot) / 48
                rows, pts_t = [], 0
                for p, m in zip(pl, mins):
                    on = poss * m / (48 + ot)
                    c = {k: int(rng.poisson(r * on * (self.tdef[opp] if k in ("fg2a", "fg3a", "ast") else 1)))
                         for k, r in p["rate"].items()}
                    hb = 1.01 if home else 0.99
                    fg2m = int(rng.binomial(c["fg2a"], min(.95, p["pct"][0] * hb)))
                    fg3m = int(rng.binomial(c["fg3a"], min(.9, p["pct"][1] * hb)))
                    ftm = int(rng.binomial(c["fta"], p["pct"][2]))
                    pts = 2 * fg2m + 3 * fg3m + ftm
                    pts_t += pts
                    mstr = "0" if m <= 0 else (f"{int(m)}:{int((m % 1) * 60):02d}" if rng.random() < .5 else str(int(round(m))))
                    rows.append(dict(id=sid, min=mstr, fgm=fg2m + fg3m, fga=c["fg2a"] + c["fg3a"],
                                     fg_pct=0, fg3m=fg3m, fg3a=c["fg3a"], fg3_pct=0, ftm=ftm, fta=c["fta"],
                                     ft_pct=0, oreb=c["oreb"], dreb=c["dreb"], reb=c["oreb"] + c["dreb"],
                                     ast=c["ast"], stl=c["stl"], blk=c["blk"], turnover=c["tov"], pf=c["pf"],
                                     pts=pts, plus_minus=0,
                                     player=dict(id=p["id"], first_name=p["first_name"], last_name=p["last_name"],
                                                 position=p["position"], team_id=tid),
                                     team=self._team_obj(tid)))
                    sid += 1
                lines[tid], score[tid] = rows, pts_t
            g = self._game(gid, day, season, h, v, score[h], score[v], "Final", "final")
            self.games.append(g)
            gl = dict(id=gid, date=g["date"], season=season, status="Final", status_state="final", period=4,
                      time="Final", postseason=False, postponed=False, home_team_score=score[h],
                      visitor_team_score=score[v], home_team_id=h, visitor_team_id=v, ist_stage=None)
            for tid in (h, v):
                for r in lines[tid]:
                    r["game"] = gl
                    self.stats.append(r)


def _q1_row(r, rng):
    """Synthetic first quarter: starters (30+ min) ~29% of their game, bench ~12%."""
    m = float(str(r["min"]).split(":")[0] or 0)
    sh = 0.29 if m >= 26 else 0.12
    q = dict(r)
    for k in ("pts", "reb", "ast", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "stl", "blk", "turnover", "pf"):
        q[k] = int(rng.binomial(int(r[k] or 0), sh))
    q["reb"] = q["oreb"] + q["dreb"]
    q["min"] = str(int(round(min(12, m * sh * 1.05))))
    return q


def _q1_rows(self, rows):
    if not hasattr(self, "_q1cache"):
        rng = np.random.default_rng(11)
        self._q1cache = {r["id"]: _q1_row(r, rng) for r in self.stats}
    return [self._q1cache[r["id"]] for r in rows]


FakeLeague.q1_rows = _q1_rows


class FakeSession:
    """Implements the subset of BDL routes the client uses, with cursor pagination."""

    def __init__(self, league: FakeLeague, tier="GOAT"):
        self.L, self.tier, self.calls = league, tier, 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        assert headers and headers.get("Authorization"), "missing auth header"
        path = urlparse(url).path
        p = params or {}
        if path == "/v1/teams":
            return Resp(200, {"data": self.L.teams})
        if path in ("/v1/stats", "/v1/players/active", "/v1/player_injuries") and self.tier == "FREE":
            return Resp(401, {})
        if path == "/v1/games":
            rows = [g for g in self.L.games if not p.get("seasons[]") or g["season"] in p["seasons[]"]]
        elif path == "/v1/stats":
            rows = [s for s in self.L.stats if (not p.get("seasons[]") or s["game"]["season"] in p["seasons[]"])
                    and (not p.get("start_date") or s["game"]["date"] >= p["start_date"])]
            if p.get("period") == 1:
                rows = self.L.q1_rows(rows)
        elif path == "/v1/players/active":
            rows = [dict(id=a["id"], first_name=a["first_name"], last_name=a["last_name"],
                         position=a["position"], team=self.L._team_obj(a["team_id"])) for a in self.L.active]
        elif path == "/v1/player_injuries":
            rows = self.L.injuries
        else:
            return Resp(404, {})
        per = min(int(p.get("per_page", 25)), 100)
        cur = int(p.get("cursor", 0))
        page = rows[cur: cur + per]
        nxt = cur + per if cur + per < len(rows) else None
        return Resp(200, {"data": page, "meta": {"next_cursor": nxt, "per_page": per}})
