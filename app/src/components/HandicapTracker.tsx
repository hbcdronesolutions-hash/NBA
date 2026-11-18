import { handicapHistory } from "../results";
import { pct, signed } from "../format";
import type { JournalEntry } from "../types";

export const HANDICAP_TARGET = 80;
const BREAK_EVEN = 0.53; // réussite minimum pour gagner de l'argent à cote ~1,90

/** Suivi de la règle handicap vers 80 paris, avec verdict une fois le cap atteint. */
export function HandicapTracker({ journal }: { journal: JournalEntry[] }) {
  const h = handicapHistory(journal.filter((e) => e.live !== false));
  const decided = h.n - h.push;
  const rate = decided ? h.won / decided : NaN;
  const done = h.n >= HANDICAP_TARGET;
  const verdict = !done
    ? `Encore ${HANDICAP_TARGET - h.n} paris avant de conclure`
    : rate >= BREAK_EVEN && h.profit > 0
      ? "Objectif atteint : la règle tient sur 80 paris"
      : "Objectif non atteint : la règle ne tient pas";
  return (
    <div className={`card htrack${done ? (rate >= BREAK_EVEN && h.profit > 0 ? " is-ok" : " is-ko") : ""}`}>
      <div className="htrack-head">
        <span>Règle handicap domicile</span>
        <b>
          {h.n}/{HANDICAP_TARGET} paris
        </b>
      </div>
      <div className="htrack-bar">
        <span style={{ width: `${Math.min(100, (h.n / HANDICAP_TARGET) * 100)}%` }} />
      </div>
      <div className="htrack-stats">
        <div>
          <b>{decided ? `${pct(rate)} %` : "—"}</b>
          <small>réussite (objectif 53 %)</small>
        </div>
        <div>
          <b className={h.n ? (h.profit >= 0 ? "pos" : "neg") : ""}>{h.n ? `${signed(h.profit)} u` : "—"}</b>
          <small>résultat</small>
        </div>
        <div>
          <b>
            {h.won}/{decided}
          </b>
          <small>gagnés{h.push ? ` · ${h.push} remb.` : ""}</small>
        </div>
      </div>
      <p className="htrack-verdict">{verdict}</p>
    </div>
  );
}
