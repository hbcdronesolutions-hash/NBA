import { Info, UserRound } from "lucide-react";
import { useMemo, useState } from "react";
import { Empty, Loading, Page } from "../components/Page";
import { Segmented } from "../components/Segmented";
import { TeamLogo } from "../components/TeamLogo";
import { useProps } from "../data";
import { longDate, num1, odds, pct } from "../format";
import { team } from "../teams";
import type { PropPick, PropResult, PropStat, PropsData } from "../types";

const STAT_SHORT: Record<PropStat, string> = { pts: "pts", reb: "reb", ast: "passes", pra: "pts+reb+pas" };
const STAT_OPTIONS: { value: PropStat; label: string }[] = [
  { value: "pts", label: "Points" },
  { value: "reb", label: "Rebonds" },
  { value: "ast", label: "Passes" },
  { value: "pra", label: "P+R+P" },
];

/** « 8 points ou + » s'écrit « + de 7,5 » chez le bookmaker. */
const betclic = (k: number) => `+ de ${num1(k - 0.5)}`;

function PickCard({ p }: { p: PropPick }) {
  return (
    <div className={`card prop-pick${p.signal ? " is-signal" : ""}`}>
      <TeamLogo abbr={p.team} size={40} />
      <div className="prop-main">
        <span className="prop-player">{p.player}</span>
        <span className="prop-bet">
          {p.threshold} {p.label} ou + <small>({betclic(p.threshold)})</small>
        </span>
        <span className="prop-why">
          Prévu {num1(p.expected)} · habituel {num1(p.usual)}
          {p.absent_pts >= 10 && <> · {p.absent_pts} pts d'absents dans son équipe</>}
        </span>
        <span className="prop-vs">
          contre <TeamLogo abbr={p.opp} size={14} /> {team(p.opp).name}
        </span>
      </div>
      <div className="prop-side">
        <span className="prop-p">
          {pct(p.p)}
          <small>%</small>
        </span>
        <span className="prop-min">cote mini</span>
        <span className="prop-odds">{odds(p.min_odds)}</span>
      </div>
    </div>
  );
}

function Tracker({ history }: { history: PropResult[] }) {
  const done = history.filter((h) => h.won !== null);
  const sum = (rows: PropResult[]) => {
    const n = rows.length;
    const won = rows.filter((r) => r.won).length;
    const expected = n ? rows.reduce((a, r) => a + r.p, 0) / n : 0;
    return { n, won, rate: n ? won / n : 0, expected };
  };
  const sig = sum(done.filter((h) => h.signal));
  const fb = sum(done.filter((h) => !h.signal));
  if (!done.length)
    return <div className="card empty-card">Le suivi commence ce soir : chaque pari est noté le lendemain avec le vrai résultat du joueur.</div>;
  return (
    <>
      <div className="kpis">
        <div className="card kpi kpi-big">
          <span className="kpi-val">
            {sig.won}/{sig.n}
          </span>
          <span className="kpi-label">
            Signaux réussis{sig.n ? ` · ${pct(sig.rate)} % (annoncé ${pct(sig.expected)} %)` : ""}
          </span>
        </div>
        <div className="card kpi">
          <span className="kpi-val">
            {fb.won}/{fb.n}
          </span>
          <span className="kpi-label">
            À défaut réussis{fb.n ? ` · ${pct(fb.rate)} % (annoncé ${pct(fb.expected)} %)` : ""}
          </span>
        </div>
      </div>
      <div className="card list prop-history">
        {done.slice(0, 20).map((h, i) => (
          <div key={i} className="prop-hist-row">
            <span className={`prop-dot ${h.won ? "won" : "lost"}`} />
            <span className="prop-hist-main">
              <b>{h.player}</b> {h.threshold} {STAT_SHORT[h.stat]} ou +
              <small>
                {longDate(h.date)} · {pct(h.p)} %{h.signal ? " · signal" : ""}
              </small>
            </span>
            <span className="prop-hist-res">{h.result}</span>
          </div>
        ))}
      </div>
    </>
  );
}

function AllLines({ data }: { data: PropsData }) {
  const [stat, setStat] = useState<PropStat>("pts");
  const byMatch = useMemo(() => {
    const m = new Map<string, NonNullable<PropsData["players"]>>();
    for (const p of data.players ?? []) {
      if (!m.has(p.match_id)) m.set(p.match_id, []);
      m.get(p.match_id)!.push(p);
    }
    return [...m.values()];
  }, [data]);
  return (
    <>
      <Segmented value={stat} options={STAT_OPTIONS} onChange={setStat} />
      <div className="stack" style={{ marginTop: 12 }}>
        {byMatch.map((players) => {
          const sorted = [...players].sort((a, b) => (b.stats[stat]?.expected ?? 0) - (a.stats[stat]?.expected ?? 0));
          const t = [...new Set(players.map((p) => p.team))];
          return (
            <div key={players[0].match_id} className="card list prop-lines">
              <div className="prop-lines-head">
                <TeamLogo abbr={t[0]} size={20} /> {team(t[0]).name} – <TeamLogo abbr={t[1] ?? t[0]} size={20} />{" "}
                {team(t[1] ?? t[0]).name}
              </div>
              {sorted.map((p) => {
                const s = p.stats[stat];
                if (!s) return null;
                return (
                  <div key={p.player} className="prop-line-row">
                    <div className="prop-line-name">
                      <TeamLogo abbr={p.team} size={16} /> <b>{p.player}</b>
                      <small>
                        prévu {num1(s.expected)} · au moins {num1(s.low)}, 7 fois sur 10
                      </small>
                    </div>
                    <div className="prop-ladder">
                      {s.ladder.map((l) => (
                        <span key={l.line} className={`prop-rung${l.p >= 0.7 ? " hi" : ""}`}>
                          <b>+ de {num1(l.line)}</b>
                          <span>{pct(l.p)} %</span>
                          <small>mini {odds(Math.max(1.01, 1 / l.p))}</small>
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </>
  );
}

export function Joueurs() {
  const { data, error } = useProps();
  const signals = data?.signals ?? [];
  const fallback = data?.fallback ?? [];
  return (
    <Page title="Joueurs" sub={data?.date ? longDate(data.date) : "Paris joueurs du soir"}>
      {error && <Empty icon={<UserRound />} title="Données indisponibles" text="Reviens après la prochaine mise à jour." />}
      {!data && !error && <Loading />}
      {data && (
        <>
          <p className="note first-note">
            <Info size={14} />
            Ne joue un pari que si la cote du bookmaker est au moins égale à la cote mini. Mise identique et petite, pas de
            combiné.
          </p>

          <h2 className="section">Signaux du soir</h2>
          {signals.length ? (
            <div className="stack">
              {signals.map((p) => (
                <PickCard key={`${p.player_id}-${p.stat}`} p={p} />
              ))}
            </div>
          ) : (
            <div className="card empty-card">
              Aucun signal ce soir : aucun joueur ne dépasse nettement son niveau habituel (+3 pts, +1,5 rebond, +1,5 passe ou +4
              pts+reb+passes).
            </div>
          )}

          {fallback.length > 0 && (
            <>
              <h2 className="section">À défaut · moins solides</h2>
              <div className="stack">
                {fallback.map((p) => (
                  <PickCard key={`${p.player_id}-${p.stat}`} p={p} />
                ))}
              </div>
            </>
          )}

          <h2 className="section">Suivi des paris joueurs</h2>
          <Tracker history={data.history ?? []} />

          {(data.players?.length ?? 0) > 0 && (
            <>
              <h2 className="section">Toutes les lignes</h2>
              <AllLines data={data} />
            </>
          )}
        </>
      )}
    </Page>
  );
}
