"""Collecte : résultats, box scores, calendrier, cotes.

NBA.com bloque souvent les serveurs cloud : à lancer depuis ton PC (connexion domestique).
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from .teams import TEAMS, abbr, from_full_name

ET = ZoneInfo("America/New_York")
SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
ODDS_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
UA = {"User-Agent": "Mozilla/5.0 (pronos-nba personnel)", "Referer": "https://www.nba.com/"}


def season_of(d: date) -> str:
    y = d.year if d.month >= 8 else d.year - 1
    return f"{y}-{(y + 1) % 100:02d}"


def _possessions(fga, oreb, tov, fta):
    return fga - oreb + tov + 0.44 * fta


# --------------------------------------------------------------------------- nba_api

def fetch_team_logs(season: str) -> pd.DataFrame:
    """Une ligne par équipe et par match (saison régulière), via nba_api."""
    from nba_api.stats.endpoints import leaguegamelog

    df = leaguegamelog.LeagueGameLog(
        season=season, season_type_all_star="Regular Season",
        player_or_team_abbreviation="T", timeout=60,
    ).get_data_frames()[0]
    time.sleep(1)
    return df


def fetch_player_logs(season: str) -> pd.DataFrame:
    from nba_api.stats.endpoints import leaguegamelog

    df = leaguegamelog.LeagueGameLog(
        season=season, season_type_all_star="Regular Season",
        player_or_team_abbreviation="P", timeout=90,
    ).get_data_frames()[0]
    time.sleep(1)
    return df


def store_team_logs(con: sqlite3.Connection, season: str, df: pd.DataFrame) -> int:
    n = 0
    for gid, g in df.groupby("GAME_ID"):
        if len(g) != 2:
            continue
        home = g[g["MATCHUP"].str.contains(" vs. ")]
        away = g[g["MATCHUP"].str.contains(" @ ")]
        if home.empty or away.empty:
            continue
        h, a = home.iloc[0], away.iloc[0]
        d = pd.to_datetime(h["GAME_DATE"]).date().isoformat()
        con.execute(
            "INSERT INTO matchs (id, saison, date, domicile, exterieur, score_dom, score_ext, statut) "
            "VALUES (?,?,?,?,?,?,?,'termine') ON CONFLICT(id) DO UPDATE SET "
            "score_dom=excluded.score_dom, score_ext=excluded.score_ext, statut='termine'",
            (gid, season, d, abbr(h["TEAM_ABBREVIATION"]), abbr(a["TEAM_ABBREVIATION"]),
             int(h["PTS"]), int(a["PTS"])),
        )
        for r in (h, a):
            con.execute(
                "INSERT OR REPLACE INTO stats_equipe_match VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (gid, abbr(r["TEAM_ABBREVIATION"]), int(r["PTS"]),
                 _possessions(r["FGA"], r["OREB"], r["TOV"], r["FTA"]),
                 int(r["FGM"]), int(r["FGA"]), int(r["FG3M"]), int(r["FTA"]), int(r["FTM"]),
                 int(r["OREB"]), int(r["DREB"]), int(r["TOV"])),
            )
        n += 1
    con.commit()
    return n


def store_player_logs(con: sqlite3.Connection, df: pd.DataFrame) -> int:
    rows = [
        (r.GAME_ID, int(r.PLAYER_ID), abbr(r.TEAM_ABBREVIATION), float(r.MIN or 0), int(r.PTS),
         int(r.FGM), int(r.FGA), int(r.FTM), int(r.FTA), int(r.OREB), int(r.DREB), int(r.AST),
         int(r.STL), int(r.BLK), int(r.TOV), int(r.PF))
        for r in df.itertuples()
    ]
    con.executemany("INSERT OR REPLACE INTO stats_joueur_match VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    names = {(int(r.PLAYER_ID), r.PLAYER_NAME, abbr(r.TEAM_ABBREVIATION)) for r in df.itertuples()}
    con.executemany(
        "INSERT INTO joueurs (id, nom, equipe) VALUES (?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET nom=excluded.nom, equipe=excluded.equipe", list(names))
    con.commit()
    return len(rows)


# --------------------------------------------------------------- Basketball-Reference

def fetch_bref_season(end_year: int) -> pd.DataFrame:
    """Secours pour l'historique : scores seulement (possessions estimées ensuite)."""
    months = ["october", "november", "december", "january", "february", "march", "april"]
    frames = []
    for m in months:
        url = f"https://www.basketball-reference.com/leagues/NBA_{end_year}_games-{m}.html"
        try:
            frames.append(pd.read_html(url)[0])
        except Exception:
            continue
        time.sleep(3.5)  # le site limite à ~20 requêtes / minute
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def store_bref_season(con: sqlite3.Connection, season: str, df: pd.DataFrame, pace: float = 99.0) -> int:
    n = 0
    if df.empty:
        return 0
    # Colonnes : Date, Start (ET), Visitor/Neutral, PTS, Home/Neutral, PTS.1, ...
    df = df[pd.to_numeric(df.iloc[:, 3], errors="coerce").notna()]
    for rec in df.itertuples(index=False):
        visitor, home = from_full_name(str(rec[2])), from_full_name(str(rec[4]))
        if not visitor or not home:
            continue
        d = pd.to_datetime(rec[0]).date().isoformat()
        gid = f"bref-{d}-{home}"
        v_pts, h_pts = int(float(rec[3])), int(float(rec[5]))
        con.execute("INSERT OR REPLACE INTO matchs (id, saison, date, domicile, exterieur, score_dom, score_ext, statut) "
                    "VALUES (?,?,?,?,?,?,?,'termine')",
                    (gid, season, d, home, visitor, h_pts, v_pts))
        for team, pts in ((home, h_pts), (visitor, v_pts)):
            con.execute("INSERT OR REPLACE INTO stats_equipe_match (match_id, equipe, points, possessions) VALUES (?,?,?,?)",
                        (gid, team, int(pts), pace))
        n += 1
    con.commit()
    return n


