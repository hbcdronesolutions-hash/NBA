"""Étage 2 (v2) — valeur des joueurs mesurée sur les résultats (régression « avec / sans »).

Pour chaque match : écart au score pour 100 possessions = somme, pour chaque joueur,
de sa valeur × sa part du temps de jeu (minutes / 48), moins la même chose pour l'adversaire,
plus l'avantage du terrain. Une régression ridge (rétrécie vers une estimation tirée des
statistiques individuelles) donne la valeur de chaque joueur en points pour 100 possessions
quand il est sur le terrain, par rapport à un joueur moyen.

Usage dans le modèle : la note d'une équipe reflète l'effectif qui a joué ses derniers matchs.
Ce soir, on compare la force de l'effectif disponible (valeurs × minutes attendues) à la force
moyenne de l'effectif de ces matchs-là. La différence corrige l'écart prévu : un absent important
fait baisser, un retour fait monter.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import lsqr

from .players import game_score

HCA_100 = 1.8      # avantage du terrain, pour 100 possessions (≈ points sur un match)
BOX_SCALE = 0.40   # a priori tiré du Game Score (même échelle que l'impact V1)
REPLACEMENT_GS36 = 9.0
UNKNOWN = -2.0     # joueur sans historique (débutant) : niveau remplaçant


def load_minutes(con: sqlite3.Connection) -> pd.DataFrame:
    """Une ligne par joueur et par match : minutes, équipe, côté (domicile/extérieur), stats."""
    df = pd.read_sql_query("""
        SELECT s.match_id, m.date, m.saison AS season, s.joueur_id AS pid, s.equipe AS team,
               s.minutes, s.pts, s.fgm, s.fga, s.ftm, s.fta, s.oreb, s.dreb, s.ast, s.stl, s.blk,
               s.tov, s.pf, (s.equipe = m.domicile) AS is_home
        FROM stats_joueur_match s JOIN matchs m ON m.id = s.match_id
        WHERE m.statut = 'termine' AND s.minutes > 0""", con)
    df["date"] = pd.to_datetime(df["date"])
    return df


def box_prior(pm: pd.DataFrame) -> pd.Series:
    """A priori par joueur (points / 100 possessions, centré sur 0 = joueur moyen)."""
    g = pm.assign(gs=game_score(pm)).groupby("pid").agg(gs=("gs", "sum"), mins=("minutes", "sum"))
    gs36 = (36 * g["gs"] + REPLACEMENT_GS36 * 300) / (g["mins"] + 300)
    v = (gs36 - REPLACEMENT_GS36) * BOX_SCALE
    # Recentrage : en moyenne pondérée par les minutes, la ligue vaut 0.
    return v - np.average(v, weights=g["mins"])


def fit_values(games: pd.DataFrame, pm: pd.DataFrame, asof: pd.Timestamp,
               damp: float = 3.0, half_life_days: float = 365.0, prior_weight: float = 1.0) -> pd.Series:
    """Valeur de chaque joueur au matin de `asof`, uniquement avec les matchs antérieurs."""
    g = games[(games["date"] < asof) & games["home_pts"].notna()]
    p = pm[pm["date"] < asof]
    if g.empty or p.empty:
        return pd.Series(dtype=float)
    prior = box_prior(p) * prior_weight
    pids = prior.index.to_numpy()
    col = {pid: i for i, pid in enumerate(pids)}
    row = {gid: i for i, gid in enumerate(g["id"])}
    p = p[p["match_id"].isin(row)]
    share = (p["minutes"] / 48.0).to_numpy() * np.where(p["is_home"].to_numpy() == 1, 1.0, -1.0)
    X = csr_matrix((share, (p["match_id"].map(row).to_numpy(), p["pid"].map(col).to_numpy())),
                   shape=(len(row), len(col)))
    y = ((g["home_pts"] - g["away_pts"]) / g["poss"] * 100 - HCA_100).to_numpy()
    w = np.sqrt(0.5 ** ((asof - g["date"]).dt.days.to_numpy() / half_life_days))
    # Ridge vers l'a priori : on résout pour (v − a priori).
    resid = y - X @ prior.to_numpy()
    sol = lsqr(csr_matrix(X.multiply(w[:, None])), resid * w, damp=damp)[0]
    return pd.Series(prior.to_numpy() + sol, index=pids)


def strength(rows: pd.DataFrame, values: pd.Series, minutes_col: str = "minutes") -> float:
    """Force d'un effectif : valeurs × part du temps de jeu, ramenée à 5 joueurs sur le terrain."""
    if rows.empty:
        return 0.0
    m = rows[minutes_col].to_numpy(dtype=float)
    v = rows["pid"].map(values).fillna(UNKNOWN).to_numpy() if len(values) else np.zeros(len(rows))
    tot = m.sum()
    return float((v * m).sum() / tot * 5) if tot > 0 else 0.0


