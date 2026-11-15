import type { ComponentType, SVGProps } from "react";
import * as L from "nba-team-logos";

type Logo = ComponentType<SVGProps<SVGSVGElement>>;

interface Meta {
  city: string;
  name: string;
  color: string;
  logo: Logo;
}

const t = (city: string, name: string, color: string, logo: Logo): Meta => ({ city, name, color, logo });

export const TEAMS: Record<string, Meta> = {
  ATL: t("Atlanta", "Hawks", "#E03A3E", L.ATL),
  BOS: t("Boston", "Celtics", "#007A33", L.BOS),
  BKN: t("Brooklyn", "Nets", "#1A1A1A", L.BK),
  CHA: t("Charlotte", "Hornets", "#00788C", L.CHA),
  CHI: t("Chicago", "Bulls", "#CE1141", L.CHI),
  CLE: t("Cleveland", "Cavaliers", "#860038", L.CLE),
  DAL: t("Dallas", "Mavericks", "#0064B1", L.DAL),
  DEN: t("Denver", "Nuggets", "#0E2240", L.DEN),
  DET: t("Detroit", "Pistons", "#C8102E", L.DET),
  GSW: t("Golden State", "Warriors", "#1D428A", L.GSW),
  HOU: t("Houston", "Rockets", "#CE1141", L.HOU),
  IND: t("Indiana", "Pacers", "#002D62", L.IND),
  LAC: t("LA", "Clippers", "#C8102E", L.LAC),
  LAL: t("Los Angeles", "Lakers", "#552583", L.LAL),
  MEM: t("Memphis", "Grizzlies", "#5D76A9", L.MEM),
  MIA: t("Miami", "Heat", "#98002E", L.MIA),
  MIL: t("Milwaukee", "Bucks", "#00471B", L.MIL),
  MIN: t("Minnesota", "Timberwolves", "#236192", L.MIN),
  NOP: t("New Orleans", "Pelicans", "#0C2340", L.NO),
  NYK: t("New York", "Knicks", "#F58426", L.NYK),
  OKC: t("Oklahoma City", "Thunder", "#007AC1", L.OKC),
  ORL: t("Orlando", "Magic", "#0077C0", L.ORL),
  PHI: t("Philadelphie", "76ers", "#006BB6", L.PHI),
  PHX: t("Phoenix", "Suns", "#E56020", L.PHX),
  POR: t("Portland", "Trail Blazers", "#E03A3E", L.POR),
  SAC: t("Sacramento", "Kings", "#5A2D81", L.SAC),
  SAS: t("San Antonio", "Spurs", "#6E7378", L.SAS),
  TOR: t("Toronto", "Raptors", "#CE1141", L.TOR),
  UTA: t("Utah", "Jazz", "#3E2680", L.UTA),
  WAS: t("Washington", "Wizards", "#002B5C", L.WAS),
};

export const team = (abbr: string): Meta =>
  TEAMS[abbr] ?? { city: abbr, name: abbr, color: "#888", logo: L.NBA };
