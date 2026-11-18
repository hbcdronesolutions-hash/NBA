import type { JournalEntry, Side } from "./types";

export const conf = (e: JournalEntry) => Math.max(e.p_home, 1 - e.p_home);
export const pickSide = (e: JournalEntry): Side => (e.p_home >= 0.5 ? "home" : "away");
export const isHit = (e: JournalEntry) => (e.p_home >= 0.5 ? 1 : 0) === e.home_win;
const minOdds = (p: number) => Math.ceil(((1.05 / p) * 100) - 1e-9) / 100;

export interface Bet {
  side: Side;
  odds: number;
  min: number;
  won: boolean | null;
  profit: number | null; // en unités misées
}

/** Pari conseillé : pastille verte (cote du bookmaker ≥ cote minimum, sans dépasser +15 %). */
export function advisedBet(e: JournalEntry): Bet | null {
  if (!e.odds) return null;
  const sides: [Side, number, number][] = [
    ["home", e.odds[0], e.p_home],
    ["away", e.odds[1], 1 - e.p_home],
  ];
  for (const [side, o, p] of sides) {
    const min = minOdds(p);
    if (o >= min && o <= min * 1.15) {
      const won = e.home_win == null ? null : (side === "home") === (e.home_win === 1);
      return { side, odds: o, min, won, profit: won == null ? null : won ? o - 1 : -1 };
    }
  }
  return null;
}

export function summary(entries: JournalEntry[], threshold: number) {
  const done = entries.filter((e) => e.home_win != null);
  const sel = done.filter((e) => conf(e) >= threshold);
  const bets = done.map(advisedBet).filter((b): b is Bet => b != null && b.won != null);
  return {
    n: done.length,
    hits: done.filter(isHit).length,
    selN: sel.length,
    selHits: sel.filter(isHit).length,
    betN: bets.length,
    betWon: bets.filter((b) => b.won).length,
    profit: bets.reduce((a, b) => a + (b.profit ?? 0), 0),
  };
}

export function readThreshold(): number {
  try {
    const v = Number(localStorage.getItem("seuil"));
    return v >= 60 && v <= 80 ? v / 100 : 0.7;
  } catch {
    return 0.7;
  }
}

/**
 * « Désaccord bookmakers » : le modèle donne gagnante une équipe que le bookmaker voit perdante
 * (probabilité implicite < 50 %). Parmi ces cas, celui de plus forte espérance (p × cote − 1).
 */
export interface NightPick {
  side: Side;
  p: number;
  odds: number;
  ev: number;
  book: number; // probabilité des bookmakers pour la même équipe
}

export function nightPickFor(pHome: number, oddsHome: number, oddsAway: number): NightPick | null {
  const side: Side = pHome >= 0.5 ? "home" : "away";
  const p = Math.max(pHome, 1 - pHome);
  const o = side === "home" ? oddsHome : oddsAway;
  const ih = 1 / oddsHome;
  const ia = 1 / oddsAway;
  const book = side === "home" ? ih / (ih + ia) : ia / (ih + ia);
  if (book >= 0.5) return null;
  return { side, p, odds: o, ev: p * o - 1, book };
}

export function bestNightPick<T>(items: T[], get: (x: T) => NightPick | null): { item: T; pick: NightPick } | null {
  let best: { item: T; pick: NightPick } | null = null;
  for (const item of items) {
    const pick = get(item);
    if (pick && (!best || pick.ev > best.pick.ev)) best = { item, pick };
  }
  return best;
}

/** Paris du soir passés (un par soirée au plus), avec leur résultat. */
export function nightPicksHistory(entries: JournalEntry[]) {
  const byNight = new Map<string, JournalEntry[]>();
  for (const e of entries) if (e.odds) byNight.set(e.date, [...(byNight.get(e.date) ?? []), e]);
  const out: { date: string; e: JournalEntry; pick: NightPick; won: boolean | null; profit: number | null }[] = [];
  for (const [date, es] of byNight) {
    const b = bestNightPick(es, (e) => nightPickFor(e.p_home, e.odds![0], e.odds![1]));
    if (!b) continue;
    const won = b.item.home_win == null ? null : (b.pick.side === "home") === (b.item.home_win === 1);
    out.push({ date, e: b.item, pick: b.pick, won, profit: won == null ? null : won ? b.pick.odds - 1 : -1 });
  }
  return out.sort((a, b) => b.date.localeCompare(a.date));
}

