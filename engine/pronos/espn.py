"""Source principale : API publique d'ESPN (fonctionne aussi depuis un serveur cloud).

- tableau des matchs par date : calendrier, heures, scores, cotes DraftKings (moneyline) ;
- résumé par match : box score des équipes (possessions) et des joueurs.
"""
from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import requests

from .collect import ET, _possessions
from .teams import TEAMS, abbr

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
UA = {"User-Agent": "Mozilla/5.0 (pronos-nba personnel)"}
ESPN_ABBR = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX"}

_session = requests.Session()
_session.headers.update(UA)


def _get(url: str, params: dict | None = None, tries: int = 4) -> dict:
    for k in range(tries):
        try:
            r = _session.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"ESPN indisponible : {url} {params}")


def team_abbr(code: str) -> str:
    return abbr(ESPN_ABBR.get(code, code))


def american_to_decimal(s) -> float | None:
    try:
        v = float(str(s).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if v == 0:
        return None
    return round(1 + v / 100, 3) if v > 0 else round(1 + 100 / -v, 3)


def season_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def _moneyline(comp: dict) -> tuple[float | None, float | None, str | None]:
    for o in comp.get("odds") or []:
        ml = o.get("moneyline") or {}
        h, a = ml.get("home") or {}, ml.get("away") or {}
        # Cote de clôture si disponible (dernière avant le match), sinon ouverture.
        oh = american_to_decimal((h.get("close") or h.get("open") or {}).get("odds"))
        oa = american_to_decimal((a.get("close") or a.get("open") or {}).get("odds"))
        if oh and oa:
            return oh, oa, (o.get("provider") or {}).get("name", "Bookmaker")
        # Ancien format : homeTeamOdds.moneyLine
        oh = american_to_decimal((o.get("homeTeamOdds") or {}).get("moneyLine"))
        oa = american_to_decimal((o.get("awayTeamOdds") or {}).get("moneyLine"))
        if oh and oa:
            return oh, oa, (o.get("provider") or {}).get("name", "Bookmaker")
    return None, None, None


def fetch_day(d: date) -> list[dict]:
    data = _get(f"{BASE}/scoreboard", {"dates": d.strftime("%Y%m%d"), "limit": 50})
    out = []
    for ev in data.get("events", []):
        if (ev.get("season") or {}).get("type") != 2:  # saison régulière uniquement
            continue
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        home, away = team_abbr(teams["home"]["team"]["abbreviation"]), team_abbr(teams["away"]["team"]["abbreviation"])
        if home not in TEAMS or away not in TEAMS:
            continue
        tip = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
        done = comp["status"]["type"].get("completed", False)
        oh, oa, book = _moneyline(comp)
        out.append({
            "id": f"espn-{ev['id']}", "espn_id": ev["id"],
            "season": season_label((ev.get("season") or {}).get("year", tip.year + 1) - 1),
            "date": tip.astimezone(ET).date().isoformat(), "tip_utc": tip.isoformat(),
            "home": home, "away": away,
            "home_pts": int(teams["home"]["score"]) if done else None,
            "away_pts": int(teams["away"]["score"]) if done else None,
            "done": done, "odds_home": oh, "odds_away": oa, "book": book,
        })
    return out


def _stat(stats: list[dict], name: str) -> str:
    return next((s["displayValue"] for s in stats if s["name"] == name), "0")


def _pair(v: str) -> tuple[int, int]:
    a, _, b = v.partition("-")
    return int(a or 0), int(b or 0)


def fetch_summary(espn_id: str) -> dict:
    d = _get(f"{BASE}/summary", {"event": espn_id})
    bs = d.get("boxscore", {})
    teams = []
    for t in bs.get("teams", []):
        st = t.get("statistics", [])
        fgm, fga = _pair(_stat(st, "fieldGoalsMade-fieldGoalsAttempted"))
        fg3m, _ = _pair(_stat(st, "threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
        ftm, fta = _pair(_stat(st, "freeThrowsMade-freeThrowsAttempted"))
        teams.append({
            "team": team_abbr(t["team"]["abbreviation"]), "fgm": fgm, "fga": fga, "fg3m": fg3m,
            "ftm": ftm, "fta": fta, "oreb": int(_stat(st, "offensiveRebounds") or 0),
            "dreb": int(_stat(st, "defensiveRebounds") or 0),
            "tov": int(_stat(st, "totalTurnovers") or _stat(st, "turnovers") or 0),
        })
    players = []
    for block in bs.get("players", []):
        team = team_abbr(block["team"]["abbreviation"])
        for st in block.get("statistics", []):
            labels = st.get("labels") or st.get("names") or []
            for a in st.get("athletes", []):
                if a.get("didNotPlay") or not a.get("stats"):
                    continue
                s = dict(zip(labels, a["stats"]))
                try:
                    mins = float(str(s.get("MIN", "0")).split(":")[0] or 0)
                except ValueError:
                    mins = 0.0
                if mins <= 0:
                    continue
                fgm, fga = _pair(s.get("FG", "0-0"))
                ftm, fta = _pair(s.get("FT", "0-0"))
                num = lambda k: int(str(s.get(k, "0")).replace("+", "") or 0)
                players.append({
                    "id": int(a["athlete"]["id"]), "name": a["athlete"]["displayName"], "team": team,
                    "minutes": mins, "pts": num("PTS"), "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta,
                    "oreb": num("OREB"), "dreb": num("DREB"), "ast": num("AST"), "stl": num("STL"),
                    "blk": num("BLK"), "tov": num("TO"), "pf": num("PF"),
                })
    oh, oa, book = _moneyline({"odds": d.get("pickcenter") or []})
    return {"teams": teams, "players": players, "odds": (oh, oa, book) if oh and oa else None}


# ------------------------------------------------------------------- stockage

def store_games(con: sqlite3.Connection, games: list[dict]) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for g in games:
        con.execute(
            "INSERT INTO matchs (id, saison, date, heure_utc, domicile, exterieur, score_dom, score_ext, statut) "
            "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET date=excluded.date, "
            "heure_utc=excluded.heure_utc, score_dom=excluded.score_dom, score_ext=excluded.score_ext, "
            "statut=excluded.statut",
            (g["id"], g["season"], g["date"], g["tip_utc"], g["home"], g["away"], g["home_pts"],
             g["away_pts"], "termine" if g["done"] else "prevu"))
        if g["odds_home"] and g["odds_away"]:
            # Cotes des matchs passés : datées de l'heure du match (dernières connues avant).
            stamp = g["tip_utc"] if g["done"] else now
            con.execute("INSERT OR REPLACE INTO cotes VALUES (?,?,?,?,?)",
                        (g["id"], g["book"], g["odds_home"], g["odds_away"], stamp))
    con.commit()


def store_summary(con: sqlite3.Connection, gid: str, summ: dict, scores: dict[str, int], tip: str | None = None) -> None:
    if summ.get("odds") and tip:
        oh, oa, book = summ["odds"]
        con.execute("INSERT OR IGNORE INTO cotes VALUES (?,?,?,?,?)", (gid, book, oh, oa, tip))
    for t in summ["teams"]:
        con.execute("INSERT OR REPLACE INTO stats_equipe_match VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (gid, t["team"], scores.get(t["team"]), _possessions(t["fga"], t["oreb"], t["tov"], t["fta"]),
                     t["fgm"], t["fga"], t["fg3m"], t["fta"], t["ftm"], t["oreb"], t["dreb"], t["tov"]))
    for p in summ["players"]:
        con.execute("INSERT OR REPLACE INTO stats_joueur_match VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (gid, p["id"], p["team"], p["minutes"], p["pts"], p["fgm"], p["fga"], p["ftm"], p["fta"],
                     p["oreb"], p["dreb"], p["ast"], p["stl"], p["blk"], p["tov"], p["pf"]))
        con.execute("INSERT INTO joueurs (id, nom, equipe) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET "
                    "nom=excluded.nom, equipe=excluded.equipe", (p["id"], p["name"], p["team"]))


def sync_dates(con: sqlite3.Connection, days: list[date], workers: int = 8) -> list[dict]:
    """Tableau des matchs pour chaque date (en parallèle), puis enregistrement."""
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(fetch_day, days))
    games = [g for day in results for g in day]
    store_games(con, games)
    return games


