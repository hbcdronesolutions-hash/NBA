"""Section 4 — rejouer les saisons passées match par match.

Règle absolue : chaque prévision n'utilise que les matchs joués avant le jour du match.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import replace

import numpy as np
import pandas as pd

from . import ratings as R
from .model import predict


def replay(games: pd.DataFrame, p: R.Params, use_context: bool = True) -> pd.DataFrame:
    """Une prévision par match terminé, toutes saisons confondues (chronologique)."""
    rows = []
    prior = R.neutral_prior()
    for season, sg in games.groupby("season", sort=True):
        sg = sg.sort_values("date")
        done = sg[sg["home_pts"].notna()]
        r = prior
        for day, dg in done.groupby("date", sort=True):
            r = R.compute(sg, day, prior, p)
            for g in dg.itertuples():
                pr = predict(g.home, g.away, day, r, p, schedule=sg, use_context=use_context)
                rows.append({
                    "season": season, "date": day, "id": g.id, "home": g.home, "away": g.away,
                    "spread": pr.spread, "p_home": pr.p_home,
                    "margin": g.home_pts - g.away_pts, "home_win": int(g.home_pts > g.away_pts),
                })
        end = R.compute(sg, sg["date"].max() + pd.Timedelta(days=1), prior, p)
        prior = end.regressed(p.prior_regress)
    return pd.DataFrame(rows)


def metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0}
    p = df["p_home"].clip(1e-6, 1 - 1e-6)
    y = df["home_win"]
    pick_p = np.maximum(p, 1 - p)
    hit = ((p >= 0.5) == (y == 1)).astype(int)
    return {
        "n": int(len(df)),
        "accuracy": float(hit.mean()),
        "logloss": float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()),
        "brier": float(((p - y) ** 2).mean()),
        "calibration": calibration(pick_p, hit),
    }


def calibration(pick_p: pd.Series, hit: pd.Series) -> list[dict]:
    bins = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
    out = []
    for lo, hi in bins:
        m = (pick_p >= lo) & (pick_p < hi)
        if m.sum():
            out.append({"bin": f"{int(lo*100)}-{min(int(hi*100), 100)}", "lo": lo, "n": int(m.sum()),
                        "confidence": float(pick_p[m].mean()), "hit": float(hit[m].mean())})
    return out


def selection(df: pd.DataFrame) -> dict:
    """Section 8 : sélection des matchs les plus sûrs par soirée."""
    d = df.copy()
    d["conf"] = np.maximum(d["p_home"], 1 - d["p_home"])
    d["hit"] = ((d["p_home"] >= 0.5) == (d["home_win"] == 1)).astype(int)
    nights = d.sort_values("conf", ascending=False).groupby("date")
    out = {}
    for k in (1, 3, 4):
        top = nights.head(k)
        out[f"top{k}"] = {"per_night": k, "accuracy": float(top["hit"].mean())}
    for th in (0.65, 0.70, 0.75):
        sel = d[d["conf"] >= th]
        out[f"conf{int(th*100)}"] = {
            "per_night": float(len(sel) / d["date"].nunique()),
            "accuracy": float(sel["hit"].mean()) if len(sel) else None,
        }
    for k in (2, 3, 4):
        top = nights.head(k)
        full = top.groupby("date").filter(lambda g: len(g) == k)
        if len(full):
            out[f"combo{k}"] = float(full.groupby("date")["hit"].min().mean())
    return out


def tune(games: pd.DataFrame, train: list[str], valid: str, base: R.Params | None = None) -> tuple[R.Params, list]:
    """Réglages sur les saisons anciennes, vérification sur la suivante (sans y toucher)."""
    base = base or R.Params()
    keep = train + [valid]
    sub = games[games["season"] <= max(keep)]
    results = []
    for hl, pw in itertools.product([30, 45, 60, 90, 150], [4, 8, 16]):
        p = replace(base, half_life_days=hl, prior_weight=pw)
        bt = replay(sub, p)
        tr = bt[bt["season"].isin(train)]
        sigma = float(np.std(tr["margin"] - tr["spread"]))
        p = replace(p, sigma=round(sigma, 2))
        tr = tr.assign(p_home=_reprob(tr, p.sigma))
        results.append((metrics(tr)["logloss"], p))
    best = min(results, key=lambda x: x[0])[1]
    return best, results


def _reprob(df: pd.DataFrame, sigma: float) -> pd.Series:
    return df["spread"].apply(lambda s: 0.5 * (1 + math.erf(s / (sigma * math.sqrt(2)))))


def baselines(games: pd.DataFrame, seasons: list[str]) -> dict:
    """Repères naïfs : domicile gagne toujours, meilleur bilan avant le match."""
    home, better = [], []
    for season, sg in games[games["season"].isin(seasons) & games["home_pts"].notna()].groupby("season"):
        wins: dict[str, list[int]] = {}
        for g in sg.sort_values("date").itertuples():
            hw = int(g.home_pts > g.away_pts)
            home.append(hw)
            rec_h = np.mean(wins.get(g.home, [0.5]))
            rec_a = np.mean(wins.get(g.away, [0.5]))
            better.append(int((rec_h >= rec_a) == bool(hw)))
            wins.setdefault(g.home, []).append(hw)
            wins.setdefault(g.away, []).append(1 - hw)
    return {"home_always": float(np.mean(home)) if home else None,
            "better_record": float(np.mean(better)) if better else None}
