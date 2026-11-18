import { ListChecks } from "lucide-react";
import { Check, House, Sparkles, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Empty, Loading, Page } from "../components/Page";
import { TeamLogo } from "../components/TeamLogo";
import { useRecord } from "../data";
import { odds, pct, shortDate, signed } from "../format";
import { advisedBet, bestNightPick, handicapBet, isHit, nightPickFor, pickSide, readThreshold, summary, topK } from "../results";
import { team } from "../teams";
import { HandicapTracker } from "../components/HandicapTracker";
import type { JournalEntry, Side } from "../types";

export function Results() {
  const { data, error } = useRecord();
  const nights = useMemo(() => {
    const m = new Map<string, JournalEntry[]>();
    for (const e of data?.journal ?? []) if (e.home_win != null) m.set(e.date, [...(m.get(e.date) ?? []), e]);
    return [...m.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [data]);
  const [sel, setSel] = useState<string | null>(null);
  const night = nights.find(([d]) => d === sel) ?? nights[0];
  const th = readThreshold();
  const s = night ? summary(night[1], th) : null;
  const live = night?.[1].some((e) => e.live);
  const nightPickId = night
    ? bestNightPick(night[1].filter((e) => e.odds), (e) => nightPickFor(e.p_home, e.odds![0], e.odds![1]))?.item.id
    : undefined;

  return (
    <Page title="Résultats" sub={night ? shortDate(night[0]) : " "}>
      {error && <Empty icon={<ListChecks />} title="Données indisponibles" />}
      {!data && !error && <Loading />}
      {data && nights.length === 0 && (
        <Empty icon={<ListChecks />} title="Pas encore de résultat" text="Les scores arrivent le lendemain matin." />
      )}

      {data && <HandicapTracker journal={data.journal} />}

      {nights.length > 0 && (
        <div className="nights">
          {nights.map(([d, es]) => {
            const ns = summary(es, th);
            return (
              <button key={d} className={`night${d === night?.[0] ? " is-active" : ""}`} onClick={() => setSel(d)}>
                <span className="night-date">{shortDate(d).replace(".", "")}</span>
                <span className="night-score">
                  {ns.hits}/{ns.n}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {s && night && (
        <>
          {!live && <p className="replay-note">Rejoué — le modèle appliqué avant chaque match, sans les absents. Le suivi en temps réel commence le 15 nov.</p>}
          <div className="kpis">
            <div className="card kpi kpi-big">
              <span className="kpi-val">
                {s.hits}
                <small>/{s.n}</small>
              </span>
              <span className="kpi-label">Bons vainqueurs</span>
            </div>
            <div className="card kpi">
              <span className="kpi-val">{s.selN ? `${s.selHits}/${s.selN}` : "—"}</span>
              <span className="kpi-label">Sélection ≥ {Math.round(th * 100)} %</span>
            </div>
            <div className="card kpi">
              <span className={`kpi-val ${s.betN ? (s.profit >= 0 ? "pos" : "neg") : ""}`}>{s.betN ? signed(s.profit) : "—"}</span>
              <span className="kpi-label">Paris conseillés{s.betN ? ` (${s.betWon}/${s.betN})` : ""}</span>
            </div>
          </div>

          <div className="card tops">
            <span className="tops-title">Les plus sûrs du soir</span>
            {[2, 3].map((k) => {
              const t = topK(night[1], k);
              return (
                <div key={k} className={`tops-item${t && t.hits === k ? " is-perfect" : ""}`}>
                  <span className="tops-k">{k} matchs</span>
                  <span className="tops-val">{t ? `${t.hits}/${k}` : "—"}</span>
                </div>
              );
            })}
          </div>

          <div className="stack" style={{ marginTop: 12 }}>
            {[...night[1]]
              .sort((a, b) => Math.max(b.p_home, 1 - b.p_home) - Math.max(a.p_home, 1 - a.p_home))
              .map((e, i) => (
                <ResultCard key={e.id} e={e} nightPick={nightPickId === e.id} rank={i < 3 ? i + 1 : undefined} />
              ))}
          </div>
          <p className="note">Paris conseillés : pastille verte, 1 unité misée à la cote du bookmaker. Gain en unités.</p>
        </>
      )}
    </Page>
  );
}

function ResultCard({ e, nightPick, rank }: { e: JournalEntry; nightPick?: boolean; rank?: number }) {
  const hit = isHit(e);
  const bet = advisedBet(e);
  const pick = pickSide(e);
  return (
    <div className="card result">
      {rank && <span className="result-rank">{rank === 1 ? "Le plus sûr" : `${rank}e plus sûr`}</span>}
      <div className={`result-mark ${hit ? "ok" : "ko"}`}>{hit ? <Check size={14} strokeWidth={3} /> : <X size={14} strokeWidth={3} />}</div>
      <Row e={e} side="home" pick={pick} />
      <Row e={e} side="away" pick={pick} />
      <SpreadCompare e={e} />
      {nightPick && (() => {
        const np = nightPickFor(e.p_home, e.odds![0], e.odds![1])!;
        const won = (np.side === "home") === (e.home_win === 1);
        const a = np.side === "home" ? e.home : e.away;
        return (
          <div className={`result-bet nightpick-res ${won ? "won" : "lost"}`}>
            <span>
              <Sparkles size={13} /> Désaccord bookmakers · <TeamLogo abbr={a} size={16} /> {team(a).name} à {odds(np.odds)}
            </span>
            <b>{signed(won ? np.odds - 1 : -1)}</b>
          </div>
        );
      })()}
      {(() => {
        const hb = handicapBet(e);
        if (!hb || !hb.result) return null;
        return (
          <div className={`result-bet hcap-res ${hb.result === "gagné" ? "won" : "lost"}`}>
            <span>
              Handicap · <TeamLogo abbr={e.home} size={16} /> {team(e.home).name} {hb.line > 0 ? "+" : hb.line < 0 ? "−" : ""}
              {Math.abs(hb.line).toFixed(1).replace(".", ",")} · {hb.result}
            </span>
            <b>{signed(hb.profit ?? 0)}</b>
          </div>
        );
      })()}
      {bet && (
        <div className={`result-bet ${bet.won ? "won" : "lost"}`}>
          <span>
            Pari conseillé · <TeamLogo abbr={bet.side === "home" ? e.home : e.away} size={16} />{" "}
            {team(bet.side === "home" ? e.home : e.away).name} à {odds(bet.odds)}
          </span>
          <b>{signed(bet.profit ?? 0)}</b>
        </div>
      )}
    </div>
  );
}

function Row({ e, side, pick }: { e: JournalEntry; side: Side; pick: Side }) {
  const abbr = side === "home" ? e.home : e.away;
  const pts = e.score ? (side === "home" ? e.score[0] : e.score[1]) : null;
  const won = e.home_win != null && (side === "home") === (e.home_win === 1);
  const p = side === "home" ? e.p_home : 1 - e.p_home;
  return (
    <div className={`result-row${won ? " is-winner" : ""}`}>
      <TeamLogo abbr={abbr} size={30} dim={!won} />
      <span className="team-name">
        {team(abbr).name}
        {side === "home" && <House size={13} className="home-icon" aria-label="à domicile" />}
      </span>
      {pick === side && <span className="result-pick">Prono {pct(p)} %</span>}
      <span className="result-pts">{pts ?? "—"}</span>
    </div>
  );
}

/** Écart prévu par l'algorithme avant le match, face à l'écart réel. */
function SpreadCompare({ e }: { e: JournalEntry }) {
  if (e.spread == null || !e.score) return null;
  const fmt = (x: number) => Math.abs(x).toFixed(1).replace(".", ",").replace(",0", "");
  const who = (m: number) => team(m >= 0 ? e.home : e.away).name;
  const real = e.score[0] - e.score[1];
  const err = Math.abs(real - e.spread);
  return (
    <div className="result-spread">
      <span>
        Prévu : <b>{who(e.spread)} par {fmt(e.spread)}</b>
      </span>
      <span>
        Réel : <b>{who(real)} par {fmt(real)}</b>
      </span>
      <span className={`result-spread-err ${err <= 5 ? "good" : err >= 15 ? "bad" : ""}`}>
        {err < 0.5 ? "pile" : `écart de ${fmt(err)} pt${err >= 2 ? "s" : ""}`}
      </span>
    </div>
  );
}
