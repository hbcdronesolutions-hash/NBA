import { Info, Target } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { DemoChip, Empty, Loading, Page } from "../components/Page";
import { TeamLogo } from "../components/TeamLogo";
import { badge, comboMinOdds, pick, useToday } from "../data";
import { odds, pct, tipTime } from "../format";
import { team } from "../teams";

const KEY = "seuil";
const readThreshold = () => {
  try {
    const v = Number(localStorage.getItem(KEY));
    return v >= 60 && v <= 80 ? v : 70;
  } catch {
    return 70;
  }
};

export function Selection() {
  const { data, error } = useToday();
  const [threshold, setThreshold] = useState(readThreshold);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, String(threshold));
    } catch {
      /* stockage indisponible */
    }
  }, [threshold]);

  const picks = (data?.games ?? [])
    .map((g) => ({ g, ...pick(g) }))
    .filter((x) => x.p * 100 >= threshold)
    .sort((a, b) => b.p - a.p);
  const allRight = picks.reduce((acc, x) => acc * x.p, 1);
  const allGreen = picks.length >= 2 && picks.every((x) => x.g.verdict[x.side] === "vert");

  return (
    <Page title="Sélection" sub="Les matchs les plus sûrs" right={<DemoChip show={data?.demo} />}>
      <div className="card threshold">
        <div className="threshold-head">
          <span>Confiance minimum</span>
          <b>{threshold} %</b>
        </div>
        <input
          type="range"
          min={60}
          max={80}
          step={1}
          value={threshold}
          onChange={(e) => setThreshold(Number(e.target.value))}
          style={{ ["--fill" as string]: `${((threshold - 60) / 20) * 100}%` }}
          aria-label="Seuil de confiance"
        />
      </div>

      {error && <Empty icon={<Target />} title="Données indisponibles" />}
      {!data && !error && <Loading />}
      {data && picks.length === 0 && (
        <Empty icon={<Target />} title="Aucun match assez sûr ce soir" text="Baisse le seuil ou reviens demain." />
      )}

      <div className="stack">
        {picks.map(({ g, abbr, p, side }) => {
          const b = badge(p);
          const opp = side === "home" ? g.away : g.home;
          const missing = g.absences.filter((a) => a.team === abbr || a.team === opp);
          return (
            <Link key={g.id} to={`/match/${encodeURIComponent(g.id)}`} className="card pick">
              <TeamLogo abbr={abbr} size={52} />
              <div className="pick-main">
                <span className="pick-team">{team(abbr).name}</span>
                <span className="pick-vs">
                  {side === "home" ? "reçoit" : "chez"} <TeamLogo abbr={opp} size={16} /> {team(opp).name} · {tipTime(g.tip_utc)}
                </span>
                {missing.length > 0 && (
                  <span className="pick-missing">Sans {missing.map((a) => a.player.split(" ").slice(-1)[0]).join(", ")}</span>
                )}
              </div>
              <div className="pick-side">
                <span className="prob">
                  {pct(p)}
                  <small>%</small>
                </span>
                {b && <span className={`badge badge-${b.tone}`}>{b.label}</span>}
              </div>
            </Link>
          );
        })}
      </div>

      {picks.length >= 2 && (
        <div className="card summary">
          <div>
            <span className="summary-label">Tous justes</span>
            <span className="summary-val">{pct(allRight)} %</span>
          </div>
          {allGreen && (
            <div>
              <span className="summary-label">Combiné · cote min</span>
              <span className="summary-val">{odds(comboMinOdds(picks.map((x) => x.p)))}</span>
            </div>
          )}
        </div>
      )}

      <p className="note">
        <Info size={14} /> Réussir toute la sélection est bien moins probable que chaque match pris seul.
      </p>
    </Page>
  );
}
