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
from . import rapm as RP
from .collect import ET, load_games, load_player_logs, load_rosters, season_of
from .db import ROOT
from .model import Prediction, predict
from .players import absences_for, player_table
from .props import forecasts

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
    plogs = load_player_logs(con, season)
    rosters = load_rosters(con)
    players = player_table(plogs, day, rosters)
    inj = INJ.latest_for(con, day.date().isoformat())
    slate = sched[sched["date"] == day]
    roster = None
    try:   # v1.1 : valeur des joueurs (régression avec / sans) et effectif du soir
        pm = RP.load_minutes(con)
        values = RP.fit_values(games[games["home_pts"].notna()], pm, day, damp=p.rapm_damp)
        names = {r_[0]: r_[1] for r_ in con.execute("SELECT id, nom FROM joueurs")}
        teams = sorted(set(slate["home"]) | set(slate["away"]))
        roster = RP.roster_adjustments(games, pm, values, day, teams, inj, rosters, names, p.half_life_days)
    except Exception as e:  # repli sur le calcul simple de la V1
        print(f"Effectif du soir : repli V1 ({e.__class__.__name__}: {e})")
    out = []
    for g in slate.itertuples():
        pace = r.team(g.home)["pace"] * r.team(g.away)["pace"] / r.league_pace
        abs_ = absences_for(g.home, inj, players, pace) + absences_for(g.away, inj, players, pace) if len(players) else []
        pr = predict(g.home, g.away, day, r, p, schedule=sched, absences=abs_, roster=roster)
        payload = game_payload(g.id, g.tip_utc, pr, match_odds(con, g.id),
                                (g.home_pts, g.away_pts) if pd.notna(g.home_pts) else None)
        # Détail pour l'explication (vidéo) : chaque absent avec sa valeur, ses minutes et son coût.
        k = p.roster_k * pace / 100
        payload["absent_detail"] = [
            {"team": t, "player": a_["name"], "status": a_["status"], "value": round(a_.get("value", 0.0), 2),
             "minutes": round(a_.get("minutes", 0.0), 1), "impact": round(a_["impact"] * k, 2)}
            for t in (g.home, g.away) for a_ in ((roster or {}).get(t) or {}).get("absents", [])]
        payload["injury_report"] = [{"team": i["team"], "player": i["player"], "status": i["status"]}
                                    for i in inj if i["team"] in (g.home, g.away)]
        payload["players"] = forecasts(plogs, day, g.home, g.away, r, inj, rosters) if len(plogs) else []
        out.append(payload)
    return day, out


def match_odds(con: sqlite3.Connection, gid: str) -> dict | None:
    """Dernière cote de chaque bookmaker ; bookmakers français en priorité, meilleure cote par équipe."""
    rows = con.execute("""SELECT bookmaker, cote_dom, cote_ext FROM cotes c WHERE match_id = ?
        AND releve = (SELECT MAX(releve) FROM cotes c2 WHERE c2.match_id = c.match_id AND c2.bookmaker = c.bookmaker)""",
                       (gid,)).fetchall()
    rows = [r for r in rows if r["cote_dom"] and r["cote_ext"]]
    french = [r for r in rows if r["bookmaker"].endswith("(FR)")]
    rows = french or rows
    if not rows:
        return None
    name = lambda r: r["bookmaker"].replace(" (FR)", "")
    bh = max(rows, key=lambda r: r["cote_dom"])
    ba = max(rows, key=lambda r: r["cote_ext"])
    # Probabilité des bookmakers : moyenne des probabilités implicites (marges retirées).
    pb = sum(B.book_probability(r["cote_dom"], r["cote_ext"]) for r in rows) / len(rows)
    return {
        "home": bh["cote_dom"], "away": ba["cote_ext"], "book_home": name(bh), "book_away": name(ba),
        "book": name(bh) if len(rows) == 1 else "Meilleure cote",
        "p_book_home": pb, "french": bool(french),
        "books": sorted(({"book": name(r), "home": r["cote_dom"], "away": r["cote_ext"]} for r in rows),
                        key=lambda x: x["book"]),
    }


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
    if odds:
        pb = odds.pop("p_book_home")
        d.update({
            "odds": odds,
            "p_book_home": round(pb, 4),
            "divergence": abs(pb - ph) > B.DIVERGENCE,
            "verdict": {"home": B.verdict(odds["home"], d["min_odds"]["home"]),
                        "away": B.verdict(odds["away"], d["min_odds"]["away"])},
        })
    return d


