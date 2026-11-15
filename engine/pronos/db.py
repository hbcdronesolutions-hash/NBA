"""Base SQLite : un simple fichier, rien à installer."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .teams import TEAMS

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "pronos.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS equipes (
    abbr TEXT PRIMARY KEY, nba_id INTEGER, ville TEXT, nom TEXT,
    lat REAL, lon REAL, fuseau TEXT, altitude INTEGER
);
CREATE TABLE IF NOT EXISTS joueurs (
    id INTEGER PRIMARY KEY, nom TEXT, equipe TEXT, impact REAL, maj TEXT
);
CREATE TABLE IF NOT EXISTS matchs (
    id TEXT PRIMARY KEY, saison TEXT, date TEXT, heure_utc TEXT,
    domicile TEXT, exterieur TEXT, score_dom INTEGER, score_ext INTEGER,
    statut TEXT DEFAULT 'prevu'
);
CREATE INDEX IF NOT EXISTS idx_matchs_date ON matchs(date);
CREATE TABLE IF NOT EXISTS stats_equipe_match (
    match_id TEXT, equipe TEXT, points INTEGER, possessions REAL,
    fgm INTEGER, fga INTEGER, fg3m INTEGER, fta INTEGER, ftm INTEGER,
    oreb INTEGER, dreb INTEGER, tov INTEGER,
    PRIMARY KEY (match_id, equipe)
);
CREATE TABLE IF NOT EXISTS stats_joueur_match (
    match_id TEXT, joueur_id INTEGER, equipe TEXT, minutes REAL,
    pts INTEGER, fgm INTEGER, fga INTEGER, ftm INTEGER, fta INTEGER,
    oreb INTEGER, dreb INTEGER, ast INTEGER, stl INTEGER, blk INTEGER,
    tov INTEGER, pf INTEGER,
    PRIMARY KEY (match_id, joueur_id)
);
CREATE TABLE IF NOT EXISTS blessures (
    rapport TEXT, date_match TEXT, equipe TEXT, joueur TEXT, statut TEXT, raison TEXT,
    PRIMARY KEY (rapport, equipe, joueur)
);
CREATE TABLE IF NOT EXISTS cotes (
    match_id TEXT, bookmaker TEXT, cote_dom REAL, cote_ext REAL, releve TEXT,
    PRIMARY KEY (match_id, bookmaker, releve)
);
CREATE TABLE IF NOT EXISTS notes_equipes (
    date TEXT, equipe TEXT, attaque REAL, defense REAL, rythme REAL,
    PRIMARY KEY (date, equipe)
);
-- Effectif actuel de chaque équipe (transferts pris en compte avant le premier match).
CREATE TABLE IF NOT EXISTS effectifs (
    joueur_id INTEGER PRIMARY KEY, nom TEXT, equipe TEXT, maj TEXT
);
-- Journal des prévisions : une ligne par match, jamais modifiée ensuite.
CREATE TABLE IF NOT EXISTS previsions (
    match_id TEXT PRIMARY KEY, proba_dom REAL, ecart_dom REAL,
    corrections TEXT, absents TEXT, version TEXT, enregistre TEXT
);
"""


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT OR IGNORE INTO equipes VALUES (?,?,?,?,?,?,?,?)",
        [(t.abbr, t.nba_id, t.city, t.name, t.lat, t.lon, t.tz, t.altitude_m) for t in TEAMS.values()],
    )
    con.commit()
    return con
