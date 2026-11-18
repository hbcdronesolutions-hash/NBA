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
      {g.handicap && <HandicapCard g={g} />}

      <div className="team-toggle">
        {(["home", "away"] as const).map((s) => {
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

function HandicapCard({ g }: { g: Game }) {
  const h = g.handicap!;
  const home = team(g.home).name;
  const lineTxt = `${h.line > 0 ? "+" : h.line < 0 ? "−" : ""}${Math.abs(h.line).toFixed(1).replace(".", ",")}`;
  const ours = g.spread >= 0 ? `${home} par ${g.spread.toFixed(1).replace(".", ",")}` : `${team(g.away).name} par ${(-g.spread).toFixed(1).replace(".", ",")}`;
  return (
    <div className={`card hcap-card${h.signal ? " is-on" : ""}`}>
      <div className="hcap-head">
        <span>Règle handicap domicile</span>
        <b>{h.signal ? "Signal" : "Pas de signal"}</b>
      </div>
      <dl>
        <dt>Handicap du bookmaker ({h.book})</dt>
        <dd>
          {home} {lineTxt} · {odds(h.odds_home)}
        </dd>
        <dt>Notre écart prévu</dt>
        <dd>{ours}</dd>
        <dt>Notre avance sur le bookmaker</dt>
        <dd>{(h.edge > 0 ? "+" : h.edge < 0 ? "−" : "") + Math.abs(h.edge).toFixed(1).replace(".", ",")} pts</dd>
      </dl>
      <p className="hcap-rule">{handicapSentence(home, h.line)}</p>
      <p className="hcap-note">
        Signal quand nous voyons l'équipe à domicile au moins 4 pts plus forte que le bookmaker, qu'elle soit favorite ou
        outsider. Test sur 3 saisons : 55 % de réussite (290 paris), non prouvé.
      </p>
    </div>
  );
}

/** Ce qu'il faut pour gagner le pari handicap de l'équipe à domicile, en clair. */
export function handicapSentence(name: string, line: number): string {
  if (line < 0) {
    const need = Number.isInteger(line) ? -line + 1 : Math.ceil(-line);
    const push = Number.isInteger(line) ? ` (exactement ${-line} : remboursé)` : "";
    return `Pour gagner ce pari, les ${name} doivent gagner de ${need} points ou plus${push}.`;
  }
  if (line > 0) {
    const max = Number.isInteger(line) ? line - 1 : Math.floor(line);
    const push = Number.isInteger(line) ? ` (défaite de exactement ${line} : remboursé)` : "";
    return `Pour gagner ce pari, les ${name} doivent gagner, ou perdre de ${max} point${max > 1 ? "s" : ""} ou moins${push}.`;
  }
  return `Pour gagner ce pari, les ${name} doivent gagner (match nul impossible : remboursé en cas d'égalité).`;
}
