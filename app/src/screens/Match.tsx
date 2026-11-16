import { ChevronLeft, House } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { OddsPill, VERDICT_LABEL } from "../components/OddsPill";
import { Empty, Loading } from "../components/Page";
import { Segmented } from "../components/Segmented";
import { PlayersTab } from "./PlayersTab";
import { SpreadTab } from "./SpreadTab";
import { useState } from "react";
import { ProbBar } from "../components/ProbBar";
import { TeamLogo } from "../components/TeamLogo";
import { pick, useToday } from "../data";
import { num1, odds, pct, tipTime } from "../format";
import { team } from "../teams";
import type { Factor, Game, Side } from "../types";

const STATUS: Record<string, string> = { out: "Absent", doubtful: "Douteux", questionable: "Incertain" };

export function Match() {
  const { id } = useParams();
  const { data } = useToday();
  const g = data?.games.find((x) => x.id === id);
  return (
    <main className="page page-detail">
      <header className="detail-head">
        <Link to="/" className="back" aria-label="Retour">
          <ChevronLeft size={24} />
        </Link>
        <span className="time">{g ? tipTime(g.tip_utc) : ""}</span>
        <span style={{ width: 32 }} />
      </header>
      {!data ? (
        <Loading />
      ) : !g ? (
        <Empty
          icon={<ChevronLeft />}
          title="Ce match n'est plus au programme"
          text="Retrouve les matchs de ce soir dans l'onglet Ce soir, et les résultats dans Résultats."
        />
      ) : (
        <Detail g={g} sigma={data.sigma ?? 13.7} />
      )}
    </main>
  );
}

type Tab = "winner" | "spread" | "players";

function Detail({ g, sigma }: { g: Game; sigma: number }) {
  const [tab, setTab] = useState<Tab>("winner");
  const fav = pick(g);
  const factors = mergeFactors(g.factors);
  const maxAbs = Math.max(2, ...factors.map((f) => Math.abs(f.points)));
  return (
    <>
      <section className="hero">
        <HeroTeam abbr={g.home} p={g.p_home} fav={fav.side === "home"} home />
        <span className="hero-at">vs</span>
        <HeroTeam abbr={g.away} p={1 - g.p_home} fav={fav.side === "away"} />
      </section>
      <ProbBar away={g.away} home={g.home} pHome={g.p_home} pBookHome={g.p_book_home} divergence={g.divergence} height={8} />
      <p className="spread">
        <TeamLogo abbr={fav.abbr} size={18} /> {team(fav.abbr).name} par <b>{num1(Math.abs(g.spread))}</b> pts
        {g.p_book_home != null && (
          <span className={`book${g.divergence ? " is-alert" : ""}`}>
            Bookmakers {pct(fav.side === "home" ? g.p_book_home : 1 - g.p_book_home)} %
          </span>
        )}
      </p>

      <div className="tabs-wrap">
        <Segmented<Tab>
          value={tab}
          onChange={setTab}
          options={[
            { value: "winner", label: "Vainqueur" },
            { value: "spread", label: "Écart" },
            { value: "players", label: "Joueurs" },
          ]}
        />
      </div>
      {tab === "spread" && <SpreadTab g={g} sigma={sigma} />}
      {tab === "players" && <PlayersTab g={g} />}
      {tab === "winner" && (
        <>
      <h2 className="section first">Ce qui fait pencher</h2>
      <p className="factor-intro">
        Le modèle additionne ces éléments, en points d'écart au score final. Résultat :{" "}
        <b>
          {team(fav.abbr).name} par {num1(Math.abs(g.spread))} pts
        </b>
        .
      </p>
      <div className="card list">
        {factors.map((f) => {
          const who = f.points >= 0 ? g.home : g.away; // équipe avantagée par cette ligne
          return (
            <div key={f.key + (f.team ?? "")} className="factor">
              <div className="factor-main">
                <span className="factor-label">{f.label}</span>
                {f.detail && <span className="factor-detail">{f.detail}</span>}
                <span className="factor-bar">
                  <span style={{ width: `${(Math.abs(f.points) / maxAbs) * 100}%`, background: team(who).color }} />
                </span>
              </div>
              <div className="factor-side">
                <span className="factor-val">+{num1(Math.abs(f.points))}</span>
                <span className="factor-who">
                  <TeamLogo abbr={who} size={16} />
                  {team(who).name}
                </span>
              </div>
            </div>
          );
        })}
        <div className="factor factor-total">
          <span className="factor-label">Écart prévu</span>
          <div className="factor-side">
            <span className="factor-val">+{num1(Math.abs(g.spread))}</span>
            <span className="factor-who">
              <TeamLogo abbr={fav.abbr} size={16} />
              {team(fav.abbr).name}
            </span>
          </div>
        </div>
      </div>

      {g.absences.length > 0 && (
        <>
          <h2 className="section">Absents</h2>
          <div className="card list">
            {g.absences.map((a) => (
              <div key={a.team + a.player} className="absent">
                <TeamLogo abbr={a.team} size={22} />
                <span className="absent-name">{a.player}</span>
                <span className={`status status-${a.status.toLowerCase()}`}>{STATUS[a.status.toLowerCase()] ?? a.status}</span>
                <span className="factor-val">−{num1(a.impact)}</span>
              </div>
            ))}
          </div>
        </>
      )}

      <h2 className="section">Cotes</h2>
      <div className="odds-grid">
        {(["home", "away"] as Side[]).map((s) => (
          <OddsCard key={s} g={g} side={s} />
        ))}
      </div>
      {g.odds?.books && g.odds.books.length > 1 && (
        <div className="card list books">
          <div className="books-row books-head">
            <span />
            <TeamLogo abbr={g.home} size={20} />
            <TeamLogo abbr={g.away} size={20} />
          </div>
          {g.odds.books.map((b) => (
            <div key={b.book} className="books-row">
              <span className="books-name">{b.book}</span>
              <span className={b.home === g.odds!.home ? "is-best" : ""}>{odds(b.home)}</span>
              <span className={b.away === g.odds!.away ? "is-best" : ""}>{odds(b.away)}</span>
            </div>
          ))}
        </div>
      )}
      {g.odds && g.odds.french === false && <p className="note">Cotes françaises indisponibles : cotes américaines (DraftKings) affichées.</p>}
      <p className="legend">
        <span className="pill pill-vert"><span className="pill-dot" /></span> cote ≥ minimum
        <span className="pill pill-gris"><span className="pill-dot" /></span> ne pas miser
        <span className="pill pill-orange"><span className="pill-dot" /></span> à vérifier
      </p>
        </>
      )}
    </>
  );
}

