"""Ligne de commande.

    python -m pronos init        # historique : 4 saisons (une fois)
    python -m pronos matin       # résultats de la nuit + calendrier (chaque matin)
    python -m pronos soir        # blessures + cotes + prévisions + journal + export (avant les matchs)
    python -m pronos backtest    # rejoue les saisons passées, règle les paramètres
    python -m pronos export      # régénère les fichiers de l'app
    python -m pronos demo        # ligue simulée pour essayer l'app
    python -m pronos video       # vidéo du prono le plus sûr du soir (captures + voix off)
    python -m pronos serve       # sert l'app sur le réseau local (téléphone sur le même Wi-Fi)
"""
from __future__ import annotations

import argparse
import json
import socket
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import backtest as BT
from . import collect as C
from . import espn as E
from . import injuries as INJ
from .db import ROOT, connect
from .service import (BACKTEST_FILE, PARAMS_FILE, export, journal, load_journal_csv, load_params,
                      save_journal_csv, tonight)


def _tip_soon(con, hours: float = 2.5) -> bool:
    """Vrai si un match commence dans les prochaines heures : dernière lecture juste avant les matchs."""
    now = datetime.now(timezone.utc)
    for (tip,) in con.execute("SELECT heure_utc FROM matchs WHERE score_dom IS NULL AND heure_utc IS NOT NULL"):
        try:
            t = datetime.fromisoformat(str(tip).replace("Z", "+00:00"))
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if 0 <= (t - now).total_seconds() / 3600 <= hours:
            return True
    return False


def french_odds(con) -> None:
    """Cotes françaises (vainqueur + handicap) via The Odds API.

    Au plus une lecture toutes les 3 h, plus une juste avant les premiers matchs du soir :
    ~5 appels de 2 crédits par jour, ~300 crédits par mois sur les 500 gratuits. Sous 40 crédits restants, on ne prend plus que le vainqueur (1 crédit).
    """
    last = con.execute("SELECT MAX(releve) FROM cotes WHERE bookmaker LIKE '%(FR)'").fetchone()[0]
    age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600 if last else 99
    if age_h < 2.9 and not (age_h >= 0.9 and _tip_soon(con)):
        print(f"Cotes françaises : relevées il y a {age_h:.1f} h, pas de nouvelle requête")
        return
    low = con.execute("SELECT valeur FROM meta WHERE cle='odds_restant'").fetchone()
    try:
        odds = C.fetch_odds(spreads=not (low and int(low[0]) < 40))
    except Exception as e:  # les cotes ne doivent pas bloquer les prévisions
        print(f"Cotes françaises : erreur {e.__class__.__name__}")
        return
    rem = next((o["remaining"] for o in odds if o.get("remaining") is not None), None)
    if rem is not None:
        con.execute("INSERT OR REPLACE INTO meta VALUES ('odds_restant', ?)", (str(rem),))
    if odds:
        n, nl = C.store_odds(con, odds)
        from collections import Counter
        books = Counter(o["bookmaker"] for o in odds if o.get("line"))
        detail = ", ".join(f"{b} {k}" for b, k in books.most_common()) or "aucun"
        print(f"Cotes The Odds API : {n} cotes vainqueur, {nl} handicaps français ({detail})")
    con.commit()


def _seasons_back(n: int) -> list[str]:
    cur = C.season_of(date.today())
    y = int(cur[:4])
    return [f"{yy}-{(yy + 1) % 100:02d}" for yy in range(y - n, y + 1)]


def cmd_init(args) -> None:
    """Historique via ESPN : calendrier, scores, box scores (équipes et joueurs)."""
    con = connect()
    today = date.today()
    cur = int(C.season_of(today)[:4])
    for y in range(cur - args.saisons, cur + 1):
        games = E.sync_dates(con, E.season_days(y, today))
        done = sum(g["done"] for g in games)
        print(f"{E.season_label(y)} : {done} matchs joués, {len(games) - done} à venir", flush=True)
    print(f"Box scores : {E.sync_boxscores(con)} matchs")
    print("Vérification : 1 230 matchs attendus par saison régulière complète.")


