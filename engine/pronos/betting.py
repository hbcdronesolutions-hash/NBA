"""Section 10 — cote minimum conseillée, pastilles, combinés, badges de fiabilité."""
from __future__ import annotations

import math

MARGIN_WINNER = 0.05   # vainqueur / écart de points (fiabilité vérifiée sur 2 saisons)
MARGIN_PLAYERS = 0.10  # paris joueurs (pas encore vérifiés)
MARGIN_COMBO = 0.05
CHECK_RATIO = 1.15     # au-delà : pastille orange « à vérifier »
DIVERGENCE = 0.05      # signal quand modèle et bookmakers divergent de plus de 5 points de %


def ceil2(x: float) -> float:
    return math.ceil(round(x * 100, 6)) / 100


def min_odds(p: float, margin: float = MARGIN_WINNER) -> float:
    """Cote en dessous de laquelle il ne faut pas miser, arrondie au centième supérieur."""
    return ceil2((1 + margin) / p)


def fair_odds(p: float) -> float:
    return round(1 / p, 2)


def verdict(book: float | None, minimum: float) -> str:
    """'vert' (intéressant), 'gris' (ne pas miser), 'orange' (à vérifier), 'aucune'."""
    if not book:
        return "aucune"
    if book > minimum * CHECK_RATIO:
        return "orange"
    return "vert" if book >= minimum else "gris"


def book_probability(odds_home: float, odds_away: float) -> float:
    """Probabilité implicite du domicile, marge du bookmaker retirée."""
    ih, ia = 1 / odds_home, 1 / odds_away
    return ih / (ih + ia)


def badge(p: float) -> str | None:
    if p >= 0.75:
        return "Très sûr"
    if p >= 0.70:
        return "Sûr"
    if p >= 0.65:
        return "Correct"
    return None


def combo_min_odds(probs: list[float]) -> float:
    return ceil2((1 + MARGIN_COMBO) / math.prod(probs))
