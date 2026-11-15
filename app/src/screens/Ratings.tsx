import { ChartNoAxesColumn } from "lucide-react";
import { Empty, Loading, Page } from "../components/Page";
import { Sparkline } from "../components/Sparkline";
import { TeamLogo } from "../components/TeamLogo";
import { useRatings } from "../data";
import { num1, signed } from "../format";
import { team } from "../teams";

export function Ratings() {
  const { data, error } = useRatings();
  return (
    <Page title="Forces" sub="Note nette pour 100 possessions">
      {error && <Empty icon={<ChartNoAxesColumn />} title="Données indisponibles" />}
      {!data && !error && <Loading />}
      {data && (
        <div className="card list">
          {data.teams.map((t) => (
            <div key={t.abbr} className="rank-row">
              <span className="rank">{t.rank}</span>
              <TeamLogo abbr={t.abbr} size={32} />
              <span className="rank-main">
                <span className="rank-name">{team(t.abbr).name}</span>
                <span className="rank-sub">
                  <span title="Attaque">↗ {num1(t.off)}</span>
                  <span title="Défense">↘ {num1(t.def)}</span>
                </span>
              </span>
              <Sparkline values={t.trend} color={team(t.abbr).color} />
              <span className={`net ${t.net >= 0 ? "pos" : "neg"}`}>{signed(t.net)}</span>
            </div>
          ))}
        </div>
      )}
      {data && (
        <p className="note">
          ↗ points marqués · ↘ points encaissés, pour 100 possessions. Courbe : 15 derniers matchs.
        </p>
      )}
    </Page>
  );
}
