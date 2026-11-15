/** Fonction de répartition de la loi normale (approximation d'Abramowitz-Stegun, erreur < 1e-7). */
export function normCdf(x: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = 0.3989422804014327 * Math.exp((-x * x) / 2);
  const p = d * t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return x >= 0 ? 1 - p : p;
}

/** Probabilité de dépasser une ligne en .5 (« plus de »). */
export const probOver = (mean: number, sd: number, line: number) => 1 - normCdf((line - mean) / sd);

/** Cote minimum conseillée = (1 + marge) ÷ probabilité, arrondie au centième supérieur. */
export const minOdds = (p: number, margin: number) => Math.ceil((((1 + margin) / p) * 100) - 1e-9) / 100;

export const MARGIN_SPREAD = 0.05;
export const MARGIN_PLAYERS = 0.1;
