import { Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { pct } from "../format";
import { bestNightPick, nightPickFor } from "../results";
import { team } from "../teams";
import type { Game } from "../types";
import { TeamLogo } from "./TeamLogo";

/** Encart discret : le plus gros désaccord du soir entre notre algorithme et les bookmakers (information, pas un conseil de pari). */
export function NightPickCard({ games }: { games: Game[] }) {
  const now = Date.now();
  const best = bestNightPick(
    games.filter((g) => g.odds && !g.result && (!g.tip_utc || new Date(g.tip_utc).getTime() > now)),
    (g) => nightPickFor(g.p_home, g.odds!.home, g.odds!.away),
  );
  if (!best) {
    return (
      <div className="nightpick nightpick-none">
        <Sparkles size={14} /> Pas de désaccord avec les bookmakers ce soir
      </div>
    );
  }
  const { item: g, pick } = best;
  const abbr = pick.side === "home" ? g.home : g.away;
  return (
    <Link to={`/match/${encodeURIComponent(g.id)}`} className="nightpick">
      <span className="nightpick-label">
        <Sparkles size={13} /> Désaccord bookmakers
      </span>
      <TeamLogo abbr={abbr} size={26} />
      <span className="nightpick-team">{team(abbr).name}</span>
      <span className="nightpick-info">
        {pct(pick.p)} % pour nous · {pct(pick.book)} % pour eux
      </span>
    </Link>
  );
}
