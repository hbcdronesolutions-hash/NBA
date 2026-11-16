"""Vidéo du prono du soir : captures de l'app + montage dynamique + voix off.

    python -m pronos video                 # match le plus fiable du soir, voix edge-tts
    python -m pronos video --voix espeak   # voix de secours (hors ligne)
    python -m pronos video --match espn-401909989

Sortie : data/videos/prono_<date>_<équipes>.mp4 (format vertical 1080×1920, réseaux sociaux)
et le texte de la voix off à côté (.txt).
Prérequis : app construite (cd app && npm run build), ffmpeg, Playwright (pip install playwright
&& playwright install chromium), edge-tts (pip install edge-tts) pour la voix neuronale.
"""
from __future__ import annotations

import asyncio
import functools
import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .db import ROOT
from .teams import TEAMS

W, H, FPS = 1080, 1920, 30
BG = (245, 245, 242)
INK = (17, 17, 19)
MUTED = (120, 120, 126)
VOICE = os.environ.get("PRONOS_VOIX", "fr-FR-RemyMultilingualNeural")
FONT_DIRS = ["/usr/share/fonts/opentype/inter", "/usr/share/fonts/truetype/inter", "C:/Windows/Fonts", "/Library/Fonts"]
FADE = 0.35

RESPONSABLE = ("Jouer comporte des risques : endettement, isolement, dépendance. "
               "Pour être aidé, appelez le 09 74 75 13 13, appel non surtaxé.")


# ---------------------------------------------------------------- utilitaires

def nick(abbr: str) -> str:
    return TEAMS[abbr].name


def fr(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def font(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    for d in FONT_DIRS:
        for name in (f"Inter-{weight}.otf", f"Inter-{weight}.ttf", "Inter-Bold.otf", "arialbd.ttf", "Arial Bold.ttf"):
            p = Path(d) / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def duration(path: Path) -> float:
    return float(run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]))


# ------------------------------------------------------------ choix du match

def pick_game(today: dict, match_id: str | None) -> dict:
    games = today["games"]
    if match_id:
        return next(g for g in games if g["id"] == match_id)
    now = datetime.now(ZoneInfo("UTC"))
    upcoming = [g for g in games if not g.get("result") and
                (not g.get("tip_utc") or datetime.fromisoformat(g["tip_utc"]) > now)] or games
    return max(upcoming, key=lambda g: max(g["p_home"], 1 - g["p_home"]))


# ------------------------------------------------------------------ scénario

@dataclass
class Scene:
    key: str
    title: str          # bandeau en haut de l'écran
    text: str           # voix off (et sous-titres)
    image: Path | None = None
    meta: dict | None = None


def _pts(x: float) -> str:
    x = abs(x)
    return fr(x) + (" points" if x >= 2 else " point")


def _int(x: float) -> str:
    return str(round(x))


def _pct(x: float) -> str:
    return f"{round(x * 100)} %"


OFFERTS = ROOT / "data" / "offerts.csv"


def load_offers() -> dict[str, str]:
    """Match offert en vidéo chaque soir : {date: id du match}."""
    if not OFFERTS.exists():
        return {}
    rows = [l.split(",") for l in OFFERTS.read_text().splitlines()[1:] if "," in l]
    return {d: m for d, m in rows}


def save_offer(date: str, match_id: str) -> None:
    offers = load_offers()
    offers[date] = match_id
    OFFERTS.parent.mkdir(parents=True, exist_ok=True)
    OFFERTS.write_text("date,match_id\n" + "".join(f"{d},{m}\n" for d, m in sorted(offers.items())))


def yesterday_review(record: dict, today: str) -> dict | None:
    """Bilan de la veille (temps réel) + la meilleure « stat positive » disponible."""
    live = [e for e in record.get("journal", []) if e.get("live") is not False and e.get("home_win") is not None
            and e["date"] < today]
    if not live:
        return None
    last = max(e["date"] for e in live)
    night = sorted([e for e in live if e["date"] == last], key=lambda e: -max(e["p_home"], 1 - e["p_home"]))
    hit = lambda e: (e["p_home"] >= 0.5) == (e["home_win"] == 1)
    pick = lambda e: e["home"] if e["p_home"] >= 0.5 else e["away"]
    n, h = len(night), sum(hit(e) for e in night)
    by_date: dict[str, list] = {}
    for e in live:
        by_date.setdefault(e["date"], []).append(e)
    dates = sorted(by_date)
    week = [e for d in dates[-7:] for e in by_date[d]]
    streak = 0
    for d in reversed(dates):
        top = max(by_date[d], key=lambda e: max(e["p_home"], 1 - e["p_home"]))
        if not hit(top):
            break
        streak += 1
    offered_id = load_offers().get(last)
    offered = next((e for e in night if e["id"] == offered_id), night[0])
    rev = {
        "date": last, "n": n, "hits": h, "rate": h / n, "night": night,
        "winners": [nick(pick(e)) for e in night if hit(e)],
        "offered": offered, "offered_ok": hit(offered),
        "top2_ok": n >= 2 and hit(night[0]) and hit(night[1]),
        "week_rate": sum(hit(e) for e in week) / len(week), "week_n": len(week), "week_nights": len(dates[-7:]),
        "streak": streak, "all_rate": sum(hit(e) for e in live) / len(live), "all_n": len(live),
    }
    return rev


