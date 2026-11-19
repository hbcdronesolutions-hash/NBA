"""Paris joueurs : points, rebonds, passes, points + rebonds + passes.

Pour chaque joueur du soir, un modèle appris sur les saisons passées (arbres de décision, LightGBM)
donne la prévision et la distribution de la stat (quantiles 10 % ... 90 %), d'où la probabilité
d'atteindre « N ou plus » et la cote minimum (1 / probabilité).

Facteurs : forme (saison, 5 et 10 derniers matchs, moyenne pondérée, saison précédente),
minutes et rôle, coéquipiers absents (rapport des blessures), ce que l'adversaire concède,
rythme des deux équipes, domicile, repos, écart prévu par l'algorithme.

Sélection (vérifiée sur 2025-26, matchs jamais vus) : le pari « N ou plus » le plus haut à 70 %
de chances ou plus, retenu comme signal quand la prévision dépasse nettement l'habitude du joueur
(+3 pts, +1,5 rebond, +1,5 passe, +4 pts+reb+passes) : 72 à 84 % de réussite réelle.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .db import ROOT
from .players import normalize

STATS = {"pts": "points", "reb": "rebonds", "ast": "passes", "pra": "pts + reb + passes"}
MINDEV = {"pts": 3.0, "reb": 1.5, "ast": 1.5, "pra": 4.0}
QS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
TARGET_P = 0.70
MODEL_DIR = ROOT / "data" / "props_models"
CSV = ROOT / "data" / "paris_joueurs.csv"
MAX_AGE_DAYS = 7
BASE = ["mn_sea", "mn_l5", "mn_l10", "mn_ew", "gp", "start_l5", "rest", "is_home", "mn_prev",
        "abs_mn", "abs_pts", "abs_reb", "abs_ast", "pace", "opp_pace", "team_spread", "abs_spread"]
LADDER = (5, 10, 15, 20, 25, 30, 35, 40, 45, 50)   # « + de 4,5 », « + de 9,5 »... comme chez Betclic

SCHEMA = """CREATE TABLE IF NOT EXISTS paris_joueurs (
    date TEXT, match_id TEXT, joueur_id INTEGER, joueur TEXT, equipe TEXT, adversaire TEXT,
    stat TEXT, seuil INTEGER, proba REAL, cote_mini REAL, prevu REAL, habituel REAL, signal INTEGER,
    resultat REAL, enregistre TEXT, PRIMARY KEY (date, joueur_id, stat))"""
COLS = ["date", "match_id", "joueur_id", "joueur", "equipe", "adversaire", "stat", "seuil", "proba",
        "cote_mini", "prevu", "habituel", "signal", "resultat", "enregistre"]


# ---------------------------------------------------------------------------------- données

def _logs(con: sqlite3.Connection) -> pd.DataFrame:
    p = pd.read_sql_query("""
        SELECT s.match_id id, s.joueur_id pid, s.equipe team, s.minutes mn, s.pts, s.oreb + s.dreb reb, s.ast,
               m.date, m.saison season, m.domicile home, m.exterieur away
        FROM stats_joueur_match s JOIN matchs m ON m.id = s.match_id
        WHERE m.score_dom IS NOT NULL AND s.minutes > 0""", con)
    p["date"] = pd.to_datetime(p["date"])
    p["tonight"] = 0
    return p


def _tonight_rows(con: sqlite3.Connection, day: str, injuries: list[dict]) -> pd.DataFrame:
    out = {(i["team"], normalize(i["player"])) for i in injuries if i["status"].lower() in ("out", "doubtful")}
    ros = pd.read_sql_query("SELECT joueur_id pid, nom, equipe team FROM effectifs", con)
    slate = pd.read_sql_query("SELECT id, domicile home, exterieur away, saison season FROM matchs WHERE date = ?",
                              con, params=(day,))
    rows = []
    for g in slate.itertuples():
        for tm in (g.home, g.away):
            for r in ros[ros["team"] == tm].itertuples():
                if (tm, normalize(r.nom)) not in out:
                    rows.append(dict(id=g.id, pid=r.pid, team=tm, mn=np.nan, pts=np.nan, reb=np.nan, ast=np.nan,
                                     date=pd.Timestamp(day), season=g.season, home=g.home, away=g.away, tonight=1))
    return pd.DataFrame(rows)


def features(con: sqlite3.Connection, day: str | None = None, injuries: list[dict] | None = None,
             spreads: dict | None = None) -> pd.DataFrame:
    """Une ligne par joueur et par match, avec uniquement des informations connues avant le match."""
    pl = _logs(con)
    if day:
        pl = pd.concat([pl, _tonight_rows(con, day, injuries or [])], ignore_index=True)
    pl = pl.sort_values(["date", "id"]).reset_index(drop=True)
    pl["pra"] = pl["pts"] + pl["reb"] + pl["ast"]
    pl["opp"] = np.where(pl["team"] == pl["home"], pl["away"], pl["home"])
    pl["is_home"] = (pl["team"] == pl["home"]).astype(int)
    g = pl.groupby(["pid", "season"])
    for s in ("pts", "reb", "ast", "pra", "mn"):
        sh = g[s].shift()
        k = [pl["pid"], pl["season"]]
        pl[f"{s}_sea"] = sh.groupby(k).transform(lambda x: x.expanding().mean())
        pl[f"{s}_l5"] = sh.groupby(k).transform(lambda x: x.rolling(5, min_periods=3).mean())
        pl[f"{s}_l10"] = sh.groupby(k).transform(lambda x: x.rolling(10, min_periods=5).mean())
        pl[f"{s}_ew"] = sh.groupby(k).transform(lambda x: x.ewm(halflife=6).mean())
    mn_cum = g["mn"].shift().groupby([pl["pid"], pl["season"]]).cumsum()
    for s in ("pts", "reb", "ast"):
        sh = g[s].shift()
        pl[f"{s}_pm"] = sh.groupby([pl["pid"], pl["season"]]).cumsum() / mn_cum
        pl[f"{s}_sd"] = sh.groupby([pl["pid"], pl["season"]]).transform(lambda x: x.expanding(5).std())
    pl["gp"] = g.cumcount()
    pl["start_l5"] = (g["mn"].shift() >= 26).astype(float).where(g["mn"].shift().notna()) \
        .groupby([pl["pid"], pl["season"]]).transform(lambda x: x.rolling(5, min_periods=3).mean())
    pl["rest"] = pl.groupby("pid")["date"].diff().dt.days.fillna(5).clip(0, 10)
    prev = pl[pl["tonight"] == 0].groupby(["pid", "season"])[["pts", "reb", "ast", "mn"]].mean().reset_index()
    order = sorted(pl["season"].unique())
    prev["season"] = prev["season"].map(dict(zip(order, order[1:])))
    prev = prev.dropna(subset=["season"]).rename(columns={c: c + "_prev" for c in ("pts", "reb", "ast", "mn")})
    pl = pl.merge(prev, on=["pid", "season"], how="left")
    pl = _absences(pl)
    pl = _opponent(pl)
    pl = _pace_spread(con, pl, spreads or {})
    return pl


def _absences(pl: pd.DataFrame) -> pd.DataFrame:
    """Production habituelle (10 derniers matchs) des joueurs de l'équipe vus récemment et absents ce soir."""
    k = [pl["pid"], pl["season"]]
    post = {s: pl[s].fillna(pl[f"{s}_l10"]).groupby(k).transform(lambda x: x.rolling(10, min_periods=1).mean())
            for s in ("mn", "pts", "reb", "ast")}
    state: dict[str, dict] = {}
    rows = []
    pid, team = pl["pid"].values, pl["team"].values
    for (dt, gid, tm), ix in pl.groupby(["date", "id", "team"], sort=True).indices.items():
        st = state.setdefault(tm, {})
        present = set(pid[ix])
        tot = np.zeros(4)
        for p_, (d0, vals) in st.items():
            if p_ not in present and (dt - d0).days <= 15 and vals[0] >= 12:
                tot += vals
        rows.append((gid, tm, *tot))
        for i in ix:
            st[pid[i]] = (dt, np.array([post[s].values[i] for s in ("mn", "pts", "reb", "ast")]))
            for other, ost in state.items():
                if other != tm:
                    ost.pop(pid[i], None)
    a = pd.DataFrame(rows, columns=["id", "team", "abs_mn", "abs_pts", "abs_reb", "abs_ast"]).fillna(0)
    return pl.merge(a, on=["id", "team"], how="left")


