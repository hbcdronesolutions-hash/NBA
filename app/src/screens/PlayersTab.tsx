import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { Segmented } from "../components/Segmented";
import { Stepper } from "../components/Stepper";
import { TeamLogo } from "../components/TeamLogo";
import { num1, odds, pct } from "../format";
import { MARGIN_PLAYERS, minOdds, probOver } from "../math";
import { team } from "../teams";
import type { Game, PlayerForecast } from "../types";

type Stat = "pts" | "reb" | "ast" | "pra";
const STATS: { value: Stat; label: string; long: string }[] = [
  { value: "pts", label: "PTS", long: "points" },
  { value: "reb", label: "REB", long: "rebonds" },
  { value: "ast", label: "PAS", long: "passes" },
  { value: "pra", label: "P+R+P", long: "pts + rebonds + passes" },
];

export function PlayersTab({ g }: { g: Game }) {
  const [side, setSide] = useState<"home" | "away">("home");
  const [open, setOpen] = useState<number | null>(null);
  const abbr = side === "home" ? g.home : g.away;
  const players = (g.players ?? []).filter((p) => p.team === abbr);

  return (
    <>
      <div className="team-toggle">
        {(["home", "away"] as const).map((s) => {
          const a = s === "home" ? g.home : g.away;
          return (
            <button key={s} className={side === s ? "is-active" : ""} onClick={() => { setSide(s); setOpen(null); }}>
              <TeamLogo abbr={a} size={26} />
              {team(a).name}
            </button>
          );
        })}
      </div>

      <div className="card list">
        <div className="pl-head">
          <span />
          <span>MIN</span>
          <span>PTS</span>
          <span>REB</span>
          <span>PAS</span>
        </div>
        {players.map((p) => (
          <div key={p.id}>
            <button className={`pl-row${open === p.id ? " is-open" : ""}`} onClick={() => setOpen(open === p.id ? null : p.id)}>
              <span className="pl-name">
                {p.name}
                {p.status === "questionable" && <span className="pl-flag">Incertain</span>}
              </span>
              <span className="pl-min">{Math.round(p.minutes)}</span>
              <span>{num1(p.pts)}</span>
              <span>{num1(p.reb)}</span>
              <span>{num1(p.ast)}</span>
              <ChevronDown size={16} className="pl-chev" />
            </button>
            {open === p.id && <Lines p={p} />}
          </div>
        ))}
        {players.length === 0 && <p className="empty-text pl-empty">Pas de prévision pour cette équipe.</p>}
      </div>
      <p className="note">Prévisions des joueurs à 20 min ou plus. Marge de sécurité de 10 % : pas encore vérifiée contre de vraies lignes.</p>
    </>
  );
}

function Lines({ p }: { p: PlayerForecast }) {
  const [stat, setStat] = useState<Stat>("pts");
  const mean = p[stat];
  const sd = p.sd[stat];
  const [line, setLine] = useState(Math.floor(mean) + 0.5);
  const change = (s: Stat) => {
    setStat(s);
    setLine(Math.floor(p[s]) + 0.5);
  };
  const over = probOver(mean, sd, line);
  const long = STATS.find((s) => s.value === stat)!.long;
  return (
    <div className="pl-lines">
      <Segmented value={stat} options={STATS.map((s) => ({ value: s.value, label: s.label }))} onChange={change} />
      <div className="pl-forecast">
        Prévision <b>{num1(mean)}</b> {long}
      </div>
      <Stepper value={line} onChange={setLine} min={0.5} max={Math.ceil(mean + 3 * sd) + 0.5}>
        <span className="line-val">
          {num1(line)}
          <small> {long}</small>
        </span>
      </Stepper>
      <div className="pl-outcomes">
        <Side label="Plus de" p={over} />
        <Side label="Moins de" p={1 - over} />
      </div>
    </div>
  );
}

function Side({ label, p }: { label: string; p: number }) {
  return (
    <div className={`pl-side${p >= 0.5 ? " is-likely" : ""}`}>
      <span className="pl-side-label">{label}</span>
      <span className="pl-side-p">{pct(p)} %</span>
      <span className="outcome-odds">min {odds(minOdds(p, MARGIN_PLAYERS))}</span>
    </div>
  );
}