def _positive_stat(rev: dict) -> str:
    if rev["top2_ok"]:
        return "les 2 pronos les plus sûrs sont quand même passés"
    if rev["offered_ok"]:
        return "le match qu'on t'avait analysé est bien passé"
    if rev["week_nights"] >= 3 and rev["week_rate"] >= 0.65:
        return f"sur les {rev['week_nights']} derniers soirs, notre algorithme reste à {_pct(rev['week_rate'])} de réussite"
    if rev["streak"] >= 2:
        return f"le prono le plus sûr est passé {rev['streak']} soirs d'affilée"
    return f"depuis le début du suivi, notre algorithme est à {_pct(rev['all_rate'])} de réussite"


def script(g: dict, today: dict, ratings: dict | None = None, record: dict | None = None) -> list[Scene]:
    """Voix off validée : bilan de la veille, analyse détaillée du match offert, cotes, fin sans lien."""
    home, away = g["home"], g["away"]
    fav = home if g["p_home"] >= 0.5 else away
    other = away if fav == home else home
    p = max(g["p_home"], 1 - g["p_home"])
    F, O = nick(fav), nick(other)
    spread = abs(g["spread"])
    rt = {t["abbr"]: t for t in (ratings or {}).get("teams", [])}
    fac = lambda k: [f for f in g["factors"] if f["key"] == k]
    sc: list[Scene] = []

    # 1-2. Bilan de la veille.
    rev = yesterday_review(record or {}, today["date"])
    if rev:
        score = f"{rev['hits']} sur {rev['n']}"
        if rev["rate"] >= 0.8:
            hook = (f"Hier soir, notre algorithme a trouvé le bon vainqueur sur {rev['n']} matchs NBA sur {rev['n']}."
                    + (" Aucune erreur." if rev["hits"] == rev["n"] else f" {rev['hits']} bons pronos."))
            if rev["hits"] < rev["n"]:
                hook = f"Hier soir, {score} : {rev['hits']} bons pronos sur {rev['n']} matchs NBA pour notre algorithme."
        elif rev["rate"] >= 0.6:
            hook = f"Hier soir, {score} pour notre algorithme… et {_positive_stat(rev)}."
        else:
            hook = (f"Soyons honnêtes : hier soir, soirée compliquée, seulement {score}. "
                    f"Mais {_positive_stat(rev)}.")
            if rev["week_nights"] >= 3 and "derniers soirs" not in _positive_stat(rev):
                hook += f" Et sur les {rev['week_nights']} derniers soirs, on reste à {_pct(rev['week_rate'])}."
        sc.append(Scene("intro", f"{rev['hits']}/{rev['n']} hier soir", hook, meta={"card": "intro", "rev": rev}))
        w = rev["winners"][:3]
        if rev["hits"] == rev["n"]:
            t = f"{', '.join(w)}… tous les favoris annoncés ont gagné. "
        elif w:
            t = f"{', '.join(w)} ont fait le travail. "
        else:
            t = ""
        o = rev["offered"]
        on, oo = nick(o["home"] if o["p_home"] >= 0.5 else o["away"]), nick(o["away"] if o["p_home"] >= 0.5 else o["home"])
        sh, sa = o["score"]
        sw, sl = max(sh, sa), min(sh, sa)
        if rev["offered_ok"]:
            t += f"Et le match qu'on t'avait analysé, {on} contre {oo} : victoire des {on}, {sw} à {sl}."
        else:
            t += (f"Le match qu'on t'avait analysé, {on} contre {oo}, n'est pas passé : {sw} à {sl}. "
                  "Ça arrive : aucun prono n'est sûr à 100 %.")
        sc.append(Scene("veille", "Hier soir", t, meta={"shot": "veille", "scroll": True}))
    else:
        sc.append(Scene("intro", "Prono NBA du soir", "Ce soir, notre algorithme a analysé tous les matchs NBA de la nuit.",
                        meta={"card": "intro"}))

    # 3. Le match du soir.
    absent_fav = [a for a in g.get("absent_detail", []) if a["team"] == fav and a["status"] in ("out", "doubtful")
                  and a["impact"] >= 1.0]
    twist = (f" Et pourtant, {absent_fav[0]['player']} est forfait. Voici pourquoi."
             if absent_fav else " Voici pourquoi.")
    venue = f"à domicile face aux {O}" if fav == home else f"en déplacement chez les {O}"
    sc.append(Scene("liste", "Ce soir",
                    f"Ce soir, notre algorithme a analysé les {len(today['games'])} matchs de la nuit. On t'en dévoile un : "
                    f"les {F}, {venue}.", meta={"shot": "liste"}))
    sc.append(Scene("match", f"{F} : {_pct(p)}",
                    f"Notre algorithme leur donne {_pct(p)} de chances de gagner.{twist}", meta={"shot": "match"}))

    # 4. Niveau réel des équipes.
    force = fac("force")
    sc.append(Scene("methode", "Le vrai niveau des équipes",
                    "Premier élément, le plus lourd : le vrai niveau des équipes. Pas le classement : on mesure les "
                    "points marqués et encaissés pour 100 possessions, corrigés selon la force de chaque adversaire, "
                    "et les matchs récents comptent plus que les anciens.",
                    meta={"shot": "forces"}))
    if fav in rt and other in rt:
        a_, b_ = rt[fav], rt[other]
        t = (f"Résultat : les {F} marquent {_int(a_['off'])} points et en encaissent {_int(a_['def'])} pour 100 possessions. "
             f"Les {O} en marquent {_int(b_['off'])}… et en encaissent {_int(b_['def'])}.")
        if b_["def"] >= (ratings or {}).get("league", {}).get("ortg", 111) + 4:
            t += " C'est l'une des défenses les plus perméables que mesure notre algorithme."
        elif a_["def"] <= (ratings or {}).get("league", {}).get("ortg", 111) - 4:
            t += f" La défense des {F} est l'une des plus solides que mesure notre algorithme."
        sc.append(Scene("niveau", "Pour 100 possessions", t, meta={"shot": "forces"}))
        # 5. Dynamique sur les derniers matchs.
        ta, tb = a_.get("trend") or [], b_.get("trend") or []
        if len(ta) >= 5 and len(tb) >= 5:
            def move(name, tr):
                d = tr[-1] - tr[0]
                verb = ("montent en puissance" if d > 3 else "progressent" if d > 1 else
                        "plongent" if d < -3 else "baissent" if d < -1 else "restent stables")
                sign = lambda x: ("plus " if x >= 0 else "moins ") + fr(abs(x))
                return f"les {name} {verb}, de {sign(tr[0])} à {sign(tr[-1])}"
            sc.append(Scene("tendance", "La dynamique",
                            f"Et la tendance, sur leurs {min(len(ta), 15)} derniers matchs : {move(F, ta)}, et {move(O, tb)}.",
                            meta={"shot": "forces"}))

    # 6. Rythme du match.
    if force:
        sc.append(Scene("rythme", "Le rythme du match",
                        f"Avec {_int(g['pace'])} possessions prévues ce soir, cet écart de niveau vaut à lui seul "
                        f"{_pts(force[0]['points'])} d'avance pour les {nick(home if force[0]['points'] >= 0 else away)}.",
                        meta={"shot": "f_" + force[0]["label"]}))

    # 7. Absents, joueur par joueur.
    ad = g.get("absent_detail", [])
    big = sorted([a for a in ad if a["status"] in ("out", "doubtful") and a["impact"] >= 0.8], key=lambda a: -a["impact"])
    free = [a for a in ad if a["status"] in ("out", "doubtful") and a["impact"] <= 0.1 and a["minutes"] >= 12]
    played = {a["player"].split(" ")[-1].lower() for a in ad}
    long_term = []
    for i in g.get("injury_report", []):
        last_name = i["player"].split(",")[0].replace(" III", "").replace(" Jr.", "").split(" ")[-1].lower()
        if i["status"].lower() == "out" and last_name not in played:
            long_term.append(i)
    if big or free:
        t = ("Les absents, maintenant. Pour chaque joueur, notre algorithme a mesuré sur 4 saisons ce que fait son "
             "équipe avec et sans lui sur le terrain, et combien de minutes il joue d'habitude.")
        sc.append(Scene("absents_methode", "Les absents", t, meta={"shot": "absents"}))
        parts = []
        for a in big[:2]:
            nm = a["player"].split(" ")[-1] if a["player"].count(" ") == 1 else a["player"]
            if not parts:
                parts.append(f"{a['player']} : avec lui sur le terrain, les {nick(a['team'])} font "
                             f"{('plus ' if a['value'] >= 0 else 'moins ')}{fr(abs(a['value']))} points pour 100 possessions. "
                             f"Il jouait {_int(a['minutes'])} minutes par match : son absence coûte {_pts(a['impact'])}.")
            else:
                parts.append(f"{'En face, ' if a['team'] != big[0]['team'] else ''}{a['player']} manque aussi : "
                             f"{_pts(a['impact'])}.")
        for a in free[:1]:
            parts.append(f"{a['player']} ? Absent, mais les {nick(a['team'])} faisaient moins bien avec lui : "
                         f"ça ne leur coûte rien.")
        if long_term:
            names = " et ".join(i["player"].split(", ")[0].replace(" III", "") for i in long_term[:2])
            parts.append(f"{names} ne jouent plus depuis un moment : c'est déjà compté dans le niveau.")
        eff = {f["team"]: f["points"] for f in fac("effectif")}
        net = sum(eff.values())
        if eff:
            who = home if net >= 0 else away
            parts.append("Bilan : les absences s'annulent presque." if abs(net) < 0.6 else
                         f"Bilan des absences : {_pts(net)} pour les {nick(who)}.")
        sc.append(Scene("absents", "Joueur par joueur", " ".join(parts), meta={"shot": "absents"}))

    # 8. Terrain, fatigue, voyage.
    ctx = []
    for f in fac("terrain"):
        ctx.append(f"les {nick(home)} reçoivent, ça vaut {_pts(f['points'])}")
    for f in fac("altitude"):
        ctx.append(f"l'altitude, difficile pour les visiteurs, ajoute {_pts(f['points'])}")
    for f in fac("veille"):
        ctx.append(f"les {nick(f['team'])} ont joué hier soir : moins {_pts(f['points'])}")
    for f in fac("3en4"):
        ctx.append(f"les {nick(f['team'])} jouent leur 3e match en 4 jours : moins {_pts(f['points'])}")
    for f in fac("voyage"):
        if abs(f["points"]) >= 0.3:
            ctx.append(f"le voyage pèse {_pts(f['points'])} : {f['detail'].split(': ', 1)[-1]}")
    if ctx:
        t = "Côté contexte : " + ", et ".join(ctx) + "."
        lab = (fac("terrain") or fac("veille") or fac("3en4") or fac("voyage"))[0]["label"]
        sc.append(Scene("contexte", "Le contexte", t, meta={"shot": "f_" + lab}))

    # 9. Total et fiabilité.
    t = f"Total : {F} d'environ {_int(spread)} points, soit {_pct(p)} de chances."
    bt = (record or {}).get("backtest") or {}
    for b in bt.get("calibration", []):
        if b["lo"] <= p < b["lo"] + 0.1 + (0.01 if b["lo"] >= 0.9 else 0):
            t += (f" Et ces pourcentages sont vérifiés : quand notre algorithme annonce entre {round(b['lo'] * 100)} et "
                  f"{min(100, round(b['lo'] * 100) + 10)} %, l'équipe gagne {_pct(b['hit'])} du temps.")
            break
    sc.append(Scene("total", f"{F} par {_int(spread)} pts", t, meta={"shot": "f_Écart prévu"}))

    # 10. Cotes et bookmakers.
    side = "home" if fav == home else "away"
    mn = g["min_odds"][side]
    if g.get("odds"):
        best = g["odds"][side]
        french = g["odds"].get("french", True)
        bk = g["odds"].get(f"book_{side}") if french else None
        bk = bk or "les bookmakers"
        pb = g["p_book_home"] if fav == home else 1 - g["p_book_home"]
        if p - pb > 0.10:
            t = (f"Côté cotes, attention : les bookmakers ne donnent les {F} qu'à {_pct(pb)}, cote {fr(best, 2)} chez {bk}, "
                 f"bien au-dessus de notre minimum de {fr(mn, 2)}. Vraie opportunité, ou info qu'ils ont et pas nous : "
                 f"vérifie les blessures avant de miser.")
        elif best >= mn:
            t = (f"Côté cotes, les bookmakers sont d'accord, à {_pct(pb)}. La meilleure cote est à {fr(best, 2)} chez {bk}, "
                 f"au-dessus de notre minimum de {fr(mn, 2)} : selon notre algorithme, ce pari a de la valeur.")
        else:
            t = (f"Côté cotes, les bookmakers sont d'accord, à {_pct(pb)}. Mais la meilleure cote, à {fr(best, 2)} chez {bk}, "
                 f"est sous notre minimum de {fr(mn, 2)} : le pari est probable, mais il rapporte peu. À jouer petit, ou à combiner.")
    else:
        t = f"Côté cotes, notre cote minimum est de {fr(mn, 2)}. Compare-la à celle de ton bookmaker."
    sc.append(Scene("cotes", "Les cotes", t, meta={"shot": "cotes"}))

    # 11. Rien n'est figé.
    gen = datetime.fromisoformat(today["generated_at"]).astimezone(ZoneInfo("Europe/Paris"))
    sc.append(Scene("maj", "Rien n'est figé",
                    f"Prono calculé à {gen.hour} heure{'s' if gen.hour > 1 else ''} {gen.minute:02d} : un forfait de dernière "
                    f"minute peut tout changer.", meta={"card": "maj", "time": f"{gen:%H:%M}"}))

    # 12. Fin.
    sc.append(Scene("cta", "Abonne-toi",
                    "Chaque soir, notre algorithme analyse tous les matchs NBA, joueur par joueur. On t'en offre un : "
                    "abonne-toi pour celui de demain.", meta={"card": "cta", "rev": rev}))
    sc.append(Scene("outro", f"Prono : {F}",
                    "Et rappel : aucun pari n'est sûr, joue de façon responsable.",
                    meta={"card": "outro"}))
    return sc


