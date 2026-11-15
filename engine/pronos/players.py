"""Étage 2 — valeur d'impact des joueurs (calcul maison V1) et minutes prévues.

Impact = Game Score ramené à 36 minutes, comparé à un remplaçant, converti en points
pour 100 possessions. Volontairement simple : à remplacer par DARKO / EPM si accessibles.
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

from .model import Absence

REPLACEMENT_GS36 = 9.0      # Game Score / 36 min d'un joueur de rotation remplaçable
POINTS_PER_GS = 0.40        # conversion en points pour 100 possessions
SHRINK_MINUTES = 200.0      # a priori : 200 minutes au niveau remplaçant
STATUS_WEIGHT = {"out": 1.0, "doubtful": 1.0, "questionable": 0.5}


def game_score(df: pd.DataFrame) -> pd.Series:
    return (df["pts"] + 0.4 * df["fgm"] - 0.7 * df["fga"] - 0.4 * (df["fta"] - df["ftm"])
            + 0.7 * df["oreb"] + 0.3 * df["dreb"] + df["stl"] + 0.7 * df["ast"]
            + 0.7 * df["blk"] - 0.4 * df["pf"] - df["tov"])


def player_table(logs: pd.DataFrame, asof: pd.Timestamp, rosters: dict[int, str] | None = None) -> pd.DataFrame:
    """Une ligne par joueur : équipe actuelle, minutes prévues (10 derniers matchs), impact."""
    logs = logs[logs["date"] < asof].copy()
    if logs.empty:
        return pd.DataFrame(columns=["player_id", "name", "team", "minutes", "impact"])
    logs["gs"] = game_score(logs)
    logs = logs.sort_values("date")
    rows = []
    for pid, g in logs.groupby("player_id"):
        mins = g["minutes"].sum()
        gs36 = (36 * g["gs"].sum() + REPLACEMENT_GS36 * SHRINK_MINUTES) / (mins + SHRINK_MINUTES)
        rows.append({
            "player_id": pid,
            "name": g["name"].iloc[-1],
            "team": (rosters or {}).get(int(pid), g["team"].iloc[-1]),
            "minutes": float(g["minutes"].tail(10).mean()),
            "impact": max(0.0, (gs36 - REPLACEMENT_GS36) * POINTS_PER_GS),
        })
    return pd.DataFrame(rows)


def normalize(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    if "," in name:  # « Nom, Prénom » du rapport officiel
        last, first = name.split(",", 1)
        name = f"{first} {last}"
    name = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", name.lower())
    return re.sub(r"[^a-z]", "", name)


def absences_for(team: str, injuries: list[dict], players: pd.DataFrame, pace: float) -> list[Absence]:
    """Convertit les lignes du rapport des blessures en points d'écart perdus."""
    out = []
    roster = players[players["team"] == team]
    by_name = {normalize(n): r for n, r in zip(roster["name"], roster.itertuples())}
    for inj in injuries:
        if inj["team"] != team:
            continue
        weight = STATUS_WEIGHT.get(inj["status"].lower())
        if not weight:
            continue
        r = by_name.get(normalize(inj["player"]))
        if r is None:
            continue
        pts = r.impact * r.minutes / 48 * pace / 100 * weight
        if pts >= 0.05:
            out.append(Absence(team, r.name, inj["status"], pts))
    return sorted(out, key=lambda a: -a.impact)