def _opponent(pl: pd.DataFrame) -> pd.DataFrame:
    """Ce que l'adversaire concède dans chaque stat (saison à date), rapporté à la moyenne de la ligue."""
    hist = pl[pl["tonight"] == 0]
    tg = hist.groupby(["id", "team", "opp", "date", "season"])[["pts", "reb", "ast", "pra"]].sum().reset_index()
    tg = tg.sort_values("date")
    lg = tg.groupby("season")[["pts", "reb", "ast", "pra"]].transform("mean")
    for s in ("pts", "reb", "ast", "pra"):
        tg[f"allow_{s}"] = tg.groupby(["opp", "season"])[s].transform(lambda x: x.shift().expanding(5).mean()) / lg[s]
        # valeur de ce soir : moyenne complète de la saison en cours
        tg[f"last_{s}"] = tg.groupby(["opp", "season"])[s].transform("mean") / lg[s]
    cols = [f"allow_{s}" for s in ("pts", "reb", "ast", "pra")]
    pl = pl.merge(tg[["id", "opp"] + cols], on=["id", "opp"], how="left")
    last = tg.sort_values("date").groupby("opp")[[f"last_{s}" for s in ("pts", "reb", "ast", "pra")]].last()
    tn = pl["tonight"] == 1
    for s in ("pts", "reb", "ast", "pra"):
        pl.loc[tn, f"allow_{s}"] = pl.loc[tn, "opp"].map(last[f"last_{s}"])
    return pl