function HeroTeam({ abbr, p, fav, home }: { abbr: string; p: number; fav: boolean; home?: boolean }) {
  return (
    <div className={`hero-team${fav ? " is-fav" : ""}`}>
      <TeamLogo abbr={abbr} size={76} />
      <span className="hero-name">
        {team(abbr).name}
        {home && <House size={13} className="home-icon" aria-label="à domicile" />}
      </span>
      <span className="hero-prob">
        {pct(p)}
        <small>%</small>
      </span>
    </div>
  );
}

function OddsCard({ g, side }: { g: Game; side: Side }) {
  const abbr = side === "home" ? g.home : g.away;
  const v = g.verdict[side];
  const book = g.odds?.[side];
  return (
    <div className="card odds-card">
      <div className="odds-team">
        <TeamLogo abbr={abbr} size={24} />
        <span>{team(abbr).name}</span>
      </div>
      <dl>
        <dt>Minimum</dt>
        <dd>
          <OddsPill value={g.min_odds[side]} verdict={v} />
        </dd>
        <dt>Équilibre</dt>
        <dd>{odds(g.fair_odds[side])}</dd>
        <dt>{(side === "home" ? g.odds?.book_home : g.odds?.book_away) ?? g.odds?.book ?? "Bookmaker"}</dt>
        <dd>{book ? odds(book) : "—"}</dd>
      </dl>
      <span className={`verdict verdict-${v}`}>{VERDICT_LABEL[v]}</span>
    </div>
  );
}

/** Regroupe les corrections de même nature (ex. déplacement) par équipe. */
function mergeFactors(fs: Factor[]): Factor[] {
  const out: Factor[] = [];
  for (const f of fs) {
    const same = out.find((o) => o.key === f.key && o.team === f.team);
    if (same) same.points += f.points;
    else out.push({ ...f });
  }
  return out.filter((f) => Math.abs(f.points) >= 0.05);
}
