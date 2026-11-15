"""Données de démonstration : une ligue simulée pour voir l'app avant la vraie collecte.

Rien ici n'est réel (scores, joueurs, blessures, cotes). L'app affiche un badge « Démo ».
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from . import backtest as BT
from . import ratings as R
from .db import connect, ROOT
from .service import BACKTEST_FILE, export, tonight

SEASONS = [(2024, date(2024, 10, 22), date(2025, 4, 13)),
           (2025, date(2025, 10, 21), date(2026, 4, 12)),
           (2026, date(2026, 10, 20), date(2026, 11, 14))]

FIRST = ["Alex", "Jordan", "Tyler", "Marcus", "Devin", "Chris", "Malik", "Isaiah", "Evan", "Noah",
         "Julian", "Caleb", "Andre", "Darius", "Luka", "Theo", "Hugo", "Nico", "Owen", "Zach"]
LAST = ["Martin", "Brooks", "Hayes", "Carter", "Reed", "Price", "Grant", "Fields", "Mason", "Lane",
        "Porter", "Wells", "Bishop", "Rivers", "Cole", "Hart", "Webb", "Stone", "Ford", "Shaw"]

TONIGHT = [("TOR", "NYK", "00:30"), ("BOS", "MIA", "00:30"), ("CLE", "ATL", "01:00"),
           ("MIL", "IND", "01:00"), ("DEN", "PHX", "02:00"), ("OKC", "DAL", "02:00"),
           ("LAC", "CHA", "03:30"), ("SAC", "MEM", "04:00")]


def _schedule(rng, start: date, end: date, teams: list[str]) -> list[tuple[date, str, str]]:
    games, day = [], start
    while day <= end:
        k = int(rng.integers(4, 12))
        pool = list(rng.permutation(teams))[: 2 * k]
        for i in range(0, len(pool) - 1, 2):
            games.append((day, pool[i], pool[i + 1]))
        day += timedelta(days=1)
    return games


def build(seed: int = 7) -> None:
    rng = np.random.default_rng(seed)
    db_path = ROOT / "data" / "demo.sqlite"
    if db_path.exists():
        db_path.unlink()
    con = connect(db_path)
    teams = R.ABBRS
    strength = dict(zip(teams, rng.normal(0, 6.5, len(teams))))
    off_bias = dict(zip(teams, rng.normal(0, 2.5, len(teams))))
    pace = dict(zip(teams, rng.normal(99, 2.2, len(teams))))
    rosters = {t: [(f"{FIRST[rng.integers(20)]} {LAST[rng.integers(20)]}", float(m))
                   for m in (36, 34, 32, 30, 26, 22, 18, 14, 10)] for t in teams}
    pid = 1000
    player_ids = {}

    for y, start, end in SEASONS:
        season = f"{y}-{(y + 1) % 100:02d}"
        for t in teams:  # dérive d'une saison à l'autre
            strength[t] = 0.8 * strength[t] + rng.normal(0, 3.8)
        for n, (day, h, a) in enumerate(_schedule(rng, start, end, teams)):
            poss = pace[h] * pace[a] / 99 + rng.normal(0, 3)
            true_spread = (strength[h] - strength[a]) * poss / 100 + 2.0
            margin = round(true_spread + rng.normal(0, 12.5))
            margin = margin if margin != 0 else 1
            total = (114 + (off_bias[h] + off_bias[a]) / 2) * poss / 50 + rng.normal(0, 10)
            hp, ap = round((total + margin) / 2), round((total - margin) / 2)
            if hp == ap:
                hp += 1
            gid = f"demo-{season}-{n:05d}"
            con.execute("INSERT INTO matchs VALUES (?,?,?,?,?,?,?,?,'termine')",
                        (gid, season, day.isoformat(), None, h, a, hp, ap))
            for team, pts in ((h, hp), (a, ap)):
                con.execute("INSERT INTO stats_equipe_match (match_id, equipe, points, possessions) VALUES (?,?,?,?)",
                            (gid, team, pts, poss))
            if season.startswith("2026"):
                for team in (h, a):
                    for name, mins in rosters[team]:
                        key = (team, name)
                        if key not in player_ids:
                            pid += 1
                            player_ids[key] = pid
                            con.execute("INSERT INTO joueurs (id, nom, equipe) VALUES (?,?,?)", (pid, name, team))
                        m = max(0, mins + rng.normal(0, 3))
                        star = 1.6 if mins >= 34 else 1.0
                        pts = max(0, rng.normal(mins * 0.48 * star, 5))
                        con.execute("INSERT INTO stats_joueur_match VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                    (gid, player_ids[key], team, m, int(pts), int(pts * .37), int(pts * .8),
                                     int(pts * .15), int(pts * .19), int(m * .05), int(m * .17),
                                     int(m * .1 * star), int(m * .03), int(m * .02), int(m * .05), 2))
    # Ce soir (15/11/2026), heures françaises -> UTC.
    day = date(2026, 11, 15)
    for i, (h, a, fr) in enumerate(TONIGHT):
        hh, mm = map(int, fr.split(":"))
        tip = datetime(2026, 11, 16, hh, mm, tzinfo=timezone(timedelta(hours=1))).astimezone(timezone.utc)
        con.execute("INSERT INTO matchs (id, saison, date, heure_utc, domicile, exterieur) VALUES (?,?,?,?,?,?)",
                    (f"demo-tonight-{i}", "2026-27", day.isoformat(), tip.isoformat(), h, a))
    # Blessures fictives.
    report = "2026-11-15T17:00:00+00:00 demo"
    for team, idx, status in (("NYK", 0, "Out"), ("CHA", 1, "Questionable"), ("DEN", 2, "Out"), ("MIA", 0, "Doubtful")):
        name = rosters[team][idx][0]
        last, first = name.split(" ")[1], name.split(" ")[0]
        con.execute("INSERT OR REPLACE INTO blessures VALUES (?,?,?,?,?,?)",
                    (report, day.isoformat(), team, f"{last}, {first}", status, "Démo"))
    con.commit()

    # Backtest de référence : les résultats réels du 15/11/2026 (fiche de conception, section 8).
    BACKTEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKTEST_FILE.write_text(json.dumps(REFERENCE_BACKTEST))

    # Journal : la saison simulée rejouée, comme si chaque prévision avait été faite avant le match.
    games = pd.read_sql_query("SELECT m.id, m.saison season, m.date, m.domicile home, m.exterieur away, "
                              "m.score_dom home_pts, m.score_ext away_pts, "
                              "(SELECT AVG(possessions) FROM stats_equipe_match s WHERE s.match_id=m.id) poss "
                              "FROM matchs m WHERE m.statut='termine'", con)
    games["date"] = pd.to_datetime(games["date"])
    p = R.Params()
    bt = BT.replay(games[games["season"] >= "2025-26"], p)
    # Journal : les prévisions de la saison en cours, comme si elles avaient été faites avant chaque match.
    cur = bt[bt["season"] == "2026-27"]
    for row in cur.itertuples():
        ph = row.p_home
        oh, oa = _odds(rng, ph)
        rec = (row.date - pd.Timedelta(hours=6)).isoformat()
        con.execute("INSERT OR IGNORE INTO previsions VALUES (?,?,?,?,?,?,?)",
                    (row.id, ph, row.spread, "[]", "[]", p.version, rec))
        con.execute("INSERT OR IGNORE INTO cotes VALUES (?,?,?,?,?)", (row.id, "Démo", oh, oa, rec))
    # Cotes de ce soir.
    _, games_tonight = tonight(con, pd.Timestamp(day))
    for g in games_tonight:
        oh, oa = _odds(rng, g["p_home"])
        con.execute("INSERT OR REPLACE INTO cotes VALUES (?,?,?,?,?)",
                    (g["id"], "Démo", oh, oa, "2026-11-15T17:00:00+00:00"))
    con.commit()
    export(con, pd.Timestamp(day), demo=True)
    con.close()


REFERENCE_BACKTEST = {
    "source": "Backtest du 15/11/2026 — 2024-25 et 2025-26 (2 460 matchs jamais vus)",
    "seasons": ["2024-25", "2025-26"], "n": 2460, "accuracy": 0.678, "logloss": 0.599,
    "baselines": {"home_always": 0.549, "better_record": 0.654},
    "calibration": [
        {"bin": "50-60", "lo": 0.5, "n": 919, "confidence": 0.548, "hit": 0.556},
        {"bin": "60-70", "lo": 0.6, "n": 737, "confidence": 0.648, "hit": 0.682},
        {"bin": "70-80", "lo": 0.7, "n": 522, "confidence": 0.746, "hit": 0.787},
        {"bin": "80-90", "lo": 0.8, "n": 245, "confidence": 0.839, "hit": 0.853},
        {"bin": "90-100", "lo": 0.9, "n": 37, "confidence": 0.916, "hit": 0.946},
    ],
    "selection": {
        "top1": {"per_night": 1, "accuracy": 0.826}, "top3": {"per_night": 3, "accuracy": 0.771},
        "top4": {"per_night": 4, "accuracy": 0.753},
        "conf65": {"per_night": 3.5, "accuracy": 0.789}, "conf70": {"per_night": 2.5, "accuracy": 0.815},
        "conf75": {"per_night": 1.6, "accuracy": 0.849},
        "combo2": 0.634, "combo3": 0.476, "combo4": 0.358,
    },
}


def _odds(rng, p_home: float) -> tuple[float, float]:
    pb = float(np.clip(p_home + rng.normal(0, 0.05), 0.05, 0.95))
    vig = 1.05
    return round(1 / (pb * vig), 2), round(1 / ((1 - pb) * vig), 2)