/** Les k pronostics les plus sûrs d'une soirée : combien justes. */
export function topK(entries: JournalEntry[], k: number): { hits: number; n: number } | null {
  const done = entries.filter((e) => e.home_win != null).sort((a, b) => conf(b) - conf(a)).slice(0, k);
  if (done.length < k) return null;
  return { hits: done.filter(isHit).length, n: k };
}

/** Sur toutes les soirées : part des soirées « tous justes » et réussite globale des k plus sûrs. */
export function topKHistory(entries: JournalEntry[], k: number) {
  const nights = new Map<string, JournalEntry[]>();
  for (const e of entries) nights.set(e.date, [...(nights.get(e.date) ?? []), e]);
  let n = 0, allRight = 0, hits = 0;
  for (const es of nights.values()) {
    const t = topK(es, k);
    if (!t) continue;
    n += 1;
    hits += t.hits;
    if (t.hits === k) allRight += 1;
  }
  return { nights: n, allRight, hitRate: n ? hits / (n * k) : NaN };
}

/** Combinés du soir (1 unité par soir), en temps réel, aux meilleures cotes relevées. */
export type ComboKind = "all" | "top3" | "top2" | "selection";

export function comboHistory(entries: JournalEntry[], kind: ComboKind, threshold = 0.7) {
  const nights = new Map<string, JournalEntry[]>();
  for (const e of entries) if (e.home_win != null) nights.set(e.date, [...(nights.get(e.date) ?? []), e]);
  let n = 0, won = 0, profit = 0;
  let best = 0;
  for (const es of nights.values()) {
    const sorted = [...es].sort((a, b) => conf(b) - conf(a));
    const legs =
      kind === "all" ? sorted : kind === "top3" ? sorted.slice(0, 3) : kind === "top2" ? sorted.slice(0, 2)
        : sorted.filter((e) => conf(e) >= threshold);
    if (legs.length < (kind === "top3" ? 3 : 2) || legs.some((e) => !e.odds)) continue;
    const odds = legs.reduce((acc, e) => acc * (e.p_home >= 0.5 ? e.odds![0] : e.odds![1]), 1);
    const ok = legs.every(isHit);
    n += 1;
    if (ok) {
      won += 1;
      profit += odds - 1;
      best = Math.max(best, odds);
    } else profit -= 1;
  }
  return { n, won, profit, best };
}


/** Règle « handicap domicile » : notre écart prévu dépasse la ligne d'au moins 4 points pour le domicile. */
export const HANDICAP_EDGE = 4;

export function handicapBet(e: JournalEntry): { line: number; odds: number; result: "gagné" | "perdu" | "remboursé" | null; profit: number | null } | null {
  if (!e.line || e.spread == null || e.spread + e.line[0] < HANDICAP_EDGE) return null;
  const [line, odds] = e.line;
  if (!e.score) return { line, odds, result: null, profit: null };
  const cover = e.score[0] - e.score[1] + line;
  if (cover === 0) return { line, odds, result: "remboursé", profit: 0 };
  return cover > 0 ? { line, odds, result: "gagné", profit: odds - 1 } : { line, odds, result: "perdu", profit: -1 };
}

export function handicapHistory(entries: JournalEntry[]) {
  let n = 0, won = 0, push = 0, profit = 0;
  for (const e of entries) {
    const b = handicapBet(e);
    if (!b || b.result == null) continue;
    n += 1;
    if (b.result === "gagné") won += 1;
    if (b.result === "remboursé") push += 1;
    profit += b.profit ?? 0;
  }
  return { n, won, push, profit };
}