def sync_boxscores(con: sqlite3.Connection, workers: int = 8, progress: bool = True) -> int:
    """Box scores des matchs terminés qui n'en ont pas encore."""
    rows = con.execute("""SELECT id, heure_utc, domicile, exterieur, score_dom, score_ext FROM matchs
        WHERE statut='termine' AND id LIKE 'espn-%'
        AND id NOT IN (SELECT match_id FROM stats_equipe_match WHERE fga IS NOT NULL)""").fetchall()
    todo = [(r["id"], r["heure_utc"], {r["domicile"]: r["score_dom"], r["exterieur"]: r["score_ext"]}) for r in rows]

    def job(item):
        gid, tip, scores = item
        try:
            return gid, tip, scores, fetch_summary(gid.removeprefix("espn-"))
        except RuntimeError:
            return gid, tip, scores, None

    n = 0
    with ThreadPoolExecutor(workers) as ex:
        for gid, tip, scores, summ in ex.map(job, todo):
            if summ and len(summ["teams"]) == 2:
                store_summary(con, gid, summ, scores, tip)
                n += 1
                if n % 250 == 0:
                    con.commit()
                    if progress:
                        print(f"  box scores : {n}/{len(todo)}", flush=True)
    con.commit()
    return n


def season_days(start_year: int, today: date | None = None) -> list[date]:
    """Du 1er octobre au 30 avril (saison régulière), sans dépasser aujourd'hui + 10 jours."""
    first, last = date(start_year, 10, 1), date(start_year + 1, 4, 30)
    if today:
        last = min(last, today + timedelta(days=10))
    return [first + timedelta(days=k) for k in range((last - first).days + 1)]
