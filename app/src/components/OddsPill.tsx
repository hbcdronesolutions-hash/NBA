import { odds } from "../format";
import type { Verdict } from "../types";

export const VERDICT_LABEL: Record<Verdict, string> = {
  vert: "Intéressant",
  gris: "Ne pas miser",
  orange: "À vérifier",
  aucune: "Pas de cote",
};

/** Cote minimum conseillée, colorée selon la cote du bookmaker. */
export function OddsPill({ value, verdict }: { value: number; verdict: Verdict }) {
  return (
    <span className={`pill pill-${verdict}`} title={VERDICT_LABEL[verdict]}>
      <span className="pill-dot" />
      {odds(value)}
    </span>
  );
}