def cmd_matin(args) -> None:
    """Résultats des derniers jours, calendrier à 10 jours, box scores."""
    con = connect()
    today = date.today()
    E.sync_dates(con, [today + timedelta(days=k) for k in range(-3, 11)])
    print(f"Box scores : {E.sync_boxscores(con, progress=False)} nouveaux matchs")
    export(con)


def cmd_soir(args) -> None:
    """Rapport des blessures, cotes du jour, prévisions, journal, export."""
    con = connect()
    today = date.today()
    E.sync_dates(con, [today - timedelta(days=1), today])
    E.sync_boxscores(con, progress=False)
    url, rows = INJ.fetch_latest()
    if url:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(f"Blessures : {INJ.store(con, f'{stamp} {url}', rows)} lignes ({url.rsplit('/', 1)[-1]})")
    else:
        print("Blessures : aucun rapport trouvé")
    try:
        print(f"Effectifs : {E.store_rosters(con, E.fetch_rosters())} joueurs")
    except Exception as e:
        print(f"Effectifs : erreur {e.__class__.__name__}, ancien effectif conservé")
    french_odds(con)
    _, games = tonight(con)
    print(f"Journal : {journal(con, games, load_params().version)} prévisions enregistrées")
    save_journal_csv(con)
    export(con)
    for g in games:
        fav = g["home"] if g["p_home"] >= .5 else g["away"]
        print(f"  {g['away']} @ {g['home']}  →  {fav} {max(g['p_home'], 1 - g['p_home']):.0%}")


def player_props(con, day: str, games: list[dict]) -> None:
    """Paris joueurs du soir (props.json) et suivi des résultats ; ne bloque jamais le reste."""
    from . import playerprops as PP
    from .service import write_payloads
    try:
        PP.load_csv(con)
        print(f"Paris joueurs : {PP.settle(con)} résultats notés")
        spreads = {(g["home"], g["away"]): g.get("spread") for g in games}
        payload = PP.tonight_picks(con, day, INJ.latest_for(con, day), spreads) if games else {"date": day}
        tips = {g["id"]: g.get("tip_utc") or "" for g in games}
        print(f"Paris joueurs : {len(payload.get('signals', []))} signaux, {len(payload.get('fallback', []))} à défaut, "
              f"{PP.journal(con, payload, tips)} enregistrés")
        payload["history"] = PP.history(con)
        write_payloads({"props.json": payload})
        PP.save_csv(con)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Paris joueurs : erreur {e.__class__.__name__}")


def cmd_auto(args) -> None:
    """Tâche planifiée (GitHub Actions) : tout en une fois, base reconstruite si besoin."""
    con = connect()
    print(f"Journal repris : {load_journal_csv(con)} prévisions")
    if con.execute("SELECT COUNT(*) FROM matchs WHERE statut='termine'").fetchone()[0] < 3000:
        args.saisons = 4
        cmd_init(args)
    today = date.today()
    E.sync_dates(con, [today + timedelta(days=k) for k in range(-3, 11)])
    print(f"Box scores : {E.sync_boxscores(con, progress=False)} nouveaux matchs")
    try:
        url, rows = INJ.fetch_latest()
    except Exception as e:  # le rapport ne doit pas bloquer les prévisions
        url, rows = None, []
        print(f"Blessures : erreur {e.__class__.__name__}")
    if url:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(f"Blessures : {INJ.store(con, f'{stamp} {url}', rows)} lignes ({url.rsplit('/', 1)[-1]})")
    try:
        print(f"Effectifs : {E.store_rosters(con, E.fetch_rosters())} joueurs")
    except Exception as e:
        print(f"Effectifs : erreur {e.__class__.__name__}, ancien effectif conservé")
    french_odds(con)
    day_ts, games = tonight(con)
    print(f"Journal : {journal(con, games, load_params().version)} prévisions enregistrées")
    save_journal_csv(con)
    export(con)
    player_props(con, day_ts.date().isoformat(), games)
    for g in games:
        fav = g["home"] if g["p_home"] >= .5 else g["away"]
        print(f"  {g['away']} @ {g['home']}  →  {fav} {max(g['p_home'], 1 - g['p_home']):.0%}")


