export type Side = "home" | "away";
export type Verdict = "vert" | "gris" | "orange" | "aucune";

export interface Factor {
  key: string;
  label: string;
  points: number; // point de vue de l'équipe à domicile
  team: string | null;
}

export interface Absence {
  team: string;
  player: string;
  status: string;
  impact: number;
}

export interface PlayerForecast {
  id: number;
  name: string;
  team: string;
  status: string | null;
  minutes: number;
  pts: number;
  reb: number;
  ast: number;
  pra: number;
  sd: { pts: number; reb: number; ast: number; pra: number };
}

export interface Game {
  id: string;
  tip_utc: string | null;
  home: string;
  away: string;
  spread: number;
  p_home: number;
  pace: number;
  factors: Factor[];
  absences: Absence[];
  min_odds: Record<Side, number>;
  fair_odds: Record<Side, number>;
  odds: { book: string; home: number; away: number } | null;
  p_book_home: number | null;
  divergence: boolean;
  verdict: Record<Side, Verdict>;
  result: { home: number; away: number } | null;
  players?: PlayerForecast[];
}

export interface Today {
  generated_at: string;
  date: string;
  demo: boolean;
  version: string;
  sigma: number;
  games: Game[];
}

export interface TeamRating {
  abbr: string;
  off: number;
  def: number;
  net: number;
  pace: number;
  games: number;
  trend: number[];
  rank: number;
}

export interface Ratings {
  date: string;
  league: { ortg: number; pace: number };
  teams: TeamRating[];
}

export interface JournalEntry {
  id: string;
  date: string;
  home: string;
  away: string;
  p_home: number;
  home_win: number | null;
  score: [number, number] | null;
  odds: [number, number] | null;
}

export interface CalibrationBin {
  bin: string;
  lo: number;
  n: number;
  confidence: number;
  hit: number;
}

export interface Backtest {
  source?: string;
  seasons: string[];
  n: number;
  accuracy: number;
  logloss: number;
  calibration: CalibrationBin[];
  baselines: { home_always: number | null; better_record: number | null };
  selection: Record<string, { per_night: number; accuracy: number | null } | number>;
  books?: { n: number; model_accuracy: number; model_logloss: number; book_accuracy: number; book_logloss: number } | null;
}

export interface RecordData {
  journal: JournalEntry[];
  backtest: Backtest | null;
}
