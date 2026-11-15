"""Orchestration : prévisions du soir, journal, export JSON pour l'app mobile."""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import betting as B
from . import injuries as INJ
from . import ratings as R
from .collect import ET, load_games, load_player_logs, season_of
from .db import ROOT
from .model import Prediction, predict
from .players import absences_for, player_table

APP_DATA = [ROOT / "app" / "public" / "data", ROOT / "app" / "dist" / "data"]
PARAMS_FILE = ROOT / "data" / "params.json"
BACKTEST_FILE = ROOT / "data" / "backtest.json"


def load_params() -> R.Params:
    if PARAMS_FILE.exists():
        return R.Params(**json.loads(PARAMS_FILE.read_text()))
    return R.Params()


def ratings_asof(games: pd.DataFrame, day: pd.Timestamp, p: R.Params) -> R.Ratings:
    """Notes au matin de `day` : saisons précédentes enchaînées comme a priori."""
    season = season_of(day.date())
    return R.compute(games[games["season"] == season], day, _prior_for(games, season, p), p)


def tonight(con: sqlite3.Connection, day: pd.Timestamp | None = None) -> tuple[pd.Timestamp, list[dict]]:
    p = load_params()
    games = load_games(con)
    day = day or pd.Timestamp(datetime.now(ET).date())
    r = ratings_asof(games, day, p)
    season = season_of(day.date())
    sched = games[games["season"] == season]
    players = player_table(load_player_logs(con, season), day)
    inj = INJ.latest_for(con, day.date().isoformat())
    out = []
    for g in sched[sched["date"] == day].itertuples():
        pace = r.team(g.home)["pace"] * r.team(g.away)["pace"] / r.league_pace
        abs_ = absences_for(g.home, inj, players, pace) + absences_for(g.away, inj, players, pace) if len(players) else []
        pr = predict(g.home, g.away, day, r, p, schedule=sched, absences=abs_)
        odds = con.execute("SELECT bookmaker, cote_dom, cote_ext FROM cotes WHERE match_id=? ORDER BY releve DESC LIMIT 1",
                           (g.id,)).fetchone()
        out.append(game_payload(g.id, g.tip_utc, pr, dict(odds) if odds else None,
                                (g.home_pts, g.away_pts) if pd.notna(g.home_pts) else None))
    return day, out


def game_payload(gid: str, tip_utc: str | None, pr: Prediction, odds: dict | None, result) -> dict:
    d = pr.to_dict()
    ph, pa = pr.p_home, 1 - pr.p_home
    d.update({
        "id": gid, "tip_utc": tip_utc,
        "min_odds": {"home": B.min_odds(ph), "away": B.min_odds(pa)},
        "fair_odds": {"home": B.fair_odds(ph), "away": B.fair_odds(pa)},
        "odds": None, "p_book_home": None, "divergence": False,
        "verdict": {"home": "aucune", "away": "aucune"},
        "result": {"home": int(result[0]), "away": int(result[1])} if result else None,
    })
    if odds and odds.get("cote_dom") and odds.get("cote_ext"):
        pb = B.book_probability(odds["cote_dom"], odds["cote_ext"])
        d.update({
            "odds": {"book": odds["bookmaker"], "home": odds["cote_dom"], "away": odds["cote_ext"]},
            "p_book_home": round(pb, 4),
            "divergence": abs(pb - ph) > B.DIVERGENCE,
            "verdict": {"home": B.verdict(odds["cote_dom"], d["min_odds"]["home"]),
                        "away": B.verdict(odds["cote_ext"], d["min_odds"]["away"])},
        })
    return d


def journal(con: sqlite3.Connection, games: list[dict], version: str) -> int:
    """Enregistre la dernière prévision avant le match ; figée dès le coup d'envoi."""
    now = datetime.now(timezone.utc)
    n = 0
    for g in games:
        if g["tip_utc"] and datetime.fromisoformat(g["tip_utc"]) <= now:
            continue
        cur = con.execute(
            "INSERT OR REPLACE INTO previsions VALUES (?,?,?,?,?,?,?)",
            (g["id"], g["p_home"], g["spread"], json.dumps(g["factors"]), json.dumps(g["absences"]),
             version, now.isoformat(timespec="seconds")))
        n += cur.rowcount
    con.commit()
    return n


