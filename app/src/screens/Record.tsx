import { Check, CircleCheck, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Empty, Loading, Page } from "../components/Page";
import { TeamLogo } from "../components/TeamLogo";
import { useRecord } from "../data";
import { pct, pct1, shortDate } from "../format";
import type { CalibrationBin, JournalEntry } from "../types";

const BINS = [0.5, 0.6, 0.7, 0.8, 0.9];

const conf = (e: JournalEntry) => Math.max(e.p_home, 1 - e.p_home);
const isHit = (e: JournalEntry) => (e.p_home >= 0.5 ? 1 : 0) === e.home_win;
const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : NaN);
const logloss = (p: number, y: number) => -(y * Math.log(p) + (1 - y) * Math.log(1 - p));

function threshold() {
  try {
    const v = Number(localStorage.getItem("seuil"));
    return v >= 60 && v <= 80 ? v / 100 : 0.7;
  } catch {
    return 0.7;
  }
}

export function Record() {
  const { data, error } = useRecord();
  const [showAll, setShowAll] = useState(false);

  const s = useMemo(() => {
    if (!data) return null;
    const done = data.journal.filter((e) => e.home_win != null);
    const last = done.reduce((m, e) => (e.date > m ? e.date : m), "");
    const cutoff = last ? new Date(new Date(last + "T12:00:00Z").getTime() - 6 * 864e5).toISOString().slice(0, 10) : "";
    const week = done.filter((e) => e.date >= cutoff);
    const calib: CalibrationBin[] = BINS.map((lo) => {
      const xs = done.filter((e) => conf(e) >= lo && conf(e) < lo + 0.1 + (lo === 0.9 ? 0.01 : 0));
      return { bin: `${lo * 100}`, lo, n: xs.length, confidence: mean(xs.map(conf)), hit: mean(xs.map((e) => +isHit(e))) };
    }).filter((b) => b.n > 0);
    const withOdds = done.filter((e) => e.odds);
    const bookP = (e: JournalEntry) => {
      const [h, a] = e.odds!;
      return 1 / h / (1 / h + 1 / a);
    };
    const th = threshold();
    const sel = done.filter((e) => conf(e) >= th);
    const nights = new Set(done.map((e) => e.date)).size;
    return {
      n: done.length,
      acc: mean(done.map((e) => +isHit(e))),
      week: mean(week.map((e) => +isHit(e))),
      weekN: week.length,
      calib,
      books: withOdds.length
        ? {
            n: withOdds.length,
            model: mean(withOdds.map((e) => +isHit(e))),
            book: mean(withOdds.map((e) => +((bookP(e) >= 0.5 ? 1 : 0) === e.home_win))),
            modelLL: mean(withOdds.map((e) => logloss(e.p_home, e.home_win!))),
            bookLL: mean(withOdds.map((e) => logloss(bookP(e), e.home_win!))),
          }
        : null,
      sel: { th, acc: mean(sel.map((e) => +isHit(e))), perNight: nights ? sel.length / nights : 0 },
    };
  }, [data]);

  const byDate = useMemo(() => {
    const m = new Map<string, JournalEntry[]>();
    for (const e of data?.journal ?? []) m.set(e.date, [...(m.get(e.date) ?? []), e]);
    return [...m.entries()];
  }, [data]);

  const bt = data?.backtest;
  return (
    <Page title="Bilan" sub={s ? `${s.n} prévisions vérifiées` : " "}>
      {error && <Empty icon={<CircleCheck />} title="Données indisponibles" />}
      {!data && !error && <Loading />}
      {s && (
        <>
          <div className="kpis">
            <Kpi value={s.acc} label="Bons vainqueurs" big />
            <Kpi value={s.week} label="7 derniers jours" />
            <Kpi value={s.sel.acc} label={`Sélection ≥ ${Math.round(s.sel.th * 100)} %`} />
          </div>

          <h2 className="section">Justesse des probabilités</h2>
          <div className="card chart-card">
            <Calibration journal={s.calib} backtest={bt?.calibration ?? []} />
            <p className="chart-legend">
              <span className="dot dot-fill" /> Saison
              {bt && (
                <>
                  <span className="dot dot-ring" /> Backtest
                </>
              )}
              <span className="dash" /> Idéal
            </p>
          </div>

          {s.books && (
            <>
              <h2 className="section">Face aux bookmakers</h2>
              <div className="card list">
                <Versus label="Modèle" value={s.books.model} ll={s.books.modelLL} strong />
                <Versus label="Bookmakers" value={s.books.book} ll={s.books.bookLL} />
              </div>
            </>
          )}

          {bt && (
            <>
              <h2 className="section">Référence backtest</h2>
              <div className="card list">
                <Versus label="Modèle" value={bt.accuracy} ll={bt.logloss} strong />
                {bt.baselines.better_record != null && <Versus label="Meilleur bilan" value={bt.baselines.better_record} />}
                {bt.baselines.home_always != null && <Versus label="Toujours domicile" value={bt.baselines.home_always} />}
              </div>
              {bt.source && <p className="note">{bt.source}</p>}
            </>
          )}

          <h2 className="section">Journal</h2>
          <div className="stack">
            {(showAll ? byDate : byDate.slice(0, 4)).map(([date, entries]) => (
              <div key={date} className="card list">
                <div className="journal-date">{shortDate(date)}</div>
                {entries.map((e) => (
                  <JournalRow key={e.id} e={e} />
                ))}
              </div>
            ))}
          </div>
          {byDate.length > 4 && !showAll && (
            <button className="more" onClick={() => setShowAll(true)}>
              Tout l'historique
            </button>
          )}
        </>
      )}
    </Page>
  );
}

