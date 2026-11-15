"""Référentiel des 30 franchises : identifiants NBA, salles, fuseaux, altitude."""
from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt


@dataclass(frozen=True)
class Team:
    abbr: str
    nba_id: int
    city: str
    name: str
    lat: float
    lon: float
    tz: str
    altitude_m: int = 0

    @property
    def full_name(self) -> str:
        return f"{self.city} {self.name}"


TEAMS: dict[str, Team] = {t.abbr: t for t in [
    Team("ATL", 1610612737, "Atlanta", "Hawks", 33.757, -84.396, "America/New_York", 320),
    Team("BOS", 1610612738, "Boston", "Celtics", 42.366, -71.062, "America/New_York", 6),
    Team("BKN", 1610612751, "Brooklyn", "Nets", 40.683, -73.976, "America/New_York", 10),
    Team("CHA", 1610612766, "Charlotte", "Hornets", 35.225, -80.839, "America/New_York", 230),
    Team("CHI", 1610612741, "Chicago", "Bulls", 41.881, -87.674, "America/Chicago", 180),
    Team("CLE", 1610612739, "Cleveland", "Cavaliers", 41.496, -81.688, "America/New_York", 200),
    Team("DAL", 1610612742, "Dallas", "Mavericks", 32.790, -96.810, "America/Chicago", 140),
    Team("DEN", 1610612743, "Denver", "Nuggets", 39.749, -105.008, "America/Denver", 1609),
    Team("DET", 1610612765, "Detroit", "Pistons", 42.341, -83.055, "America/New_York", 190),
    Team("GSW", 1610612744, "Golden State", "Warriors", 37.768, -122.388, "America/Los_Angeles", 5),
    Team("HOU", 1610612745, "Houston", "Rockets", 29.751, -95.362, "America/Chicago", 15),
    Team("IND", 1610612754, "Indiana", "Pacers", 39.764, -86.156, "America/New_York", 220),
    Team("LAC", 1610612746, "LA", "Clippers", 33.945, -118.341, "America/Los_Angeles", 30),
    Team("LAL", 1610612747, "Los Angeles", "Lakers", 34.043, -118.267, "America/Los_Angeles", 80),
    Team("MEM", 1610612763, "Memphis", "Grizzlies", 35.138, -90.051, "America/Chicago", 80),
    Team("MIA", 1610612748, "Miami", "Heat", 25.781, -80.188, "America/New_York", 2),
    Team("MIL", 1610612749, "Milwaukee", "Bucks", 43.045, -87.917, "America/Chicago", 190),
    Team("MIN", 1610612750, "Minnesota", "Timberwolves", 44.979, -93.276, "America/Chicago", 260),
    Team("NOP", 1610612740, "New Orleans", "Pelicans", 29.949, -90.082, "America/Chicago", 1),
    Team("NYK", 1610612752, "New York", "Knicks", 40.751, -73.993, "America/New_York", 10),
    Team("OKC", 1610612760, "Oklahoma City", "Thunder", 35.463, -97.515, "America/Chicago", 370),
    Team("ORL", 1610612753, "Orlando", "Magic", 28.539, -81.384, "America/New_York", 30),
    Team("PHI", 1610612755, "Philadelphia", "76ers", 39.901, -75.172, "America/New_York", 5),
    Team("PHX", 1610612756, "Phoenix", "Suns", 33.446, -112.071, "America/Phoenix", 330),
    Team("POR", 1610612757, "Portland", "Trail Blazers", 45.532, -122.667, "America/Los_Angeles", 15),
    Team("SAC", 1610612758, "Sacramento", "Kings", 38.580, -121.500, "America/Los_Angeles", 9),
    Team("SAS", 1610612759, "San Antonio", "Spurs", 29.427, -98.438, "America/Chicago", 200),
    Team("TOR", 1610612761, "Toronto", "Raptors", 43.643, -79.379, "America/Toronto", 76),
    Team("UTA", 1610612762, "Utah", "Jazz", 40.768, -111.901, "America/Denver", 1288),
    Team("WAS", 1610612764, "Washington", "Wizards", 38.898, -77.021, "America/New_York", 10),
]}

BY_ID = {t.nba_id: t for t in TEAMS.values()}

# Abréviations alternatives rencontrées selon les sources.
ALIASES = {
    "BRK": "BKN", "NJN": "BKN", "CHO": "CHA", "PHO": "PHX", "GS": "GSW", "NO": "NOP",
    "NOR": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS",
}

# Noms complets (rapport des blessures, cotes) -> abréviation.
FULL_NAMES = {t.full_name.lower(): t.abbr for t in TEAMS.values()}
FULL_NAMES["los angeles clippers"] = "LAC"


def abbr(code: str) -> str:
    code = code.strip().upper()
    return ALIASES.get(code, code)


def from_full_name(name: str) -> str | None:
    return FULL_NAMES.get(" ".join(name.lower().split()))


def distance_km(a: str, b: str) -> float:
    """Distance orthodromique entre deux salles."""
    ta, tb = TEAMS[a], TEAMS[b]
    la1, lo1, la2, lo2 = map(radians, (ta.lat, ta.lon, tb.lat, tb.lon))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))