def _pace_spread(con: sqlite3.Connection, pl: pd.DataFrame, spreads: dict) -> pd.DataFrame:
    te = pd.read_sql_query("""SELECT s.match_id id, s.equipe team, s.possessions poss, m.date, m.saison season
                              FROM stats_equipe_match s JOIN matchs m ON m.id = s.match_id""", con)
    te["date"] = pd.to_datetime(te["date"])
    te = te.sort_values("date")
    te["pace"] = te.groupby(["team", "season"])["poss"].transform(lambda x: x.shift().expanding(5).mean())
    pl = pl.merge(te[["id", "team", "pace"]], on=["id", "team"], how="left")
    pl = pl.merge(te[["id", "team", "pace"]].rename(columns={"team": "opp", "pace": "opp_pace"}),
                  on=["id", "opp"], how="left")
    last = te.groupby("team")["poss"].apply(lambda x: x.tail(15).mean())
    tn = pl["tonight"] == 1
    pl.loc[tn, "pace"] = pl.loc[tn, "team"].map(last)
    pl.loc[tn, "opp_pace"] = pl.loc[tn, "opp"].map(last)
    # écart prévu (point de vue domicile) : rejoué par le backtest pour l'historique, modèle du soir sinon
    from .backtest import replay
    from .collect import load_games
    from .service import load_params
    try:
        games = load_games(con)
        hist = replay(games[games["home_pts"].notna()], load_params())[["id", "spread"]]
    except Exception:
        hist = pd.DataFrame(columns=["id", "spread"])
    pl = pl.merge(hist, on="id", how="left")
    if spreads:
        m = pl["tonight"] == 1
        pl.loc[m, "spread"] = [spreads.get((h, a), np.nan) for h, a in zip(pl.loc[m, "home"], pl.loc[m, "away"])]
    pl["team_spread"] = np.where(pl["is_home"] == 1, pl["spread"], -pl["spread"])
    pl["abs_spread"] = pl["spread"].abs()
    return pl


# ---------------------------------------------------------------------------------- modèles

def _feats(t: str) -> list[str]:
    f = BASE + [f"{t}_sea", f"{t}_l5", f"{t}_l10", f"{t}_ew"]
    if t != "pra":
        f += [f"{t}_pm", f"{t}_sd", f"{t}_prev"]
    return f + [f"allow_{t}"]


def _eligible(pl: pd.DataFrame) -> pd.Series:
    return (pl["gp"] >= 5) & (pl["mn_l10"] >= 15)


