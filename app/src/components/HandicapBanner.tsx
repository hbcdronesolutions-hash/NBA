import { Link } from "react-router-dom";
import { team } from "../teams";
import { odds } from "../format";
import type { Game } from "../types";
import { TeamLogo } from "./TeamLogo";

export const fmtLine = (l: number) => `${l > 0 ? "+" : l < 0 ? "−" : ""}${Math.abs(l).toFixed(1).replace(".", ",")}`;

/** Bandeau « Signal handicap » en haut de Ce soir : tous les matchs signalés, cliquables. */
export function HandicapBanner({ games }: { games: Game[] }) {
  const sig = games.filter((g) => g.handicap?.signal && !g.result);
  if (!sig.length) return <div className="hbanner hbanner-none">Pas de signal handicap ce soir</div>;
  return (
    <div className="hbanner">
      <span className="hbanner-title">
        {sig.length > 1 ? `${sig.length} signaux handicap ce soir` : "Signal handicap ce soir"}
      </span>
      {sig.map((g) => (
        <Link key={g.id} to={`/match/${encodeURIComponent(g.id)}`} className="hbanner-row">
          <TeamLogo abbr={g.home} size={24} />
          <span className="hbanner-team">
            {team(g.home).name} {fmtLine(g.handicap!.line)}
          </span>
          <span className="hbanner-odds">{odds(g.handicap!.odds_home)}</span>
        </Link>
      ))}
    </div>
  );
}
