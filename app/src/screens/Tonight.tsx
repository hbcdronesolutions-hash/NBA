import { House, Moon } from "lucide-react";
import { Link } from "react-router-dom";
import { NightPickCard } from "../components/NightPickCard";
import { OddsPill } from "../components/OddsPill";
import { DemoChip, Empty, Loading, Page } from "../components/Page";
import { ProbBar } from "../components/ProbBar";
import { TeamLogo } from "../components/TeamLogo";
import { useToday } from "../data";
import { longDate, pct, tipTime } from "../format";
import { team } from "../teams";
import type { Game, Side } from "../types";

export function Tonight() {
  const { data, error } = useToday();
  return (
    <Page title="Ce soir" sub={data ? longDate(data.date) : " "} right={<DemoChip show={data?.demo} />}>
      {error && <Empty icon={<Moon />} title="Données indisponibles" text="Lance « python -m pronos soir » sur ton PC." />}
      {!data && !error && <Loading />}
      {data && data.games.length === 0 && <Empty icon={<Moon />} title="Pas de match cette nuit" />}
      {data && data.games.length > 0 && <NightPickCard games={data.games} />}
      {data && (
        <div className="stack">
          {[...data.games]
            .sort((a, b) => (a.tip_utc ?? "").localeCompare(b.tip_utc ?? ""))
            .map((g) => (
              <GameCard key={g.id} g={g} />
            ))}
        </div>
      )}
    </Page>
  );
}

function GameCard({ g }: { g: Game }) {
  const favHome = g.p_home >= 0.5;
  return (
    <Link to={`/match/${encodeURIComponent(g.id)}`} className="card game">
      <div className="game-top">
        <span className="time">{tipTime(g.tip_utc)}</span>
        {g.handicap?.signal && <span className="hcap">Signal handicap</span>}
        {g.divergence && <span className="flag">Écart bookmakers</span>}
        {g.result && <span className="final">Terminé</span>}
      </div>
      <Row g={g} side="home" fav={favHome} />
      <Row g={g} side="away" fav={!favHome} />
      <ProbBar away={g.away} home={g.home} pHome={g.p_home} pBookHome={g.p_book_home} divergence={g.divergence} />
    </Link>
  );
}

function Row({ g, side, fav }: { g: Game; side: Side; fav: boolean }) {
  const abbr = side === "home" ? g.home : g.away;
  const p = side === "home" ? g.p_home : 1 - g.p_home;
  const score = g.result?.[side];
  return (
    <div className={`game-row${fav ? " is-fav" : ""}`}>
      <TeamLogo abbr={abbr} size={36} />
      <span className="team-name">
        {team(abbr).name}
        {side === "home" && <House size={13} className="home-icon" aria-label="à domicile" />}
      </span>
      {score != null ? <span className="score">{score}</span> : <OddsPill value={g.min_odds[side]} verdict={g.verdict[side]} />}
      <span className="prob">
        {pct(p)}
        <small>%</small>
      </span>
    </div>
  );
}