def journal(con: sqlite3.Connection, games: list[dict], version: str) -> int:
    """Enregistre la dernière prévision avant le match ; figée dès le coup d'envoi."""
    now = datetime.now(timezone.utc)
    n = 0
    for g in games:
        if g["tip_utc"] and datetime.fromisoformat(g["tip_utc"]) <= now:
            continue
        old = con.execute("SELECT proba_dom, absents FROM previsions WHERE match_id=?", (g["id"],)).fetchone()
        if old and abs(old["proba_dom"] - g["p_home"]) < 1e-4 and old["absents"] == json.dumps(g["absences"]):
            continue   # rien n'a changé : on ne réécrit pas (journal stable)
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


def _latest_odds(con: sqlite3.Connection) -> dict[str, tuple[float, float]]:
    """Pour le bilan : meilleure cote par équipe, bookmakers français en priorité."""
    ids = [r[0] for r in con.execute("SELECT DISTINCT match_id FROM cotes")]
    out = {}
    for gid in ids:
        o = match_odds(con, gid)
        if o:
            out[gid] = (o["home"], o["away"])
    return out


def replay_season(games: pd.DataFrame, season: str, p: R.Params) -> pd.DataFrame:
    """Saison en cours rejouée match par match, sans information postérieure (pas les absents)."""
    sg = games[games["season"] == season].sort_values("date")
    prior = _prior_for(games, season, p)
    rows = []
    for day, dg in sg[sg["home_pts"].notna()].groupby("date", sort=True):
        r = R.compute(sg, day, prior, p)
        for g in dg.itertuples():
            pr = predict(g.home, g.away, day, r, p, schedule=sg)
            rows.append({"id": g.id, "p_home": pr.p_home, "spread": pr.spread})
    return pd.DataFrame(rows)


def record_payload(con: sqlite3.Connection, day: pd.Timestamp | None = None) -> dict:
    """Journal (prévisions enregistrées avant les matchs) + saison en cours rejouée avant le journal."""
    odds = _latest_odds(con)
    games = load_games(con)
    info = games.set_index("id")

    def entry(gid: str, p_home: float, spread: float | None, live: bool) -> dict:
        g = info.loc[gid]
        done = pd.notna(g["home_pts"])
        o = odds.get(gid)
        return {
            "id": gid, "date": g["date"].date().isoformat(), "tip_utc": g["tip_utc"],
            "home": g["home"], "away": g["away"], "p_home": round(float(p_home), 4),
            "spread": None if spread is None or pd.isna(spread) else round(float(spread), 1),
            "home_win": int(g["home_pts"] > g["away_pts"]) if done else None,
            "score": [int(g["home_pts"]), int(g["away_pts"])] if done else None,
            "odds": [o[0], o[1]] if o and o[0] and o[1] else None,
            "live": live,
        }

    rows = con.execute("SELECT match_id, proba_dom, ecart_dom FROM previsions").fetchall()
    journal = [entry(r["match_id"], r["proba_dom"], r["ecart_dom"], True) for r in rows if r["match_id"] in info.index]
    live_ids = {e["id"] for e in journal}
    first_live = min((e["date"] for e in journal), default="9999")
    season = season_of((day or pd.Timestamp(datetime.now(ET).date())).date())
    try:
        rep = replay_season(games, season, load_params())
    except Exception:
        rep = pd.DataFrame()
    for r in rep.itertuples() if len(rep) else []:
        if r.id not in live_ids and info.loc[r.id, "date"].date().isoformat() < first_live:
            journal.append(entry(r.id, r.p_home, r.spread, False))
    journal.sort(key=lambda e: (e["date"], e["tip_utc"] or ""), reverse=True)
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
        "record.json": record_payload(con, day),
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