def roster_adjustments(games: pd.DataFrame, pm: pd.DataFrame, values: pd.Series, day: pd.Timestamp,
                       teams: list[str], injuries: list[dict], rosters: dict[int, str],
                       names: dict[int, str], half_life_days: float = 60.0) -> dict[str, dict]:
    """Pour chaque équipe : force de l'effectif ce soir − force moyenne de ses derniers matchs.

    Renvoie {équipe: {"delta": points / 100 poss, "absents": [...], "base_games": n}}.
    """
    from .players import normalize
    from .collect import season_of

    status = {(i["team"], normalize(i["player"])): i["status"].lower() for i in injuries}
    season = season_of(day.date())
    hist = pm[pm["date"] < day]
    recent = hist[hist["date"] >= day - pd.Timedelta(days=21)]
    em = hist.sort_values("date").groupby("pid")["minutes"].apply(lambda s: s.tail(10).mean())
    last_team = hist.sort_values("date").groupby("pid")["team"].last()
    out = {}
    for team in teams:
        # Force moyenne de l'effectif sur les matchs de la saison (même pondération que la note).
        ps = hist[(hist["season"] == season) & (hist["team"] == team)]
        if ps["match_id"].nunique() < 3:
            out[team] = {"delta": 0.0, "absents": [], "base_games": int(ps["match_id"].nunique())}
            continue
        v = ps["pid"].map(values).fillna(UNKNOWN)
        tg = ps.assign(vm=v * ps["minutes"]).groupby(["match_id", "date"]).agg(vm=("vm", "sum"), m=("minutes", "sum")).reset_index()
        w = 0.5 ** ((day - tg["date"]).dt.days / half_life_days)
        sbar = float(np.average(tg["vm"] / tg["m"] * 5, weights=w))
        # Effectif disponible ce soir.
        if rosters:
            cand = [pid for pid, t in rosters.items() if t == team]
        else:
            cand = [pid for pid, t in last_team.items() if t == team]
        cand = [pid for pid in cand if pid in em.index and pid in set(recent["pid"])]
        # Minutes attendues : 10 derniers matchs de l'équipe (0 si non joué) ; recrue : 80 % d'ailleurs.
        team_games = ps.drop_duplicates("match_id").sort_values("date")["match_id"].tail(10)
        last10 = ps[ps["match_id"].isin(team_games)].groupby("pid")["minutes"].sum() / len(team_games)
        em_team = {pid: float(last10.get(pid, 0.0)) or 0.8 * float(em[pid]) for pid in cand}
        rows, absents = [], []
        for pid in cand:
            st = status.get((team, normalize(names.get(pid, ""))), "")
            mins = em_team[pid]
            if st in ("out", "doubtful"):
                absents.append((pid, st, mins))
                continue
            rows.append((pid, mins * (0.5 if st == "questionable" else 1.0)))
            if st == "questionable":
                absents.append((pid, st, mins * 0.5))
        avail = pd.DataFrame(rows, columns=["pid", "minutes"])
        s_t = strength(avail, values)
        detail = []
        for pid, st, mins in absents:
            with_him = pd.concat([avail[avail["pid"] != pid], pd.DataFrame([(pid, em_team[pid])], columns=["pid", "minutes"])])
            detail.append({"pid": int(pid), "name": names.get(pid, str(pid)), "status": st,
                           "impact": strength(with_him, values) - s_t,
                           "value": float(values.get(pid, UNKNOWN)), "minutes": float(em_team[pid])})
        out[team] = {"delta": s_t - sbar, "absents": sorted(detail, key=lambda a: -a["impact"]),
                     "base_games": int(ps["match_id"].nunique())}
    return out


def team_expected_minutes(pm: pd.DataFrame) -> pd.Series:
    """Minutes attendues de chaque joueur avant chaque match de son équipe.

    Moyenne sur les 10 derniers matchs de l'équipe (0 s'il n'a pas joué). Pour une recrue
    sans match avec l'équipe : 80 % de sa moyenne récente ailleurs.
    Index : (match_id, pid) des matchs de la saison ; utilisable aussi pour « ce soir ».
    """
    out = []
    overall = pm.sort_values("date").groupby("pid")["minutes"].apply(lambda s: s.shift().rolling(10, min_periods=1).mean())
    overall.index = pm.sort_values("date").index
    pm = pm.assign(ov=overall.reindex(pm.index))
    for (season, team), g in pm.groupby(["season", "team"]):
        order = g.drop_duplicates("match_id").sort_values("date")["match_id"].tolist()
        pv = g.pivot_table(index="match_id", columns="pid", values="minutes", aggfunc="sum").reindex(order).fillna(0.0)
        n = pd.Series(range(len(order)), index=order).clip(upper=10)
        roll = pv.rolling(10, min_periods=1).sum().shift().div(n.replace(0, np.nan), axis=0)
        st = roll.stack(future_stack=True).rename("em").reset_index()
        st = st.merge(g[["match_id", "pid", "ov"]], on=["match_id", "pid"], how="inner")
        st["em"] = np.where(st["em"].fillna(0) > 0, st["em"], 0.8 * st["ov"].fillna(12.0))
        out.append(st[["match_id", "pid", "em"]])
    return pd.concat(out).set_index(["match_id", "pid"])["em"]
