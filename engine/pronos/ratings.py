"""Étage 1 — force de base des équipes (notes d'attaque / défense pour 100 possessions).

- correction de la force des adversaires (résolution itérative) ;
- matchs récents plus lourds (poids divisé par deux tous les `half_life_days`) ;
- a priori de début de saison : note de la saison passée ramenée vers la moyenne,
  qui compte pour `prior_weight` matchs et s'efface à mesure que la saison avance.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .teams import TEAMS

ABBRS = sorted(TEAMS)
IDX = {a: i for i, a in enumerate(ABBRS)}
N = len(ABBRS)

LEAGUE_ORTG = 114.0
LEAGUE_PACE = 99.0


@dataclass
class Params:
    half_life_days: float = 60.0
    prior_weight: float = 8.0
    prior_regress: float = 0.70
    hca: float = 1.8
    altitude: float = 1.5
    b2b: float = -2.1
    three_in_four: float = -0.6
    travel_per_1000km: float = -0.15
    tz_per_hour: float = -0.15
    questionable_weight: float = 0.5
    sigma: float = 13.7
    roster_k: float = 1.0          # effectif du soir (valeur des joueurs), réglé par backtest
    rapm_damp: float = 3.0
    iterations: int = 15
    version: str = "v1.1"


@dataclass
class Ratings:
    """Notes à une date donnée, calculées uniquement avec les matchs antérieurs."""
    off: np.ndarray
    deff: np.ndarray
    pace: np.ndarray
    games: np.ndarray
    league_ortg: float
    league_pace: float
    extra: dict = field(default_factory=dict)

    def team(self, abbr: str) -> dict:
        i = IDX[abbr]
        return {
            "off": float(self.off[i]), "def": float(self.deff[i]),
            "net": float(self.off[i] - self.deff[i]), "pace": float(self.pace[i]),
            "games": int(self.games[i]),
        }

    def regressed(self, k: float) -> "Ratings":
        """A priori pour la saison suivante : k × (note − moyenne) + moyenne."""
        lg = self.league_ortg
        return Ratings(
            off=lg + k * (self.off - lg), deff=lg + k * (self.deff - lg),
            pace=self.league_pace + k * (self.pace - self.league_pace),
            games=np.zeros(N), league_ortg=lg, league_pace=self.league_pace,
        )


def neutral_prior() -> Ratings:
    return Ratings(np.full(N, LEAGUE_ORTG), np.full(N, LEAGUE_ORTG), np.full(N, LEAGUE_PACE),
                   np.zeros(N), LEAGUE_ORTG, LEAGUE_PACE)


def compute(season_games: pd.DataFrame, asof: pd.Timestamp, prior: Ratings, p: Params) -> Ratings:
    """Notes au matin de `asof` à partir des matchs terminés de la saison avant cette date.

    `season_games` : colonnes date, home, away, home_pts, away_pts, poss.
    """
    g = season_games[(season_games["date"] < asof) & season_games["home_pts"].notna()]
    if g.empty:
        r = prior.regressed(1.0)
        return r

    age = (asof - g["date"]).dt.days.to_numpy(dtype=float)
    w = 0.5 ** (age / p.half_life_days)
    h = g["home"].map(IDX).to_numpy()
    a = g["away"].map(IDX).to_numpy()
    poss = g["poss"].to_numpy(dtype=float)
    ppp_h = g["home_pts"].to_numpy(dtype=float) / poss * 100
    ppp_a = g["away_pts"].to_numpy(dtype=float) / poss * 100
    half_hca = p.hca / 2 * 100 / poss  # on retire l'avantage du terrain des performances

    # Observations offensives : (attaque, défense adverse, valeur, poids)
    off_t = np.concatenate([h, a])
    def_t = np.concatenate([a, h])
    val = np.concatenate([ppp_h - half_hca, ppp_a + half_hca])
    ww = np.concatenate([w, w])
    pp = np.concatenate([poss, poss])

    k_lg = 60.0
    lg = float((np.sum(ww * val) + k_lg * prior.league_ortg) / (np.sum(ww) + k_lg))
    lg_pace = float((np.sum(ww * pp) + k_lg * prior.league_pace) / (np.sum(ww) + k_lg))

    pw = p.prior_weight
    # A priori recentré sur la moyenne de la saison en cours.
    pri_off = prior.off - prior.league_ortg + lg
    pri_def = prior.deff - prior.league_ortg + lg
    pri_pace = prior.pace - prior.league_pace + lg_pace

    wsum_off = np.bincount(off_t, ww, N)
    wsum_def = np.bincount(def_t, ww, N)
    off, deff = pri_off.copy(), pri_def.copy()
    for _ in range(p.iterations):
        new_off = (np.bincount(off_t, ww * (val - (deff[def_t] - lg)), N) + pw * pri_off) / (wsum_off + pw)
        new_def = (np.bincount(def_t, ww * (val - (off[off_t] - lg)), N) + pw * pri_def) / (wsum_def + pw)
        off, deff = new_off, new_def
    # Recentrage : la moyenne des notes reste la moyenne de la ligue.
    off += lg - off.mean()
    deff += lg - deff.mean()

    pace = (np.bincount(off_t, ww * pp, N) + pw * pri_pace) / (wsum_off + pw)
    games = np.bincount(off_t, None, N)
    return Ratings(off, deff, pace, games, lg, lg_pace)
