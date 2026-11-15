"""Moteur de prévision : étages 1 à 5.

Toutes les corrections sont exprimées en points d'écart « du point de vue de l'équipe
à domicile » (positif = favorise l'équipe qui reçoit).
L'étage 4 (croisement Four Factors) est écarté de la V1 : le backtest du 15/11/2026
montre qu'il n'apporte rien (règle d'ajout d'un facteur).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from math import erf, sqrt
from zoneinfo import ZoneInfo

import pandas as pd

from .ratings import Params, Ratings
from .teams import TEAMS, distance_km

ALTITUDE_TEAMS = {"DEN", "UTA"}


def win_prob(spread: float, sigma: float) -> float:
    """Étage 5 : écart prévu -> probabilité (loi normale d'écart-type sigma)."""
    return 0.5 * (1 + erf(spread / (sigma * sqrt(2))))


@dataclass
class Factor:
    key: str
    label: str
    points: float          # du point de vue de l'équipe à domicile
    team: str | None = None
    detail: str = ""       # explication en clair, propre au match


@dataclass
class Absence:
    team: str
    player: str
    status: str
    impact: float          # points d'écart perdus par l'équipe (positif)


@dataclass
class Prediction:
    home: str
    away: str
    spread: float          # écart prévu, domicile − extérieur
    p_home: float
    pace: float
    factors: list[Factor] = field(default_factory=list)
    absences: list[Absence] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["spread"] = round(self.spread, 2)
        d["p_home"] = round(self.p_home, 4)
        d["pace"] = round(self.pace, 1)
        for f in d["factors"]:
            f["points"] = round(f["points"], 2)
        for a in d["absences"]:
            a["impact"] = round(a["impact"], 2)
        return d


def _utc_offset_hours(tz: str, day: pd.Timestamp) -> float:
    dt = datetime(day.year, day.month, day.day, 19, tzinfo=ZoneInfo(tz))
    return dt.utcoffset().total_seconds() / 3600


@dataclass
class TeamContext:
    b2b: bool = False
    three_in_four: bool = False
    km: float = 0.0
    tz_hours: float = 0.0


def team_context(schedule: pd.DataFrame, team: str, day: pd.Timestamp, venue: str) -> TeamContext:
    """Étage 3 pour une équipe : repos et déplacement, à partir du calendrier."""
    prev = schedule[((schedule["home"] == team) | (schedule["away"] == team))
                    & (schedule["date"] < day) & (schedule["date"] >= day - timedelta(days=3))]
    ctx = TeamContext()
    if prev.empty:
        return ctx
    days = set((day - prev["date"]).dt.days)
    ctx.b2b = 1 in days
    ctx.three_in_four = len(prev) >= 2
    last = prev.sort_values("date").iloc[-1]
    ctx.km = distance_km(last["home"], venue)
    ctx.tz_hours = abs(_utc_offset_hours(TEAMS[venue].tz, day) - _utc_offset_hours(TEAMS[last["home"]].tz, day))
    return ctx


def predict(home: str, away: str, day: pd.Timestamp, r: Ratings, p: Params,
            schedule: pd.DataFrame | None = None,
            absences: list[Absence] | None = None,
            use_context: bool = True) -> Prediction:
    th, ta = r.team(home), r.team(away)

    # Étage 1 — force de base, ramenée au rythme prévu du match.
    pace = th["pace"] * ta["pace"] / r.league_pace
    lg = r.league_ortg
    home_pts = (th["off"] + ta["def"] - lg) * pace / 100
    away_pts = (ta["off"] + th["def"] - lg) * pace / 100
    nick = lambda a: TEAMS[a].name
    ranks = {a: i + 1 for i, a in enumerate(sorted(TEAMS, key=lambda a: -r.team(a)["net"]))}
    rank_txt = lambda a: "1er" if ranks[a] == 1 else f"{ranks[a]}e"
    factors = [Factor(
        "force", "Niveau des équipes cette saison", home_pts - away_pts, None,
        f"{nick(home)} {rank_txt(home)} de la ligue, {nick(away)} {rank_txt(away)} "
        f"(points marqués et encaissés, adversaires pris en compte)")]

    # Étage 3 — contexte du match.
    if use_context:
        factors.append(Factor("terrain", "Avantage du terrain", p.hca, home,
                              f"{nick(home)} jouent à domicile"))
        if home in ALTITUDE_TEAMS:
            factors.append(Factor("altitude", "Altitude", p.altitude, home,
                                  f"Salle en altitude : plus dur pour les {nick(away)}"))
        if schedule is not None:
            for team, sign in ((home, 1), (away, -1)):
                c = team_context(schedule, team, day, home)
                if c.b2b:
                    factors.append(Factor("veille", "Fatigue : match la veille", sign * p.b2b, team,
                                          f"{nick(team)} ont joué hier soir"))
                if c.three_in_four:
                    factors.append(Factor("3en4", "Fatigue : 3 matchs en 4 jours", sign * p.three_in_four, team,
                                          f"{nick(team)} enchaînent leur 3e match en 4 jours"))
                travel = c.km / 1000 * p.travel_per_1000km + c.tz_hours * p.tz_per_hour
                if abs(travel) >= 0.05:
                    tz = f", {c.tz_hours:.0f} h de décalage horaire" if c.tz_hours >= 1 else ""
                    factors.append(Factor("voyage", "Voyage", sign * travel, team,
                                          f"{nick(team)} : {c.km:,.0f} km depuis leur dernier match{tz}".replace(",", " ", 1)
                                          if c.km >= 1000 else
                                          f"{nick(team)} : {c.km:.0f} km depuis leur dernier match{tz}"))

    # Étage 2 — effectif du soir (version simplifiée : on retire l'impact des absents).
    absences = absences or []
    for team, sign in ((home, 1), (away, -1)):
        lost = sum(a.impact for a in absences if a.team == team)
        if lost:
            STATUS_FR = {"out": "absent", "doubtful": "douteux", "questionable": "incertain"}
            names = ", ".join(f"{a.player.split(' ', 1)[-1]} ({STATUS_FR.get(a.status.lower(), a.status)})"
                              for a in absences if a.team == team)
            factors.append(Factor("absents", "Joueurs absents", -sign * lost, team, f"{nick(team)} sans {names}"))

    spread = sum(f.points for f in factors)
    return Prediction(home, away, spread, win_prob(spread, p.sigma), pace, factors, absences)