def cmd_backtest(args) -> None:
    con = connect()
    games = C.load_games(con)
    games = games[games["home_pts"].notna()]
    seasons = sorted(games["season"].unique())
    if len(seasons) < 4:
        raise SystemExit("Il faut au moins 4 saisons (python -m pronos init).")
    train, valid, test = seasons[:-3], seasons[-3], seasons[-2:]
    print(f"Réglage sur {train}, vérification sur {valid}, test final sur {test}", flush=True)
    best, _ = BT.tune(games, train, valid)
    bt = BT.replay(games, best)
    v = BT.metrics(bt[bt["season"] == valid])
    t = bt[bt["season"].isin(test)]
    mt = BT.metrics(t)
    print(f"Retenu : demi-vie {best.half_life_days} j, a priori {best.prior_weight} matchs, σ {best.sigma}")
    print(f"Vérification : {v['accuracy']:.1%}  log loss {v['logloss']:.3f}")
    print(f"Test final   : {mt['accuracy']:.1%}  log loss {mt['logloss']:.3f}  ({mt['n']} matchs)")
    books = BT.versus_books(t, con)
    if books:
        print(f"Bookmakers ({books['n']} matchs) : modèle {books['model_accuracy']:.1%} / {books['model_logloss']:.3f}"
              f"  —  bookmakers {books['book_accuracy']:.1%} / {books['book_logloss']:.3f}")
    PARAMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PARAMS_FILE.write_text(json.dumps(asdict(best), indent=2))
    keep = json.loads(BACKTEST_FILE.read_text()).get("roster") if BACKTEST_FILE.exists() else None
    BACKTEST_FILE.write_text(json.dumps({"roster": keep,
        "source": f"Backtest sur données réelles — {', '.join(test)} ({mt['n']} matchs jamais vus)",
        "seasons": test, **mt, "baselines": BT.baselines(games, test),
        "selection": BT.selection(t), "books": books}))
    export(con)


def cmd_export(args) -> None:
    for p in export(connect()):
        print(p)


def cmd_demo(args) -> None:
    from .demo import build
    build()
    print("Données de démonstration écrites dans app/public/data/")


def cmd_video(args) -> None:
    from .video import make
    make(args.match, args.voix, once=args.une_fois)


def cmd_serve(args) -> None:
    dist = ROOT / "app" / "dist"
    if not dist.exists():
        raise SystemExit("Construis d'abord l'app : cd app && npm install && npm run build")
    from .service import copy_data_to_dist
    copy_data_to_dist()
    ip = socket.gethostbyname(socket.gethostname())
    print(f"Sur ton téléphone (même Wi-Fi) : http://{ip}:{args.port}")
    ThreadingHTTPServer(("0.0.0.0", args.port), partial(SimpleHTTPRequestHandler, directory=str(dist))).serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(prog="pronos", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--saisons", type=int, default=4); p.set_defaults(f=cmd_init)
    sub.add_parser("matin").set_defaults(f=cmd_matin)
    sub.add_parser("soir").set_defaults(f=cmd_soir)
    sub.add_parser("auto").set_defaults(f=cmd_auto)
    sub.add_parser("backtest").set_defaults(f=cmd_backtest)
    sub.add_parser("export").set_defaults(f=cmd_export)
    sub.add_parser("demo").set_defaults(f=cmd_demo)
    p = sub.add_parser("video", help="vidéo du prono le plus sûr du soir")
    p.add_argument("--match", default=None); p.add_argument("--voix", default="edge", choices=["edge", "espeak", "aucune"])
    p.add_argument("--une-fois", action="store_true", help="ne rien faire si la vidéo du soir existe déjà ou si les matchs ont commencé")
    p.set_defaults(f=cmd_video)
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=8501); p.set_defaults(f=cmd_serve)
    args = ap.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