# ---------------------------------------------------------------- captures

class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(dist: Path) -> tuple[ThreadingHTTPServer, int]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(dist)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


HIDE = ".tabbar{display:none!important} .nightpick{display:none!important} *{animation:none!important;transition:none!important}"


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name)


def capture(g: dict, scenes: list[Scene], out: Path) -> dict:
    from playwright.sync_api import sync_playwright

    dist = ROOT / "app" / "dist"
    if not (dist / "index.html").exists():
        raise SystemExit("App non construite : cd app && npm install && npm run build")
    shutil.copytree(ROOT / "app" / "public" / "data", dist / "data", dirs_exist_ok=True)
    srv, port = serve(dist)
    base = f"http://127.0.0.1:{port}/"
    logos = {}
    wanted = {s.meta.get("shot") for s in scenes if s.meta and s.meta.get("shot")}
    exe = os.environ.get("PW_CHROMIUM")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3,
                                  color_scheme="light", locale="fr-FR", timezone_id="Europe/Paris",
                                  service_workers="block")
        page = ctx.new_page()

        def open_(route: str):
            nonlocal page
            page.close()
            page = ctx.new_page()
            page.goto(base + route)
            page.wait_for_selector(".page, .page-detail")
            page.add_style_tag(content=HIDE)
            page.wait_for_timeout(700)

        # Résultats de la veille : en clair (c'est du passé, et c'est la preuve).
        if "veille" in wanted:
            open_("#/resultats")
            # On garde le score des pronos ; pas les « paris conseillés » (autre sujet que la vidéo).
            page.add_style_tag(content=".kpis .kpi:nth-child(3), .result-bet, .replay-note, .nights{display:none!important}"
                                       ".kpis{grid-template-columns:1.3fr 1fr!important}")
            page.evaluate("window.scrollTo(0,0)")
            page.wait_for_timeout(200)
            page.screenshot(path=str(out / "veille.png"), full_page=True)

        # Liste du soir : seul le match offert est lisible, les autres sont floutés (réservés aux abonnés).
        open_("#/")
        page.evaluate("""id => { document.querySelectorAll('a.game').forEach(a => {
            const on = a.getAttribute('href') === '#/match/' + id;
            if (on) { a.style.boxShadow = '0 0 0 3px #111113, 0 12px 30px rgba(0,0,0,.18)'; a.style.transform = 'scale(1.02)'; }
            else { a.style.filter = 'blur(9px)'; a.style.opacity = '0.75'; }
        }); document.querySelectorAll('.nightpick').forEach(e => e.style.display = 'none'); }""", g["id"])
        page.evaluate("id => document.querySelector(`a.game[href=\"#/match/${id}\"]`).scrollIntoView({block:'center'})", g["id"])
        page.wait_for_timeout(300)
        _shot(page, out / "liste.png", f'a.game[href="#/match/{g["id"]}"]')

        # Détail du match.
        open_(f"#/match/{g['id']}")
        for sel in (".hero .hero-team:first-child svg", ".hero .hero-team:last-child svg"):
            logos[sel] = page.locator(sel).first.evaluate("e => e.outerHTML")
        page.evaluate("window.scrollTo(0,0)")
        _shot(page, out / "match.png")

        # Éléments qui font pencher (et le total), mis en avant un par un.
        rows = page.locator(".factor")
        texts = [rows.nth(i).locator(".factor-label").inner_text() for i in range(rows.count())]
        for shot in sorted(x for x in wanted if x.startswith("f_")):
            lab = shot[2:]
            idx = next((i for i, t in enumerate(texts) if t.startswith(lab)), 0)
            page.evaluate("""i => { const rs = [...document.querySelectorAll('.factor')];
                rs.forEach((r, j) => { r.style.opacity = j === i ? '1' : '0.28';
                  r.style.background = j === i ? 'rgba(23,163,90,.10)' : 'transparent';
                  r.style.borderRadius = '14px'; r.style.paddingLeft = r.style.paddingRight = '8px'; });
                rs[i].scrollIntoView({block: 'center'}); }""", idx)
            page.evaluate("i => document.querySelectorAll('.factor')[i].setAttribute('data-focus', '1')", idx)
            page.wait_for_timeout(250)
            _shot(page, out / f"{_safe(shot)}.png", ".factor[data-focus]")
            page.evaluate("document.querySelectorAll('.factor[data-focus]').forEach(e => e.removeAttribute('data-focus'))")
        page.evaluate("document.querySelectorAll('.factor').forEach(r => { r.style.opacity='1'; r.style.background='transparent'; })")

        # Absents (liste avec le coût de chacun).
        if "absents" in wanted:
            box = page.evaluate("""() => {
                const h = [...document.querySelectorAll('h2.section')].find(x => x.textContent.trim() === 'Absents');
                if (!h) return null;
                const card = h.nextElementSibling;
                const top = h.getBoundingClientRect().top + window.scrollY - 20;
                const bottom = card.getBoundingClientRect().bottom + window.scrollY + 20;
                return {x: 0, y: Math.max(0, top), width: window.innerWidth, height: bottom - Math.max(0, top)};
            }""")
            if box:
                page.screenshot(path=str(out / "absents.png"), full_page=True, clip=box)
            else:
                shutil.copy(out / "match.png", out / "absents.png")

        # Cotes.
        box = page.evaluate("""() => {
            const g = document.querySelector('.odds-grid');
            const end = document.querySelector('.legend') || g;
            let top = g.getBoundingClientRect().top + window.scrollY - 70;
            const bottom = end.getBoundingClientRect().bottom + window.scrollY + 16;
            return {x: 0, y: Math.max(0, top), width: window.innerWidth, height: bottom - Math.max(0, top)};
        }""")
        page.screenshot(path=str(out / "cotes.png"), full_page=True, clip=box)

        # Forces : uniquement les deux équipes du match, sans numéro de rang.
        if "forces" in wanted:
            open_("#/forces")
            page.add_style_tag(content=".rank{display:none!important}")
            page.evaluate("""names => { document.querySelectorAll('.rank-row').forEach(r => {
                const n = r.querySelector('.rank-name').textContent.trim();
                if (!names.includes(n)) r.style.display = 'none'; else r.style.padding = '18px 0'; }); }""",
                          [TEAMS[g["home"]].name, TEAMS[g["away"]].name])
            page.evaluate("window.scrollTo(0,0)")
            page.wait_for_timeout(250)
            _shot(page, out / "forces.png")
        browser.close()
    srv.shutdown()
    return {"home": logos[".hero .hero-team:first-child svg"], "away": logos[".hero .hero-team:last-child svg"]}