def ratings_payload(con: sqlite3.Connection, day: pd.Timestamp) -> dict:
    p = load_params()
    games = load_games(con)
    r = ratings_asof(games, day, p)
    season = season_of(day.date())
    sg = games[(games["season"] == season) & games["home_pts"].notna() & (games["date"] < day)]
    # Évolution sur les 15 derniers matchs : note nette au lendemain de chacun.
    trend_dates = sorted(sg["date"].unique())[-40:]
    snapshots = {}
    full_prior = _prior_for(games, season, p)
    for d in trend_dates:
        snapshots[d] = R.compute(games[games["season"] == season], pd.Timestamp(d) + pd.Timedelta(days=1), full_prior, p)
    teams = []
    for a in R.ABBRS:
        t = r.team(a)
        played = sg[(sg["home"] == a) | (sg["away"] == a)]["date"].tail(15)
        trend = [round(snapshots[d].team(a)["net"], 2) for d in played if d in snapshots]
        teams.append({"abbr": a, "off": round(t["off"], 1), "def": round(t["def"], 1),
                      "net": round(t["net"], 1), "pace": round(t["pace"], 1), "games": t["games"],
                      "trend": trend})
    teams.sort(key=lambda t: -t["net"])
    for i, t in enumerate(teams, 1):
        t["rank"] = i
    return {"date": day.date().isoformat(), "league": {"ortg": round(r.league_ortg, 1),
            "pace": round(r.league_pace, 1)}, "teams": teams}


def _prior_for(games: pd.DataFrame, season: str, p: R.Params) -> R.Ratings:
    prior = R.neutral_prior()
    for s, sg in games[games["season"] < season].groupby("season", sort=True):
        end = R.compute(sg, sg["date"].max() + pd.Timedelta(days=1), prior, p)
        prior = end.regressed(p.prior_regress)
    return prior


def record_payload(con: sqlite3.Connection) -> dict:
    rows = con.execute("""
        SELECT p.match_id, m.date, m.domicile, m.exterieur, p.proba_dom, m.score_dom, m.score_ext,
               (SELECT cote_dom FROM cotes c WHERE c.match_id = p.match_id
                ORDER BY releve DESC LIMIT 1) AS cote_dom,
               (SELECT cote_ext FROM cotes c WHERE c.match_id = p.match_id
                ORDER BY releve DESC LIMIT 1) AS cote_ext
        FROM previsions p JOIN matchs m ON m.id = p.match_id ORDER BY m.date DESC, m.id""").fetchall()
    journal = [{
        "id": r["match_id"], "date": r["date"], "home": r["domicile"], "away": r["exterieur"],
        "p_home": round(r["proba_dom"], 4),
        "home_win": None if r["score_dom"] is None else int(r["score_dom"] > r["score_ext"]),
        "score": None if r["score_dom"] is None else [r["score_dom"], r["score_ext"]],
        "odds": [r["cote_dom"], r["cote_ext"]] if r["cote_dom"] else None,
    } for r in rows]
    backtest = json.loads(BACKTEST_FILE.read_text()) if BACKTEST_FILE.exists() else None
    return {"journal": journal, "backtest": backtest}


def export(con: sqlite3.Connection, day: pd.Timestamp | None = None, demo: bool = False) -> list[Path]:
    day, games = tonight(con, day)
    p = load_params()
    payloads = {
        "today.json": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "date": day.date().isoformat(), "demo": demo, "version": p.version,
                       "sigma": p.sigma, "games": games},
        "ratings.json": ratings_payload(con, day),
        "record.json": record_payload(con),
    }
    return write_payloads(payloads)


def write_payloads(payloads: dict) -> list[Path]:
    written = []
    for target in APP_DATA:
        if target.parent.exists():
            target.mkdir(parents=True, exist_ok=True)
            for name, obj in payloads.items():
                (target / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
                written.append(target / name)
    return written


def copy_data_to_dist() -> None:
    src, dst = APP_DATA
    if src.exists() and dst.parent.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)


JOURNAL_CSV = ROOT / "data" / "journal.csv"
JOURNAL_COLS = ["match_id", "proba_dom", "ecart_dom", "corrections", "absents", "version", "enregistre"]


def save_journal_csv(con: sqlite3.Connection, path: Path = JOURNAL_CSV) -> None:
    """Le journal en texte (versionné dans le dépôt) : la base SQLite peut être reconstruite."""
    df = pd.read_sql_query(f"SELECT {', '.join(JOURNAL_COLS)} FROM previsions ORDER BY enregistre, match_id", con)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def load_journal_csv(con: sqlite3.Connection, path: Path = JOURNAL_CSV) -> int:
    if not path.exists():
        return 0
    df = pd.read_csv(path, dtype={"match_id": str}).fillna("")
    con.executemany(f"INSERT OR IGNORE INTO previsions VALUES ({','.join('?' * len(JOURNAL_COLS))})",
                    df[JOURNAL_COLS].itertuples(index=False, name=None))
    con.commit()
    return len(df)
