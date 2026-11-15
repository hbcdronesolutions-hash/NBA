"""Ligne de commande.

    python -m pronos init        # historique : 4 saisons (une fois)
    python -m pronos matin       # résultats de la nuit + calendrier (chaque matin)
    python -m pronos soir        # blessures + cotes + prévisions + journal + export (avant les matchs)
    python -m pronos backtest    # rejoue les saisons passées, règle les paramètres
    python -m pronos export      # régénère les fichiers de l'app
    python -m pronos demo        # ligue simulée pour essayer l'app
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
from .service import BACKTEST_FILE, PARAMS_FILE, export, journal, load_params, tonight


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
    odds = C.fetch_odds()
    if odds:
        print(f"Cotes The Odds API : {C.store_odds(con, odds)} matchs")
    _, games = tonight(con)
    print(f"Journal : {journal(con, games, load_params().version)} nouvelles prévisions")
    export(con)
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
    BACKTEST_FILE.write_text(json.dumps({
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
    sub.add_parser("backtest").set_defaults(f=cmd_backtest)
    sub.add_parser("export").set_defaults(f=cmd_export)
    sub.add_parser("demo").set_defaults(f=cmd_demo)
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=8501); p.set_defaults(f=cmd_serve)
    args = ap.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