def train(pl: pd.DataFrame, model_dir: Path = MODEL_DIR) -> None:
    import lightgbm as lgb
    d = pl[_eligible(pl) & (pl["tonight"] == 0)]
    model_dir.mkdir(parents=True, exist_ok=True)
    common = {"num_leaves": 31, "min_data_in_leaf": 100, "verbose": -1}
    for t in STATS:
        ds = lgb.Dataset(d[_feats(t)], d[t], free_raw_data=False)
        lgb.train({**common, "objective": "poisson", "learning_rate": 0.03, "bagging_fraction": 0.8, "bagging_freq": 1,
                   "feature_fraction": 0.8}, ds, num_boost_round=500).save_model(str(model_dir / f"{t}_mu.txt"))
        for q in QS:
            lgb.train({**common, "objective": "quantile", "alpha": q, "learning_rate": 0.05}, ds,
                      num_boost_round=300).save_model(str(model_dir / f"{t}_q{int(q * 100)}.txt"))
    (model_dir / "trained").write_text(datetime.now(timezone.utc).isoformat())


def models_fresh(model_dir: Path = MODEL_DIR) -> bool:
    f = model_dir / "trained"
    try:
        trained = datetime.fromisoformat(f.read_text().strip())
    except (OSError, ValueError):
        return False
    return (datetime.now(timezone.utc) - trained).total_seconds() < MAX_AGE_DAYS * 86400


def _predict(pl: pd.DataFrame, t: str, model_dir: Path = MODEL_DIR) -> tuple[np.ndarray, np.ndarray]:
    import lightgbm as lgb
    X = pl[_feats(t)]
    mu = lgb.Booster(model_file=str(model_dir / f"{t}_mu.txt")).predict(X)
    q = np.column_stack([lgb.Booster(model_file=str(model_dir / f"{t}_q{int(x * 100)}.txt")).predict(X) for x in QS])
    return mu, np.maximum.accumulate(q, axis=1)


def p_at_least(qrow: np.ndarray, k: int) -> float:
    """Probabilité d'atteindre k ou plus (stat entière), par interpolation des quantiles."""
    return float(1 - np.interp(k - 0.5, qrow, QS, left=0.02, right=0.98))


# ---------------------------------------------------------------------------------- le soir

def tonight_picks(con: sqlite3.Connection, day: str, injuries: list[dict], spreads: dict) -> dict:
    """Prévisions et paris joueurs du soir ; entraîne les modèles s'ils ont plus d'une semaine."""
    pl = features(con, day, injuries, spreads)
    if not models_fresh():
        train(pl)
    tn = pl[(pl["tonight"] == 1) & _eligible(pl)].copy()
    if tn.empty:
        return {"date": day, "picks": [], "players": []}
    names = dict(con.execute("SELECT id, nom FROM joueurs").fetchall())
    names.update(dict(con.execute("SELECT joueur_id, nom FROM effectifs").fetchall()))
    players: dict[int, dict] = {}
    picks = []
    for t, label in STATS.items():
        mu, q = _predict(tn, t)
        usual = ((tn[f"{t}_sea"] + tn[f"{t}_l10"]) / 2).values
        for i, r in enumerate(tn.itertuples()):
            name = names.get(r.pid, str(r.pid))
            pl_ = players.setdefault(int(r.pid), {"player": name, "team": r.team, "opp": r.opp, "match_id": r.id,
                                                  "absent_pts": round(float(r.abs_pts or 0)), "stats": {}})
            ladder = [{"line": k - 0.5, "p": round(p_at_least(q[i], k), 3)} for k in LADDER
                      if 0.03 < p_at_least(q[i], k) < 0.97]
            pl_["stats"][t] = {"expected": round(float(mu[i]), 1), "usual": round(float(usual[i]), 1),
                               "low": round(float(q[i][2]), 1), "high": round(float(q[i][6]), 1), "ladder": ladder}
            ks = [k for k in range(1, 80) if p_at_least(q[i], k) >= TARGET_P]
            if not ks or np.isnan(usual[i]):
                continue
            k = max(ks)
            p = p_at_least(q[i], k)
            dev = float(mu[i] - usual[i])
            picks.append({"player": name, "player_id": int(r.pid), "team": r.team, "opp": r.opp, "match_id": r.id,
                          "stat": t, "label": label, "threshold": k, "p": round(p, 3),
                          "min_odds": round(1 / p + 0.005, 2), "expected": round(float(mu[i]), 1),
                          "usual": round(float(usual[i]), 1), "dev": round(dev, 1),
                          "signal": dev >= MINDEV[t], "absent_pts": round(float(r.abs_pts or 0))})
    picks.sort(key=lambda x: x["dev"] / MINDEV[x["stat"]], reverse=True)
    signals = [p for p in picks if p["signal"]]
    fallback = [p for p in picks if not p["signal"] and p["dev"] >= MINDEV[p["stat"]] / 2]
    # un seul pari par joueur dans « à défaut » (le plus marqué)
    seen, fb = {s["player_id"] for s in signals}, []
    for p in fallback:
        if p["player_id"] not in seen:
            fb.append(p)
            seen.add(p["player_id"])
    return {"date": day, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "signals": signals, "fallback": fb[:6], "players": sorted(players.values(), key=lambda x: (x["match_id"], x["team"]))}


