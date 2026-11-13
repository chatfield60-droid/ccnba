"""Publish a small, public NBA score and schedule feed from BALLDONTLIE."""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = "https://api.balldontlie.io"
ET = ZoneInfo("America/New_York")


def fetch(path, params):
    rows, cursor, seen = [], None, set()
    while True:
        query = dict(params, per_page=100)
        if cursor is not None:
            query["cursor"] = cursor
        url = ROOT + path + "?" + urllib.parse.urlencode(query, doseq=True)
        for attempt in range(5):
            try:
                request = urllib.request.Request(url, headers={"Authorization": os.environ["BDL_API_KEY"]})
                with urllib.request.urlopen(request, timeout=30) as response:
                    body = json.load(response)
                break
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        rows.extend(body.get("data", []))
        cursor = (body.get("meta") or {}).get("next_cursor")
        if cursor is None:
            return rows
        if str(cursor) in seen:
            raise ValueError(f"Repeated cursor on {path}")
        seen.add(str(cursor))


def number(value):
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def normalize(game, now):
    day = str(game.get("date") or "")[:10]
    start = game.get("datetime") or game.get("date")
    try:
        tip = dt.datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        if tip.tzinfo is None:
            tip = tip.replace(tzinfo=dt.timezone.utc)
    except (ValueError, TypeError):
        tip = None
    status = str(game.get("status_state") or game.get("status") or "").lower()
    final = "final" in status or status == "post"
    live = "progress" in status or status == "in"
    if game.get("postponed"):
        state = "postponed"
    elif final and (tip is None and day < now.astimezone(ET).date().isoformat() or tip and tip <= now):
        state = "final"
    elif live and tip and tip <= now:
        state = "live"
    else:
        state = "scheduled"
    home, away = game.get("home_team") or {}, game.get("visitor_team") or {}
    return {
        "game_id": game.get("id"), "date": day, "starts_at": start,
        "status": state, "status_text": str(game.get("status") or ""),
        "home": home.get("abbreviation") or home.get("name") or "Home",
        "away": away.get("abbreviation") or away.get("name") or "Away",
        "home_score": number(game.get("home_team_score")) if state in ("final", "live") else None,
        "away_score": number(game.get("visitor_team_score")) if state in ("final", "live") else None,
    }


def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(ET).date()
    dates = [(today + dt.timedelta(days=i)).isoformat() for i in range(-7, 3)]
    games = fetch("/v1/games", {"dates[]": dates})
    rows = [normalize(g, now) for g in games]
    rows = [g for g in rows if g["game_id"] and g["date"] in dates]
    rows.sort(key=lambda g: (g["date"], str(g["starts_at"]), g["game_id"]))
    result = {"updated_at": now.isoformat(), "games": rows}
    path = Path("publish/games/live.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, allow_nan=False))
    print(f"Published {len(rows)} games: {sum(g['status']=='final' for g in rows)} final", file=sys.stderr)


if __name__ == "__main__":
    main()
