import { CircleCheck } from "lucide-react";
import { useMemo } from "react";
import { Empty, Loading, Page } from "../components/Page";
import { useRecord } from "../data";
import { odds, pct, pct1, signed } from "../format";
import { comboHistory, nightPicksHistory, readThreshold, summary, topKHistory, type ComboKind } from "../results";
import type { Backtest, CalibrationBin, JournalEntry } from "../types";

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

  const s = useMemo(() => {
    if (!data) return null;
    const liveDone = data.journal.filter((e) => e.home_win != null && e.live !== false);
    const live = liveDone.length > 0;
    const done = live ? liveDone : data.journal.filter((e) => e.home_win != null);
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
    const bets = summary(done, th);
    return {
      live,
      bets,
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

  const bt = data?.backtest;
  const nightPicks = useMemo(() => {
    if (!data) return [];
    const liveDone = data.journal.some((e) => e.live !== false && e.home_win != null);
    const pool = data.journal.filter((e) => (liveDone ? e.live !== false : true));
    return nightPicksHistory(pool).filter((x) => x.won != null);
  }, [data]);
  const np = {
    n: nightPicks.length,
    won: nightPicks.filter((x) => x.won).length,
    profit: nightPicks.reduce((a, x) => a + (x.profit ?? 0), 0),
  };
  return (
    <Page title="Bilan" sub={s ? (s.live ? `${s.n} prévisions en temps réel` : s.n ? `Saison en cours rejouée · ${s.n} matchs` : "Avant le premier résultat") : " "}>
      {error && <Empty icon={<CircleCheck />} title="Données indisponibles" />}
      {!data && !error && <Loading />}
      {s && (
        <>
          {s.n > 0 ? (
            <div className="kpis">
              <Kpi value={s.acc} label={s.live ? "Bons vainqueurs" : "Bons vainqueurs (rejoué)"} big />
              <Kpi value={s.week} label="7 derniers jours" />
              <Kpi value={s.sel.acc} label={`Sélection ≥ ${Math.round(s.sel.th * 100)} %`} />
            </div>
          ) : (
            bt && (
              <div className="kpis">
                <Kpi value={bt.accuracy} label="Bons vainqueurs (backtest)" big />
                <Kpi value={selAcc(bt, 70)} label="Sélection ≥ 70 %" />
                <Kpi value={selAcc(bt, 75)} label="Sélection ≥ 75 %" />
              </div>
            )
          )}

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

          {(() => {
            const pool = data!.journal.filter((e) => e.home_win != null && (s.live ? e.live !== false : true));
            const rows = [2, 3].map((k) => ({ k, ...topKHistory(pool, k) })).filter((x) => x.nights > 0);
            if (!rows.length) return null;
            return (
              <>
                <h2 className="section">Les plus sûrs du soir</h2>
                <div className="card list">
                  {rows.map((x) => (
                    <div key={x.k} className="tops-row">
                      <span className="tops-k">{x.k} plus sûrs</span>
                      <span className="tops-big">
                        {x.allRight}/{x.nights}
                        <small> soirs tous justes</small>
                      </span>
                      <span className="tops-rate">{pct(x.hitRate)} %</span>
                    </div>
                  ))}
                </div>
                <p className="note">{s.live ? "En temps réel" : "Saison rejouée"} · à droite : réussite de ces pronos pris un par un.</p>
              </>
            );
          })()}

          {(() => {
            const pool = data!.journal.filter((e) => e.live !== false);
            const th = readThreshold();
            const rows = (
              [
                ["all", "Tous les matchs"],
                ["top3", "3 plus sûrs"],
                ["top2", "2 plus sûrs"],
                ["selection", `Sélection ≥ ${Math.round(th * 100)} %`],
              ] as [ComboKind, string][]
            ).map(([k, label]) => ({ k, label, ...comboHistory(pool, k, th) }));
            if (!rows.some((r) => r.n > 0)) return null;
            return (
              <>
                <h2 className="section">Combinés du soir</h2>
                <div className="card list">
                  <div className="combo-row combo-head">
                    <span />
                    <span>Passés</span>
                    <span>Résultat</span>
                  </div>
                  {rows.map((r) => (
                    <div key={r.k} className="combo-row">
                      <span className="combo-label">
                        {r.label}
                        {r.best > 0 && <small>meilleure cote gagnée {odds(r.best)}</small>}
                      </span>
                      <span className="combo-val">{r.n ? `${r.won}/${r.n}` : "—"}</span>
                      <span className={`combo-val ${r.n ? (r.profit >= 0 ? "pos" : "neg") : ""}`}>
                        {r.n ? `${signed(r.profit)} u` : "—"}
                      </span>
                    </div>
                  ))}
                </div>
                <p className="note">
                  En temps réel, depuis le 15 nov. · 1 unité par soir, aux meilleures cotes relevées (bookmakers français en
                  priorité). Un combiné ne compte que si toutes ses cotes sont connues.
                </p>
              </>
            );
          })()}

          {nightPicks.length > 0 && (
            <>
              <h2 className="section">Pari du soir</h2>
              <div className="card bets-card">
                <div>
                  <span className={`bets-val ${np.profit >= 0 ? "pos" : "neg"}`}>{signed(np.profit)}</span>
                  <span className="kpi-label">unités</span>
                </div>
                <div>
                  <span className="bets-val">
                    {np.won}/{np.n}
                  </span>
                  <span className="kpi-label">gagnés</span>
                </div>
                <div>
                  <span className="bets-val">{np.n ? `${signed((np.profit / np.n) * 100)} %` : "—"}</span>
                  <span className="kpi-label">rendement</span>
                </div>
              </div>
              <p className="note">{s.live ? "En temps réel" : "Saison rejouée"} · 1 unité par soir, à la meilleure cote relevée.</p>
            </>
          )}

          {s.bets.betN > 0 && (
            <>
              <h2 className="section">Paris conseillés</h2>
              <div className="card bets-card">
                <div>
                  <span className={`bets-val ${s.bets.profit >= 0 ? "pos" : "neg"}`}>{signed(s.bets.profit)}</span>
                  <span className="kpi-label">unités</span>
                </div>
                <div>
                  <span className="bets-val">
                    {s.bets.betWon}/{s.bets.betN}
                  </span>
                  <span className="kpi-label">gagnés</span>
                </div>
                <div>
                  <span className="bets-val">{signed((s.bets.profit / s.bets.betN) * 100)} %</span>
                  <span className="kpi-label">rendement</span>
                </div>
              </div>
              <p className="note">Pastilles vertes uniquement, 1 unité par pari à la cote du bookmaker.</p>
            </>
          )}

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
                {bt.roster && <Versus label="+ effectif du soir" value={bt.roster.accuracy} ll={bt.roster.logloss} strong />}
                <Versus label="Modèle" value={bt.accuracy} ll={bt.logloss} strong={!bt.roster} />
                {bt.books && <Versus label="Bookmakers" value={bt.books.book_accuracy} ll={bt.books.book_logloss} />}
                {bt.baselines.better_record != null && <Versus label="Meilleur bilan" value={bt.baselines.better_record} />}
                {bt.baselines.home_always != null && <Versus label="Toujours domicile" value={bt.baselines.home_always} />}
              </div>
              {bt.source && <p className="note">{bt.source}</p>}
            </>
          )}

          {!s.live && <p className="note">Le suivi en temps réel démarre avec les matchs du 15 novembre ; en attendant, ces chiffres viennent de la saison rejouée.</p>}
        </>
      )}
    </Page>
  );
}

function selAcc(bt: Backtest, th: number): number {
  const v = bt.selection[`conf${th}`];
  return typeof v === "object" && v?.accuracy != null ? v.accuracy : NaN;
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