function Kpi({ value, label, big }: { value: number; label: string; big?: boolean }) {
  return (
    <div className={`card kpi${big ? " kpi-big" : ""}`}>
      <span className="kpi-val">
        {Number.isFinite(value) ? pct(value) : "—"}
        <small>%</small>
      </span>
      <span className="kpi-label">{label}</span>
    </div>
  );
}

function Versus({ label, value, ll, strong }: { label: string; value: number; ll?: number; strong?: boolean }) {
  return (
    <div className={`versus${strong ? " is-strong" : ""}`}>
      <span className="versus-label">{label}</span>
      <span className="versus-bar">
        <span style={{ width: `${Math.max(0, (value - 0.4) / 0.4) * 100}%` }} />
      </span>
      <span className="versus-val">{pct1(value)} %</span>
      {ll != null && <span className="versus-ll" title="Log loss (plus bas = mieux)">{ll.toFixed(3)}</span>}
    </div>
  );
}

function JournalRow({ e }: { e: JournalEntry }) {
  const homePick = e.p_home >= 0.5;
  const p = conf(e);
  return (
    <div className="journal-row">
      <TeamLogo abbr={e.away} size={24} dim={homePick} />
      <span className="journal-at">@</span>
      <TeamLogo abbr={e.home} size={24} dim={!homePick} />
      <span className="journal-score">{e.score ? `${e.score[1]}–${e.score[0]}` : ""}</span>
      <span className="journal-p">{pct(p)} %</span>
      <span className={`journal-res ${e.home_win == null ? "" : isHit(e) ? "ok" : "ko"}`}>
        {e.home_win == null ? "·" : isHit(e) ? <Check size={14} strokeWidth={3} /> : <X size={14} strokeWidth={3} />}
      </span>
    </div>
  );
}

function Calibration({ journal, backtest }: { journal: CalibrationBin[]; backtest: CalibrationBin[] }) {
  const W = 300;
  const H = 200;
  const pad = { l: 34, r: 10, t: 10, b: 26 };
  const x = (v: number) => pad.l + ((v - 0.5) / 0.5) * (W - pad.l - pad.r);
  const y = (v: number) => H - pad.b - ((v - 0.4) / 0.6) * (H - pad.t - pad.b);
  const maxN = Math.max(1, ...journal.map((b) => b.n), ...backtest.map((b) => b.n));
  const r = (n: number) => 3 + 6 * Math.sqrt(n / maxN);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="calib" role="img" aria-label="Calibration">
      {[0.5, 0.6, 0.7, 0.8, 0.9, 1].map((v) => (
        <g key={v}>
          <line x1={x(v)} x2={x(v)} y1={pad.t} y2={H - pad.b} className="grid" />
          <text x={x(v)} y={H - 8} className="tick" textAnchor="middle">
            {v * 100}
          </text>
        </g>
      ))}
      {[0.4, 0.6, 0.8, 1].map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} className="grid" />
          <text x={pad.l - 8} y={y(v) + 4} className="tick" textAnchor="end">
            {v * 100}
          </text>
        </g>
      ))}
      <line x1={x(0.5)} y1={y(0.5)} x2={x(1)} y2={y(1)} className="ideal" />
      {backtest.map((b) => (
        <circle key={"b" + b.bin} cx={x(b.confidence)} cy={y(b.hit)} r={r(b.n)} className="pt-ring" />
      ))}
      {journal.map((b) => (
        <circle key={"j" + b.bin} cx={x(b.confidence)} cy={y(b.hit)} r={r(b.n)} className="pt-fill" />
      ))}
    </svg>
  );
}