def _shot(page, path: Path, focus: str | None = None) -> None:
    """Capture + position verticale (0..1) de l'élément à garder au centre du cadre."""
    page.screenshot(path=str(path))
    fy = 0.0
    if focus:
        fy = page.evaluate("""sel => { const e = document.querySelector(sel); if (!e) return 0;
            const r = e.getBoundingClientRect(); return (r.top + r.height / 2) / window.innerHeight; }""", focus) or 0.0
    path.with_suffix(".focus").write_text(f"{fy:.4f}")


# ------------------------------------------------------------- images 9:16

def phone_frame(shot: Path) -> Image.Image:
    """Capture d'écran dans un cadre arrondi avec ombre, à poser sur le fond."""
    img = Image.open(shot).convert("RGB")
    w = 900
    img = img.resize((w, int(img.height * w / img.width)), Image.LANCZOS)
    r = 56
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width, img.height], r, fill=255)
    framed = Image.new("RGBA", (img.width + 120, img.height + 120), (0, 0, 0, 0))
    shadow = Image.new("RGBA", framed.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([60, 80, 60 + img.width, 80 + img.height], r, fill=(0, 0, 0, 70))
    framed = Image.alpha_composite(framed, shadow.filter(ImageFilter.GaussianBlur(28)))
    framed.paste(img, (60, 60), mask)
    return framed


CORNER = 56
TOP, BOTTOM_SPACE = 300, 340


def _rounded(img: Image.Image) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width, img.height], CORNER, fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _title(d: ImageDraw.ImageDraw, text: str) -> None:
    d.text((W // 2, 210), text, font=font(64), fill=INK, anchor="mm")
    d.rounded_rectangle([W // 2 - 40, 265, W // 2 + 40, 273], 4, fill=(23, 163, 90))


def _shadow(canvas: Image.Image, x: int, y: int, w: int, h: int) -> None:
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x, y + 20, x + w, y + 20 + h], CORNER, fill=(0, 0, 0, 70))
    canvas.paste(sh.filter(ImageFilter.GaussianBlur(28)), (0, 0), sh.filter(ImageFilter.GaussianBlur(28)))


def compose(scene: Scene, shot: Path | None, logos_png: dict, g: dict, out: Path) -> Path | tuple:
    """Image fixe du plan, ou (fond, bande à faire défiler, fenêtre) pour un plan qui défile."""
    canvas = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(canvas)
    if scene.meta and scene.meta.get("card"):
        _title_card(canvas, scene, logos_png, g)
        path = out / f"{scene.key}_frame.png"
        canvas.convert("RGB").save(path)
        return path
    _title(d, scene.title)
    img = Image.open(shot).convert("RGB")
    pw = 900
    img = img.resize((pw, int(img.height * pw / img.width)), Image.LANCZOS)
    win_h = H - TOP - BOTTOM_SPACE - 60
    x = (W - pw) // 2
    if scene.meta.get("scroll") and img.height > win_h:
        # Plan qui défile : la bande (capture pleine page) glisse dans une fenêtre arrondie.
        _shadow(canvas, x, TOP, pw, win_h)
        bg = out / f"{scene.key}_bg.png"
        canvas.convert("RGB").save(bg)
        strip = out / f"{scene.key}_strip.png"
        img.save(strip)
        # Coins arrondis : masque posé par-dessus la fenêtre.
        mask = Image.new("RGBA", (pw, win_h), BG + (255,))
        hole = Image.new("L", (pw, win_h), 255)
        ImageDraw.Draw(hole).rounded_rectangle([0, 0, pw, win_h], CORNER, fill=0)
        mask.putalpha(hole)
        corners = out / f"{scene.key}_corners.png"
        mask.save(corners)
        return (bg, strip, corners, x, TOP, win_h)
    # Plan fixe : fenêtre centrée sur l'élément important (match du soir, ligne mise en avant…).
    focus = shot.with_suffix(".focus")
    fy = float(focus.read_text()) if focus.exists() else 0.0
    if img.height > win_h:
        cy = int(fy * img.height) if fy > 0 else win_h // 2
        y0 = min(max(0, cy - win_h // 2), img.height - win_h)
        img = img.crop((0, y0, pw, y0 + win_h))
    _shadow(canvas, x, TOP, pw, img.height)
    r = _rounded(img)
    canvas.paste(r, (x, TOP), r)
    path = out / f"{scene.key}_frame.png"
    canvas.convert("RGB").save(path)
    return path


def _check(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int, ok: bool = True) -> None:
    col = (23, 163, 90) if ok else (217, 68, 58)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    w = max(6, r // 5)
    if ok:
        d.line([(cx - r * 0.45, cy + r * 0.02), (cx - r * 0.1, cy + r * 0.38), (cx + r * 0.5, cy - r * 0.35)], fill="white", width=w, joint="curve")
    else:
        d.line([(cx - r * 0.38, cy - r * 0.38), (cx + r * 0.38, cy + r * 0.38)], fill="white", width=w)
        d.line([(cx + r * 0.38, cy - r * 0.38), (cx - r * 0.38, cy + r * 0.38)], fill="white", width=w)


def _title_card(canvas: Image.Image, scene: Scene, logos: dict, g: dict) -> None:
    d = ImageDraw.Draw(canvas)
    home, away = g["home"], g["away"]
    fav = home if g["p_home"] >= 0.5 else away
    p = round(max(g["p_home"], 1 - g["p_home"]) * 100)
    green = (23, 163, 90)
    card = scene.meta["card"]
    rev = scene.meta.get("rev")
    if card == "intro":
        d.text((W // 2, 330), "PRONOS NBA", font=font(52, "SemiBold"), fill=green, anchor="mm")
        if rev:
            d.text((W // 2, 700), f"{rev['hits']}/{rev['n']}", font=font(300), fill=INK, anchor="mm")
            d.text((W // 2, 900), "hier soir", font=font(80, "SemiBold"), fill=INK, anchor="mm")
            # une pastille par match de la veille
            n = rev["n"]
            r = 34 if n <= 10 else 26
            gap = 2 * r + 18
            x0 = W // 2 - (n - 1) * gap // 2
            for i, e in enumerate(rev["night"]):
                ok = (e["p_home"] >= 0.5) == (e["home_win"] == 1)
                _check(d, x0 + i * gap, 1060, r, ok)
            d.text((W // 2, 1200), "bons pronos de notre algorithme", font=font(44, "Medium"), fill=MUTED, anchor="mm")
        else:
            d.text((W // 2, 800), "Le prono du soir", font=font(90), fill=INK, anchor="mm")
    elif card == "maj":
        d.text((W // 2, 520), scene.meta.get("time", ""), font=font(200), fill=INK, anchor="mm")
        d.text((W // 2, 680), "heure du calcul", font=font(48, "Medium"), fill=MUTED, anchor="mm")
        d.rounded_rectangle([140, 820, W - 140, 1100], 40, fill=(255, 255, 255))
        d.text((W // 2, 900), "Mise à jour toutes les 30 min", font=font(48, "SemiBold"), fill=INK, anchor="mm")
        d.text((W // 2, 980), "jusqu'au coup d'envoi", font=font(48, "SemiBold"), fill=INK, anchor="mm")
        d.text((W // 2, 1050), "un forfait peut tout changer", font=font(38, "Medium"), fill=(232, 137, 12), anchor="mm")
    elif card == "cta":
        y = 420
        if rev:
            d.text((W // 2, y), f"{rev['hits']}/{rev['n']} hier", font=font(70), fill=green, anchor="mm")
            y += 120
        d.text((W // 2, y + 60), "1 match offert", font=font(84), fill=INK, anchor="mm")
        d.text((W // 2, y + 160), "chaque soir", font=font(84), fill=INK, anchor="mm")
        d.text((W // 2, y + 300), "Tous les matchs dans notre appli,", font=font(44, "Medium"), fill=MUTED, anchor="mm")
        d.text((W // 2, y + 360), "bientôt", font=font(44, "Medium"), fill=MUTED, anchor="mm")
        d.rounded_rectangle([W // 2 - 300, y + 470, W // 2 + 300, y + 590], 60, fill=INK)
        d.text((W // 2, y + 530), "Abonne-toi", font=font(60), fill=(255, 255, 255), anchor="mm")
    else:
        lf = logos["home" if fav == home else "away"].resize((360, 360))
        d.text((W // 2, 330), "PRONOSTIC", font=font(54, "SemiBold"), fill=green, anchor="mm")
        canvas.paste(lf, ((W - 360) // 2, 440), lf)
        d.text((W // 2, 900), f"{nick(fav)} gagnant", font=font(84), fill=INK, anchor="mm")
        d.text((W // 2, 1030), f"{p} %", font=font(150), fill=INK, anchor="mm")
        d.text((W // 2, 1150), "selon notre algorithme", font=font(42, "Medium"), fill=MUTED, anchor="mm")
        small = font(30, "Medium")
        y = 1300
        for line in ("Aucun pari n'est sûr. Misez petit.", "Jouer comporte des risques : endettement,",
                     "isolement, dépendance. 09 74 75 13 13", "(appel non surtaxé) · Interdit aux mineurs"):
            d.text((W // 2, y), line, font=small, fill=MUTED, anchor="mm")
            y += 44


def svg_to_png(svg: str, path: Path) -> Image.Image:
    """Logo SVG (tiré de l'app) -> PNG transparent via le navigateur."""
    from playwright.sync_api import sync_playwright

    exe = os.environ.get("PW_CHROMIUM")
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
        pg = b.new_page(viewport={"width": 600, "height": 600})
        pg.set_content(f'<html><body style="margin:0;background:transparent">'
                       f'<div style="width:600px;height:600px">{svg.replace("<svg ", "<svg width=600 height=600 ", 1)}</div></body></html>')
        pg.screenshot(path=str(path), omit_background=True)
        b.close()
    return Image.open(path).convert("RGBA")


# ------------------------------------------------------------------- voix

def tts(text: str, path: Path, engine: str) -> Path:
    if engine == "edge":
        import edge_tts

        mp3 = path.with_suffix(".mp3")
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        asyncio.run(edge_tts.Communicate(text, VOICE, rate="+14%", pitch="+2Hz", proxy=proxy).save(str(mp3)))
        return mp3
    if engine == "espeak":
        wav = path.with_suffix(".wav")
        subprocess.run(["espeak-ng", "-v", "fr-fr", "-s", "168", "-p", "40", "-w", str(wav), text], check=True)
        return wav
    # Sans voix : silence proportionnel à la longueur du texte (sous-titres seuls).
    wav = path.with_suffix(".wav")
    secs = max(2.5, len(text.split()) / 2.6)
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{secs:.2f}", str(wav)])
    return wav


# --------------------------------------------------------------- montage

def ass_subs(scenes: list[Scene], starts: list[float], durs: list[float], path: Path) -> None:
    """Sous-titres façon réseaux sociaux : phrases courtes, gros caractères, en bas."""
    def ts(t: float) -> str:
        h, r = divmod(t, 3600)
        m, s = divmod(r, 60)
        return f"{int(h)}:{int(m):02d}:{s:05.2f}"

    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "",
             "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
             "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
             "MarginR, MarginV, Encoding",
             "Style: Sub,Inter,58,&H00FFFFFF,&H00FFFFFF,&H00131111,&HB0131111,1,0,0,0,100,100,0,0,3,18,0,2,90,90,150,1",
             "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for s, t0, dur in zip(scenes, starts, durs):
        words = s.text.split()
        chunks, cur = [], []
        for w in words:
            cur.append(w)
            if len(" ".join(cur)) > 34 or w.endswith((".", ":", "?", "!")):
                chunks.append(" ".join(cur))
                cur = []
        if cur:
            chunks.append(" ".join(cur))
        total = sum(len(c) for c in chunks) or 1
        t = t0
        for c in chunks:
            dt = dur * len(c) / total
            lines.append(f"Dialogue: 0,{ts(t)},{ts(t + dt)},Sub,,0,0,0,,{c}")
            t += dt
    path.write_text("\n".join(lines), encoding="utf-8")


def make(match_id: str | None = None, voice: str = "edge", out_dir: Path | None = None) -> Path:
    today = json.loads((ROOT / "app" / "public" / "data" / "today.json").read_text())
    g = pick_game(today, match_id)
    rpath = ROOT / "app" / "public" / "data" / "ratings.json"
    ratings = json.loads(rpath.read_text()) if rpath.exists() else None
    rec_path = ROOT / "app" / "public" / "data" / "record.json"
    record = json.loads(rec_path.read_text()) if rec_path.exists() else None
    scenes = script(g, today, ratings, record)
    save_offer(today["date"], g["id"])
    out_dir = out_dir or ROOT / "data" / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"prono_{today['date']}_{g['home']}-{g['away']}"
    with tempfile.TemporaryDirectory() as tmp_:
        tmp = Path(tmp_)
        logos_svg = capture(g, scenes, tmp)
        logos = {k: svg_to_png(v, tmp / f"logo_{k}.png") for k, v in logos_svg.items()}

        # Voix off par scène ; la durée de chaque plan suit sa phrase.
        try:
            audios = [tts(s.text, tmp / f"voix_{i}", voice) for i, s in enumerate(scenes)]
        except Exception as e:
            print(f"Voix « {voice} » indisponible ({e.__class__.__name__}) : vidéo sans voix (sous-titres seuls).")
            voice = "aucune"
            audios = [tts(s.text, tmp / f"voix_{i}", voice) for i, s in enumerate(scenes)]
        durs = [duration(a) + 0.3 for a in audios]

        clips = []
        for i, (s, dur) in enumerate(zip(scenes, durs)):
            shot = None if (s.meta or {}).get("card") else tmp / f"{_safe(s.meta['shot'])}.png"
            frame = compose(s, shot, logos, g, tmp)
            clip = tmp / f"clip_{i}.mp4"
            n = int(dur * FPS) + int(FADE * FPS) + 2
            if isinstance(frame, tuple):
                bg, strip, corners, fx, fy, win_h = frame
                total = dur + FADE
                # Défilement doux : pause 0,8 s, puis descente jusqu'en bas, pause finale.
                travel = f"max(0,min(1,(t-0.8)/{max(1.0, total - 2.0):.2f}))"
                ypos = f"(ih-{win_h})*({travel})*({travel})*(3-2*({travel}))"
                ypos = f"(ih-{win_h})*(3*pow({travel},2)-2*pow({travel},3))"
                run(["ffmpeg", "-y", "-loop", "1", "-i", str(bg), "-loop", "1", "-i", str(strip),
                     "-loop", "1", "-i", str(corners), "-i", str(audios[i]),
                     "-filter_complex",
                     f"[1:v]crop=iw:{win_h}:0:'{ypos}'[s];[0:v][s]overlay={fx}:{fy}[b];[b][2:v]overlay={fx}:{fy},"
                     f"fps={FPS},format=yuv420p[v];[3:a]aresample=48000,apad=whole_dur={total:.2f}[a]",
                     "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "veryfast",
                     "-crf", "20", "-c:a", "aac", "-b:a", "160k", str(clip)])
                clips.append(clip)
                continue
            # Zoom lent et léger décalage (effet « Ken Burns »), alterné d'un plan à l'autre.
            zin = i % 2 == 0
            z = "'min(1.0+0.0005*on,1.06)'" if zin else "'max(1.06-0.0005*on,1.0)'"
            y = "'ih/2-(ih/zoom/2)'"
            vf = (f"scale={W * 2}:{H * 2},zoompan=z={z}:x='iw/2-(iw/zoom/2)':y={y}:d={n}:s={W}x{H}:fps={FPS},"
                  f"format=yuv420p")
            run(["ffmpeg", "-y", "-loop", "1", "-i", str(frame), "-i", str(audios[i]),
                 "-filter_complex", f"[0:v]{vf}[v];[1:a]aresample=48000,apad=whole_dur={dur + FADE:.2f}[a]",
                 "-map", "[v]", "-map", "[a]", "-t", f"{dur + FADE:.2f}", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "20", "-c:a", "aac", "-b:a", "160k", str(clip)])
            clips.append(clip)

        # Enchaînement avec fondus (vidéo et son).
        inputs, fc = [], []
        for c in clips:
            inputs += ["-i", str(c)]
        starts, t, vprev, aprev = [], 0.0, "[0:v]", "[0:a]"
        starts.append(0.0)
        for i in range(1, len(clips)):
            t += durs[i - 1]
            starts.append(t)
            fc.append(f"{vprev}[{i}:v]xfade=transition={'slideleft' if i % 3 else 'fade'}:duration={FADE}:offset={t:.2f}[v{i}]")
            fc.append(f"{aprev}[{i}:a]acrossfade=d={FADE}[a{i}]")
            vprev, aprev = f"[v{i}]", f"[a{i}]"
        subs = tmp / "subs.ass"
        ass_subs(scenes, starts, durs, subs)
        fc.append(f"{vprev}subtitles={subs}[vout]")
        out = out_dir / f"{name}.mp4"
        run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[vout]", "-map", aprev,
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)])
    (out_dir / f"{name}.txt").write_text("\n\n".join(f"[{s.title}]\n{s.text}" for s in scenes), encoding="utf-8")
    print(f"Vidéo : {out}  ({sum(durs):.0f} s, voix {voice})")
    return out
