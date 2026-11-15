import { Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { odds, pct } from "../format";
import { bestNightPick, nightPickFor } from "../results";
import { team } from "../teams";
import type { Game } from "../types";
import { TeamLogo } from "./TeamLogo";

/** Encart discret : le pari du soir (désaccord modèle / bookmaker, meilleure espérance). */
export function NightPickCard({ games }: { games: Game[] }) {
  const now = Date.now();
  const best = bestNightPick(
    games.filter((g) => g.odds && !g.result && (!g.tip_utc || new Date(g.tip_utc).getTime() > now)),
    (g) => nightPickFor(g.p_home, g.odds!.home, g.odds!.away),
  );
  if (!best) {
    return (
      <div className="nightpick nightpick-none">
        <Sparkles size={14} /> Pas de pari du soir
      </div>
    );
  }
  const { item: g, pick } = best;
  const abbr = pick.side === "home" ? g.home : g.away;
  const book = pick.side === "home" ? g.odds?.book_home : g.odds?.book_away;
  return (
    <Link to={`/match/${encodeURIComponent(g.id)}`} className="nightpick">
      <span className="nightpick-label">
        <Sparkles size={13} /> Pari du soir
      </span>
      <TeamLogo abbr={abbr} size={26} />
      <span className="nightpick-team">{team(abbr).name}</span>
      <span className="nightpick-info">
        {odds(pick.odds)}
        {book ? ` · ${book}` : ""} · {pct(pick.p)} %
      </span>
    </Link>
  );
}