# ------------------------------------------------------------------------ calendrier

def fetch_schedule() -> list[dict]:
    import requests

    data = requests.get(SCHEDULE_URL, headers=UA, timeout=30).json()
    season = data["leagueSchedule"]["seasonYear"]
    games = []
    for day in data["leagueSchedule"]["gameDates"]:
        for g in day["games"]:
            gid = g["gameId"]
            if not gid.startswith("002"):  # saison régulière uniquement
                continue
            tip = g.get("gameDateTimeUTC")
            tip_dt = datetime.fromisoformat(tip.replace("Z", "+00:00")) if tip else None
            games.append({
                "id": gid, "season": season,
                "date": (tip_dt.astimezone(ET).date() if tip_dt else
                         datetime.strptime(g["gameDateEst"][:10], "%Y-%m-%d").date()).isoformat(),
                "tip_utc": tip_dt.isoformat() if tip_dt else None,
                "home": abbr(g["homeTeam"]["teamTricode"]),
                "away": abbr(g["awayTeam"]["teamTricode"]),
            })
    return games


def store_schedule(con: sqlite3.Connection, games: list[dict]) -> int:
    for g in games:
        if g["home"] not in TEAMS or g["away"] not in TEAMS:
            continue
        con.execute(
            "INSERT INTO matchs (id, saison, date, heure_utc, domicile, exterieur) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET heure_utc=excluded.heure_utc, date=excluded.date",
            (g["id"], g["season"], g["date"], g["tip_utc"], g["home"], g["away"]))
    con.commit()
    return len(games)


# ----------------------------------------------------------------------------- cotes

def fetch_odds(api_key: str | None = None, bookmaker: str | None = None) -> list[dict]:
    """Cotes vainqueur via The Odds API (offre gratuite : 500 requêtes / mois)."""
    import requests

    api_key = api_key or os.environ.get("ODDS_API_KEY")
    if not api_key:
        return []
    bookmaker = bookmaker or os.environ.get("ODDS_BOOKMAKER", "betclic")
    resp = requests.get(ODDS_URL, params={
        "apiKey": api_key, "regions": "eu,fr", "markets": "h2h", "oddsFormat": "decimal",
    }, timeout=30)
    resp.raise_for_status()
    out = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for ev in resp.json():
        home, away = from_full_name(ev["home_team"]), from_full_name(ev["away_team"])
        books = ev.get("bookmakers", [])
        chosen = next((b for b in books if b["key"] == bookmaker), books[0] if books else None)
        if not chosen or not home or not away:
            continue
        prices = {o["name"]: o["price"] for o in chosen["markets"][0]["outcomes"]}
        out.append({
            "home": home, "away": away, "bookmaker": chosen["title"],
            "odds_home": prices.get(ev["home_team"]), "odds_away": prices.get(ev["away_team"]),
            "date": datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00")).astimezone(ET).date().isoformat(),
            "releve": now,
        })
    return out


def store_odds(con: sqlite3.Connection, odds: list[dict]) -> int:
    n = 0
    for o in odds:
        row = con.execute("SELECT id FROM matchs WHERE date=? AND domicile=? AND exterieur=?",
                          (o["date"], o["home"], o["away"])).fetchone()
        if row and o["odds_home"] and o["odds_away"]:
            con.execute("INSERT OR REPLACE INTO cotes VALUES (?,?,?,?,?)",
                        (row["id"], o["bookmaker"], o["odds_home"], o["odds_away"], o["releve"]))
            n += 1
    con.commit()
    return n


# ---------------------------------------------------------------------- chargement

def load_games(con: sqlite3.Connection) -> pd.DataFrame:
    """Tous les matchs (passés et à venir) avec possessions moyennes des deux équipes."""
    df = pd.read_sql_query("""
        SELECT m.id, m.saison AS season, m.date, m.heure_utc AS tip_utc,
               m.domicile AS home, m.exterieur AS away,
               m.score_dom AS home_pts, m.score_ext AS away_pts,
               (SELECT AVG(possessions) FROM stats_equipe_match s WHERE s.match_id = m.id) AS poss
        FROM matchs m ORDER BY m.date, m.id""", con)
    df["date"] = pd.to_datetime(df["date"])
    df["poss"] = df["poss"].fillna(99.0)
    return df


def load_player_logs(con: sqlite3.Connection, season: str) -> pd.DataFrame:
    df = pd.read_sql_query("""
        SELECT m.date, s.match_id, s.joueur_id AS player_id, j.nom AS name, s.equipe AS team, s.minutes,
               s.pts, s.fgm, s.fga, s.ftm, s.fta, s.oreb, s.dreb, s.ast, s.stl, s.blk, s.tov, s.pf
        FROM stats_joueur_match s JOIN matchs m ON m.id = s.match_id
        LEFT JOIN joueurs j ON j.id = s.joueur_id WHERE m.saison = ?""", con, params=(season,))
    df["date"] = pd.to_datetime(df["date"])
    return df
