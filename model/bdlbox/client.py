"""Thin BALLDONTLIE NBA client: auth header, cursor pagination, rate limiting, retries."""
import time
import logging

import requests

from .config import BASE_URL, Settings

log = logging.getLogger("bdlbox")


class TierError(RuntimeError):
    pass


class BDLClient:
    def __init__(self, settings: Settings, session=None):
        if not settings.api_key:
            raise RuntimeError("Set BDL_API_KEY (get one at app.balldontlie.io).")
        self.s = settings
        self.session = session or requests.Session()
        self._min_interval = 60.0 / settings.rpm * 1.05
        self._last = 0.0

    def _get(self, path, params=None):
        url = BASE_URL + path
        for attempt in range(6):
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            r = self.session.get(url, params=params or {}, timeout=30,
                                 headers={"Authorization": self.s.api_key})
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401:
                raise TierError(f"401 on {path}: bad key or tier '{self.s.tier}' lacks this endpoint.")
            if r.status_code in (429, 500, 503):
                back = min(60, 2 ** attempt * 2)
                log.warning("%s on %s, retry in %ss", r.status_code, path, back)
                time.sleep(back)
                continue
            raise RuntimeError(f"{r.status_code} on {path}: {getattr(r, 'text', '')[:300]}")
        raise RuntimeError(f"gave up on {path} after retries")

    def paginate(self, path, params=None):
        params = dict(params or {})
        params.setdefault("per_page", 100)
        while True:
            body = self._get(path, params)
            for row in body.get("data", []):
                yield row
            nxt = (body.get("meta") or {}).get("next_cursor")
            if not nxt:
                return
            params["cursor"] = nxt

    # ---- endpoints (tier in comment) ----
    def teams(self):                                   # Free
        return self._get("/v1/teams")["data"]

    def games(self, seasons=None, start_date=None, end_date=None, dates=None):  # Free
        p = {}
        if seasons: p["seasons[]"] = list(seasons)
        if dates: p["dates[]"] = list(dates)
        if start_date: p["start_date"] = start_date
        if end_date: p["end_date"] = end_date
        return list(self.paginate("/v1/games", p))

    def stats(self, seasons=None, start_date=None, end_date=None, game_ids=None, period=None):  # ALL-STAR
        p = {"season_type": "regular"}
        if period is not None: p["period"] = int(period)   # 1-4 quarters, completed games only
        if seasons: p["seasons[]"] = list(seasons)
        if start_date: p["start_date"] = start_date
        if end_date: p["end_date"] = end_date
        if game_ids: p["game_ids[]"] = list(game_ids)
        return list(self.paginate("/v1/stats", p))

    def active_players(self):                          # ALL-STAR
        return list(self.paginate("/v1/players/active"))

    def injuries(self):                                # ALL-STAR
        return list(self.paginate("/v1/player_injuries"))
