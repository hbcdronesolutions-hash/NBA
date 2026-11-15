"""Rapport officiel des blessures NBA (PDF publié plusieurs fois par jour).

« Out » et « Doubtful » comptent comme absents, « Questionable » comme 50 %.
"""
from __future__ import annotations

import io
import re
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .teams import TEAMS, from_full_name

ET = ZoneInfo("America/New_York")
BASE = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{d}_{t}.pdf"
STATUSES = ("Out", "Doubtful", "Questionable", "Probable", "Available")

_TEAM_RE = re.compile("|".join(sorted((re.escape(t.full_name) for t in TEAMS.values()), key=len, reverse=True)))
_PLAYER_RE = re.compile(
    r"(?P<last>[A-Z][\w'.\-]*(?: [\w'.\-]+)*?), (?P<first>[\w'.\-]+(?: [\w'.\-]+)*?) "
    r"(?P<status>" + "|".join(STATUSES) + r")\b"
)
_DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")


def candidate_urls(now: datetime, hours_back: int = 24) -> list[str]:
    """URLs possibles, de la plus récente à la plus ancienne (pas de 15 min et formats horaires)."""
    now = now.astimezone(ET).replace(second=0, microsecond=0)
    now -= timedelta(minutes=now.minute % 15)
    urls = []
    for k in range(hours_back * 4):
        t = now - timedelta(minutes=15 * k)
        urls.append(BASE.format(d=t.strftime("%Y-%m-%d"), t=t.strftime("%I_%M%p")))
        if t.minute == 0:
            urls.append(BASE.format(d=t.strftime("%Y-%m-%d"), t=t.strftime("%I%p")))
    return urls


def parse_text(text: str) -> list[dict]:
    """Extrait (date du match, équipe, joueur, statut, raison) du texte du PDF."""
    out, team, game_date = [], None, None
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line or line.startswith(("Page ", "Game Date", "Injury Report")):
            continue
        if m := _DATE_RE.search(line):
            game_date = datetime.strptime(m.group(1), "%m/%d/%Y").date().isoformat()
        teams_found = list(_TEAM_RE.finditer(line))
        if teams_found:
            last = teams_found[-1]
            team = from_full_name(last.group(0))
            line = line[last.end():].strip()
        else:
            # On retire date / heure / affiche éventuelles en début de ligne.
            line = re.sub(r"^(\d{2}/\d{2}/\d{4} )?(\d{2}:\d{2} \(ET\) )?([A-Z]{2,3}@[A-Z]{2,3} )?", "", line)
        m = _PLAYER_RE.match(line)
        if m and team:
            out.append({
                "date": game_date, "team": team,
                "player": f"{m.group('last')}, {m.group('first')}",
                "status": m.group("status"),
                "reason": line[m.end():].strip(),
            })
    return out


def fetch_latest(now: datetime | None = None) -> tuple[str | None, list[dict]]:
    import pdfplumber
    import requests

    now = now or datetime.now(ET)
    for url in candidate_urls(now):
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                text = "\n".join(page.extract_text(x_tolerance=1.5) or "" for page in pdf.pages)
            return url, parse_text(text)
    return None, []


def store(con: sqlite3.Connection, report: str, rows: list[dict]) -> int:
    con.executemany(
        "INSERT OR REPLACE INTO blessures VALUES (?,?,?,?,?,?)",
        [(report, r["date"], r["team"], r["player"], r["status"], r["reason"]) for r in rows])
    con.commit()
    return len(rows)


def latest_for(con: sqlite3.Connection, day: str) -> list[dict]:
    """Dernier rapport enregistré pour une date de match."""
    row = con.execute("SELECT rapport FROM blessures WHERE date_match=? ORDER BY rapport DESC LIMIT 1",
                      (day,)).fetchone()
    if not row:
        return []
    rows = con.execute("SELECT equipe, joueur, statut FROM blessures WHERE rapport=? AND date_match=?",
                       (row["rapport"], day)).fetchall()
    return [{"team": r["equipe"], "player": r["joueur"], "status": r["statut"]} for r in rows]
