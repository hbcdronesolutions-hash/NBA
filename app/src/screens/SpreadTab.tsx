import { useState } from "react";
import { Stepper } from "../components/Stepper";
import { TeamLogo } from "../components/TeamLogo";
import { pick } from "../data";
import { odds, pct } from "../format";
import { MARGIN_SPREAD, minOdds, normCdf } from "../math";
import { team } from "../teams";
import type { Game } from "../types";

/** Écart de points : « gagne de X ou plus » pour une équipe, et l'inverse pour l'autre. */
export function SpreadTab({ g, sigma }: { g: Game; sigma: number }) {
  const fav = pick(g);
  const [side, setSide] = useState<"home" | "away">(fav.side);
  const [line, setLine] = useState(Math.max(1, Math.min(15, Math.round(Math.abs(g.spread)))));
  const abbr = side === "home" ? g.home : g.away;
  const other = side === "home" ? g.away : g.home;
  const mean = side === "home" ? g.spread : -g.spread; // écart moyen du point de vue de l'équipe choisie
  const p = 1 - normCdf((line - 0.5 - mean) / sigma);

  return (
    <>
      <div className="team-toggle">
        {(["away", "home"] as const).map((s) => {
          const a = s === "home" ? g.home : g.away;
          return (
            <button key={s} className={side === s ? "is-active" : ""} onClick={() => setSide(s)}>
              <TeamLogo abbr={a} size={26} />
              {team(a).name}
            </button>
          );
        })}
      </div>

      <div className="card line-card">
        <span className="line-caption">Victoire par</span>
        <Stepper value={line} onChange={setLine} min={1} max={15}>
          <span className="line-val">
            {line}
            <small> pts ou +</small>
          </span>
        </Stepper>
      </div>

      <div className="stack">
        <Outcome abbr={abbr} text={`gagne de ${line} ou +`} p={p} />
        <Outcome abbr={other} text={`ne perd pas de ${line} ou +`} p={1 - p} />
      </div>
      <p className="note">
        Écart prévu : {team(fav.abbr).name} de {Math.abs(g.spread).toFixed(1).replace(".", ",")} pts. Compare la cote minimum à
        celle de ton bookmaker.
      </p>
    </>
  );
}

export function Outcome({ abbr, text, p, margin = MARGIN_SPREAD }: { abbr: string; text: string; p: number; margin?: number }) {
  return (
    <div className={`card outcome${p >= 0.5 ? " is-likely" : ""}`}>
      <TeamLogo abbr={abbr} size={32} />
      <div className="outcome-main">
        <span className="outcome-team">{team(abbr).name}</span>
        <span className="outcome-text">{text}</span>
      </div>
      <div className="outcome-side">
        <span className="prob">
          {pct(p)}
          <small>%</small>
        </span>
        <span className="outcome-odds">min {odds(minOdds(p, margin))}</span>
      </div>
    </div>
  );
}
