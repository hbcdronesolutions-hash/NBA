from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from pronos import betting as B
from pronos import ratings as R
from pronos.backtest import replay
from pronos.injuries import parse_text
from pronos.model import win_prob


def test_win_prob_matches_spec_example():
    # Fiche : un écart prévu de +5 points donne environ 66 %.
    assert win_prob(5, 13.7) == pytest.approx(0.642, abs=0.02)
    assert win_prob(0, 13.7) == 0.5


def test_min_odds_examples_from_spec():
    assert B.min_odds(0.57) == 1.85
    assert B.min_odds(0.43) == 2.45
    assert B.min_odds(0.665) == 1.58
    assert B.fair_odds(0.5) == 2.0


def test_verdict_colours():
    assert B.verdict(1.90, 1.85) == "vert"
    assert B.verdict(1.80, 1.85) == "gris"
    assert B.verdict(2.20, 1.85) == "orange"
    assert B.verdict(None, 1.85) == "aucune"


def test_combo_and_badges():
    assert B.combo_min_odds([0.8, 0.8]) == pytest.approx(1.65, abs=0.01)
    assert B.badge(0.76) == "Très sûr" and B.badge(0.72) == "Sûr" and B.badge(0.66) == "Correct"
    assert B.badge(0.6) is None


def _league(seed=1, days=120):
    rng = np.random.default_rng(seed)
    true = dict(zip(R.ABBRS, rng.normal(0, 6, 30)))
    rows, d0 = [], date(2025, 10, 21)
    for k in range(days):
        teams = list(rng.permutation(R.ABBRS))
        for i in range(0, 14, 2):
            h, a = teams[i], teams[i + 1]
            m = (true[h] - true[a]) + 2 + rng.normal(0, 11)
            rows.append({"id": f"{k}-{i}", "season": "2025-26", "date": pd.Timestamp(d0 + timedelta(days=k)),
                         "home": h, "away": a, "home_pts": 112 + m / 2, "away_pts": 112 - m / 2, "poss": 100.0})
    return pd.DataFrame(rows), true


def test_ratings_recover_true_strength():
    games, true = _league()
    r = R.compute(games, games["date"].max() + pd.Timedelta(days=1), R.neutral_prior(), R.Params())
    est = [r.team(a)["net"] for a in R.ABBRS]
    assert np.corrcoef(est, [true[a] for a in R.ABBRS])[0, 1] > 0.9


def test_no_leakage_changing_a_score_only_affects_later_games():
    games, _ = _league(days=30)
    p = R.Params()
    base = replay(games, p, use_context=False)
    target = games.iloc[100]
    altered = games.copy()
    altered.loc[altered["id"] == target["id"], "home_pts"] += 40
    alt = replay(altered, p, use_context=False)
    same_day_or_before = base["date"] <= target["date"]
    assert np.allclose(base.loc[same_day_or_before, "p_home"], alt.loc[same_day_or_before, "p_home"])
    assert not np.allclose(base.loc[~same_day_or_before, "p_home"], alt.loc[~same_day_or_before, "p_home"])


def test_injury_report_parsing():
    text = """Injury Report: 11/15/26 05:00 PM
Game Date Game Time Matchup Team Player Name Current Status Reason
11/15/2026 07:30 (ET) NYK@TOR New York Knicks Brunson, Jalen Questionable Injury/Illness - Left Ankle; Sprain
Robinson, Mitchell Out Injury/Illness - Left Ankle; Surgery
Toronto Raptors Jackson Jr., Jaren Doubtful Injury/Illness - Back
10:30 (ET) CHA@LAC Charlotte Hornets NOT YET SUBMITTED
"""
    rows = parse_text(text)
    assert [(r["team"], r["player"], r["status"]) for r in rows] == [
        ("NYK", "Brunson, Jalen", "Questionable"),
        ("NYK", "Robinson, Mitchell", "Out"),
        ("TOR", "Jackson Jr., Jaren", "Doubtful"),
    ]
    assert rows[0]["date"] == "2026-11-15"


def test_french_books_preferred_and_best_odds(tmp_path):
    from pronos.db import connect
    from pronos.service import match_odds

    con = connect(tmp_path / "t.sqlite")
    con.executemany("INSERT INTO cotes VALUES (?,?,?,?,?)", [
        ("m1", "DraftKings", 1.50, 2.80, "2026-11-15T10:00:00+00:00"),
        ("m1", "Betclic (FR)", 1.55, 2.40, "2026-11-15T09:00:00+00:00"),
        ("m1", "Betclic (FR)", 1.58, 2.35, "2026-11-15T12:00:00+00:00"),
        ("m1", "Winamax (FR)", 1.52, 2.50, "2026-11-15T12:00:00+00:00"),
    ])
    o = match_odds(con, "m1")
    assert o["french"] and len(o["books"]) == 2
    assert (o["home"], o["book_home"]) == (1.58, "Betclic")
    assert (o["away"], o["book_away"]) == (2.50, "Winamax")
