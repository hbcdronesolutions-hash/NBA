"""Section 9 — prévisions des joueurs (points, rebonds, passes, points + rebonds + passes).

Prévision = minutes attendues × rendement par minute, corrigé par :
- l'adversaire (s'il concède 10 % de plus que la moyenne : environ +7 %) ;
- le rythme prévu du match (net sur points et passes, faible sur les rebonds) ;
- les coéquipiers absents (20 % de la production attendue absente : environ +7 %).
Domicile et match la veille : aucun effet mesurable, donc ignorés.
La dispersion (écart-type) vient de l'historique du joueur, ramené à ses minutes attendues.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .players import normalize
from .ratings import Ratings

STATS = ("pts", "reb", "ast")
OPP_ELASTICITY = 0.72
PACE_ELASTICITY = {"pts": 1.0, "reb": 0.3, "ast": 1.0}
ABSENT_BOOST = 0.35          # 20 % de production absente -> +7 %
PRIOR_MINUTES = 120.0        # a priori : 120 minutes au rendement moyen de la ligue
MIN_MINUTES = 20.0           # joueurs à 20 minutes ou plus (périmètre du test)
OUT = {"out", "doubtful"}


def _prep(logs: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    d = logs[(logs["date"] < day) & (logs["minutes"] > 0)].copy()
    d["reb"] = d["oreb"] + d["dreb"]
    return d.sort_values("date")


def _allowed(d: pd.DataFrame, r: Ratings) -> tuple[dict, dict]:
    """Ce que chaque équipe concède par 100 possessions, et la moyenne de la ligue."""
    per_team = d.groupby(["match_id", "team"])[list(STATS)].sum().reset_index()
    pairs = per_team.merge(per_team, on="match_id", suffixes=("", "_opp"))
    pairs = pairs[pairs["team"] != pairs["team_opp"]]
    allowed = pairs.groupby("team")[[f"{s}_opp" for s in STATS]].mean()
    allowed.columns = list(STATS)
    from .ratings import IDX
    per100 = allowed.apply(lambda row: row / r.pace[IDX[row.name]] * 100, axis=1)
    return per100.to_dict("index"), per100.mean().to_dict()


def forecasts(logs: pd.DataFrame, day: pd.Timestamp, home: str, away: str, r: Ratings,
              injuries: list[dict], rosters: dict[int, str] | None = None) -> list[dict]:
    d = _prep(logs, day)
    if d.empty:
        return []
    allowed, lg_allowed = _allowed(d, r)
    lg_rate = {s: d[s].sum() / d["minutes"].sum() for s in STATS}
    from .ratings import IDX
    game_pace = r.pace[IDX[home]] * r.pace[IDX[away]] / r.league_pace
    status = {(i["team"], normalize(i["player"])): i["status"].lower() for i in injuries}

    out = []
    for team, opp in ((home, away), (away, home)):
        if rosters:   # effectif officiel actuel : les transferts comptent tout de suite
            roster = d[d["player_id"].map(rosters) == team]
        else:
            roster = d[d["team"] == team]
        if roster.empty:
            continue
        rows = []
        for pid, g in roster.groupby("player_id"):
            if g["date"].max() < day - pd.Timedelta(days=21):   # parti ou blessé longue durée
                continue
            st = status.get((team, normalize(g["name"].iloc[-1])), "")
            mins = float(g["minutes"].tail(10).mean())
            rate = {s: (g[s].sum() + lg_rate[s] * PRIOR_MINUTES) / (g["minutes"].sum() + PRIOR_MINUTES) for s in STATS}
            rows.append({"id": int(pid), "name": g["name"].iloc[-1], "team": team, "status": st,
                         "minutes": mins, "rate": rate, "games": g.tail(20)})
        # Coéquipiers absents : part de la production attendue qui manque.
        prod = {x["id"]: sum(x["rate"][s] for s in STATS) * x["minutes"] for x in rows}
        total = sum(prod.values()) or 1
        missing = sum(prod[x["id"]] for x in rows if x["status"] in OUT) / total
        team_pace = r.pace[IDX[team]]
        for x in rows:
            if x["status"] in OUT or x["minutes"] < MIN_MINUTES:
                continue
            f = {}
            for s in STATS:
                opp_f = (allowed.get(opp, {}).get(s, lg_allowed[s]) / lg_allowed[s]) ** OPP_ELASTICITY
                pace_f = (game_pace / team_pace) ** PACE_ELASTICITY[s]
                f[s] = x["rate"][s] * x["minutes"] * opp_f * pace_f * (1 + ABSENT_BOOST * missing)
            f["pra"] = f["pts"] + f["reb"] + f["ast"]
            g = x["games"]
            scale = x["minutes"] / g["minutes"].clip(lower=8)
            sd = {}
            for s in ("pts", "reb", "ast", "pra"):
                vals = (g[["pts", "reb", "ast"]].sum(axis=1) if s == "pra" else g[s]) * scale
                emp = float(np.std(vals, ddof=1)) if len(vals) >= 5 else 0.0
                sd[s] = round(max(emp, 1.1 * np.sqrt(max(f[s], 0.5))), 2)
            out.append({"id": x["id"], "name": x["name"], "team": team,
                        "status": x["status"] or None, "minutes": round(x["minutes"], 1),
                        **{s: round(f[s], 1) for s in ("pts", "reb", "ast", "pra")}, "sd": sd})
    return sorted(out, key=lambda p: (p["team"] != home, -p["minutes"]))