# ---------------------------------------------------------------------------------- suivi

def journal(con: sqlite3.Connection, payload: dict, tips: dict[str, str]) -> int:
    """Enregistre les paris du soir (modifiables jusqu'au coup d'envoi, ensuite figés)."""
    con.execute(SCHEMA)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    for kind in ("signals", "fallback"):
        for p in payload.get(kind, []):
            tip = tips.get(p["match_id"])
            if tip and tip <= now:
                continue
            con.execute("INSERT OR REPLACE INTO paris_joueurs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (payload["date"], p["match_id"], p["player_id"], p["player"], p["team"], p["opp"], p["stat"],
                         p["threshold"], p["p"], p["min_odds"], p["expected"], p["usual"], int(p["signal"]), None, now))
            n += 1
    con.commit()
    return n


def settle(con: sqlite3.Connection) -> int:
    """Résultat réel des paris passés (stat du joueur dans le box score)."""
    con.execute(SCHEMA)
    rows = con.execute("""SELECT p.rowid, p.stat, s.pts, s.oreb + s.dreb, s.ast, s.minutes
                          FROM paris_joueurs p JOIN matchs m ON m.id = p.match_id
                          LEFT JOIN stats_joueur_match s ON s.match_id = p.match_id AND s.joueur_id = p.joueur_id
                          WHERE p.resultat IS NULL AND m.score_dom IS NOT NULL""").fetchall()
    n = 0
    for rid, stat, pts, reb, ast, mn in rows:
        if pts is None:   # n'a pas joué : pari remboursé chez le bookmaker
            val = -1.0
        else:
            val = {"pts": pts, "reb": reb, "ast": ast, "pra": pts + reb + ast}[stat]
        con.execute("UPDATE paris_joueurs SET resultat = ? WHERE rowid = ?", (val, rid))
        n += 1
    con.commit()
    return n


def save_csv(con: sqlite3.Connection, path: Path = CSV) -> None:
    con.execute(SCHEMA)
    pd.read_sql_query(f"SELECT {', '.join(COLS)} FROM paris_joueurs ORDER BY date, signal DESC, joueur", con) \
        .to_csv(path, index=False)


def load_csv(con: sqlite3.Connection, path: Path = CSV) -> int:
    con.execute(SCHEMA)
    if not path.exists():
        return 0
    df = pd.read_csv(path)
    df = df.astype(object).where(df.notna(), None)
    con.executemany(f"INSERT OR IGNORE INTO paris_joueurs ({', '.join(COLS)}) VALUES ({', '.join('?' * len(COLS))})",
                    df[COLS].values.tolist())
    con.commit()
    return len(df)


def history(con: sqlite3.Connection) -> list[dict]:
    con.execute(SCHEMA)
    df = pd.read_sql_query(f"SELECT {', '.join(COLS)} FROM paris_joueurs WHERE resultat IS NOT NULL ORDER BY date DESC",
                           con)
    out = []
    for r in df.itertuples():
        played = r.resultat >= 0
        out.append({"date": r.date, "player": r.joueur, "team": r.equipe, "opp": r.adversaire, "stat": r.stat,
                    "label": STATS.get(r.stat, r.stat), "threshold": int(r.seuil), "p": r.proba,
                    "min_odds": r.cote_mini, "signal": bool(r.signal),
                    "result": r.resultat if played else None, "won": (r.resultat >= r.seuil) if played else None})
    return out
