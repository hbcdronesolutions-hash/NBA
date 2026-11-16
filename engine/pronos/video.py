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


def script(g: dict, n_games: int, ratings: dict | None = None) -> list[Scene]:
    """Texte de la voix off : accroche, explication détaillée du vainqueur, cotes, appel à s'abonner."""
    home, away = g["home"], g["away"]
    fav = home if g["p_home"] >= 0.5 else away
    other = away if fav == home else home
    p = round(max(g["p_home"], 1 - g["p_home"]) * 100)
    spread = abs(g["spread"])
    F, O = nick(fav), nick(other)
    lieu = "à domicile" if fav == home else "à l'extérieur"
    rt = {t["abbr"]: t for t in (ratings or {}).get("teams", [])}
    facts = {f["key"] + (f.get("team") or ""): f for f in g["factors"]}
    by_key = lambda k: [f for f in g["factors"] if f["key"] == k and abs(f["points"]) >= 0.3]

    sc = [Scene("intro", f"{F} à {p} %",
                f"Ce soir, notre algorithme a un favori très clair : les {F}, à {p} % ! "
                f"Je t'explique tout de suite pourquoi.")]
    sc.append(Scene("liste", "Ce soir",
                    f"Chaque soir, l'appli analyse tous les matchs NBA de la nuit. Ce soir, il y en a {n_games}, "
                    f"et celui-ci sort clairement du lot : les {F} {lieu}, face aux {O}."))
    book = ""
    if g.get("p_book_home") is not None:
        pb = round((g["p_book_home"] if fav == home else 1 - g["p_book_home"]) * 100)
        book = (f" Et les bookmakers vont dans le même sens, à {pb} %." if abs(pb - p) <= 5 else
                f" Les bookmakers, eux, ne sont qu'à {pb} % : notre modèle y croit plus qu'eux.")
    sc.append(Scene("match", f"{F} gagnant à {p} %",
                    f"Notre modèle donne {p} % de chances de victoire aux {F}, avec environ "
                    f"{round(spread)} points d'avance prévus.{book}"))

    # Le niveau des équipes : la méthode, puis les chiffres.
    force = by_key("force")
    if force:
        f0 = force[0]
        sc.append(Scene("methode", "Comment on mesure le niveau",
                        "Premier argument, et c'est le plus important : le vrai niveau des deux équipes. "
                        "On ne regarde pas le classement. On mesure, pour 100 possessions, combien chaque équipe "
                        "marque et combien elle encaisse, en tenant compte de la force des adversaires qu'elle a "
                        "affrontés, et en donnant plus de poids aux matchs récents."))
        if fav in rt and other in rt:
            a_, b_ = rt[fav], rt[other]
            nums = (f"Résultat : les {F} marquent {fr(a_['off'])} points et en encaissent {fr(a_['def'])} "
                    f"pour 100 possessions. Les {O} : {fr(b_['off'])} marqués, {fr(b_['def'])} encaissés. ")
        else:
            nums = ""
        who = home if f0["points"] >= 0 else away
        sc.append(Scene("facteur_force", "Niveau des équipes",
                        f"{nums}Ramené au rythme de ce match, cet écart de niveau vaut à lui seul "
                        f"{_pts(f0['points'])} d'avance pour les {nick(who)}.", meta={"factor": f0["label"]}))

    rest = sorted([f for f in g["factors"] if f["key"] != "force" and abs(f["points"]) >= 0.3],
                  key=lambda f: -abs(f["points"]))[:3]
    n_pour = 0
    for i, f in enumerate(rest):
        who = home if f["points"] >= 0 else away
        pour = who == fav                      # cet élément renforce-t-il le favori ?
        k, Wn, pts = f["key"], nick(who), _pts(f["points"])
        team_txt = nick(f.get("team") or who)
        if pour:
            n_pour += 1
            lead = "Deuxième argument" if n_pour == 1 else "Autre argument" if n_pour == 2 else "Et encore"
        else:
            lead = f"En face, un point pour les {Wn}"
        if k == "terrain":
            t = (f"{lead} : les {nick(home)} jouent à la maison. En NBA, l'avantage du terrain vaut en moyenne "
                 f"{pts}." + ("" if pour else " Mais c'est loin de suffire à combler l'écart."))
        elif k == "veille":
            t = (f"{lead} : la fatigue. Les {team_txt} ont joué hier soir, et dans nos données, enchaîner deux "
                 f"soirs de suite coûte environ {pts}.")
        elif k == "3en4":
            t = f"{lead} : les {team_txt} enchaînent leur troisième match en quatre jours. Ça vaut {pts} pour les {Wn}."
        elif k in ("effectif", "absents"):
            det = f["detail"]
            if " sans " in det:
                missing = det.split(" sans ", 1)[1].replace(" (absent)", "").replace(" (douteux)", ", incertain,").replace(" (incertain)", ", incertain,")
                txt = f"les {team_txt} seront privés de {missing.rstrip(',')}"
            elif "plus complet" in det:
                txt = f"les {team_txt} retrouvent un effectif plus complet que lors de leurs derniers matchs"
            else:
                txt = f"les {team_txt} n'ont pas tout à fait leur effectif habituel"
            t = (f"{lead} : l'effectif du soir. On regarde qui joue vraiment : {txt}. On a mesuré ce que chaque "
                 f"joueur apporte quand il est sur le terrain, et ça représente {pts} pour les {Wn}.")
        elif k == "voyage":
            t = f"{lead} : le voyage. {f['detail'].replace(' :', ',')}. Ça vaut {pts} pour les {Wn}."
        elif k == "altitude":
            t = f"{lead} : l'altitude, toujours difficile pour les visiteurs. Ça vaut {pts} pour les {Wn}."
        else:
            t = f"{lead} : {f['label'].lower()}. {f['detail']}. Ça vaut {pts}."
        sc.append(Scene(f"facteur{i}", f["label"], t, meta={"factor": f["label"]}))

    sc.append(Scene("total", f"{F} par {fr(spread)} pts",
                    f"On additionne tout ça : victoire des {F} de {fr(spread)} points. "
                    f"Voilà d'où viennent nos {p} %.", meta={"factor": "Écart prévu"}))

    side = "home" if fav == home else "away"
    mn = g["min_odds"][side]
    if g.get("odds"):
        best = g["odds"][side]
        bk = g["odds"].get(f"book_{side}") or g["odds"].get("book") or "le bookmaker"
        if best >= mn:
            t = (f"Et côté cotes, bonne nouvelle : la meilleure cote est à {fr(best, 2)} chez {bk}, au-dessus "
                 f"de notre cote minimum de {fr(mn, 2)}. Selon le modèle, le pari a de la valeur.")
        else:
            t = (f"Petit bémol, on reste honnête : la meilleure cote est à {fr(best, 2)} chez {bk}, sous notre "
                 f"minimum de {fr(mn, 2)}. Le pari est très probable, mais il rapporte peu : à jouer petit, "
                 f"ou en combiné.")
    else:
        t = f"Côté cotes : notre cote minimum est de {fr(mn, 2)}. Compare-la à celle de ton bookmaker."
    sc.append(Scene("cotes", "Les cotes", t))
    sc.append(Scene("cta", "Abonne-toi",
                    "Tu veux nos pronos chaque soir, avec toutes les explications ? Abonne-toi, et télécharge "
                    "l'appli : le lien est dans ma bio. On se retrouve demain pour le prochain match !"))
    sc.append(Scene("outro", f"Prono : {F}",
                    "Rappel : aucun pari n'est sûr. Jouer comporte des risques. Appelle le 09 74 75 13 13 "
                    "pour être aidé."))
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


def capture(g: dict, scenes: list[Scene], out: Path) -> dict:
    from playwright.sync_api import sync_playwright

    dist = ROOT / "app" / "dist"
    if not (dist / "index.html").exists():
        raise SystemExit("App non construite : cd app && npm install && npm run build")
    shutil.copytree(ROOT / "app" / "public" / "data", dist / "data", dirs_exist_ok=True)
    srv, port = serve(dist)
    base = f"http://127.0.0.1:{port}/"
    logos = {}
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

        # Liste du soir, carte du match mise en avant.
        open_("#/")
        card = page.locator(f'a.game[href="#/match/{g["id"]}"]')
        card.scroll_into_view_if_needed()
        page.evaluate("""id => { document.querySelectorAll('a.game').forEach(a => {
            const on = a.getAttribute('href') === '#/match/' + id;
            a.style.opacity = on ? '1' : '0.35';
            if (on) { a.style.boxShadow = '0 0 0 3px #111113, 0 12px 30px rgba(0,0,0,.18)'; a.style.transform = 'scale(1.02)'; }
        }); }""", g["id"])
        page.evaluate("id => document.querySelector(`a.game[href=\"#/match/${id}\"]`).scrollIntoView({block:'center'})", g["id"])
        page.wait_for_timeout(300)
        _shot(page, out / "liste.png")

        # Détail du match.
        open_(f"#/match/{g['id']}")
        for sel in (".hero .hero-team:first-child svg", ".hero .hero-team:last-child svg"):
            logos[sel] = page.locator(sel).first.evaluate("e => e.outerHTML")
        page.evaluate("window.scrollTo(0,0)")
        _shot(page, out / "match.png")

        # Chaque élément qui fait pencher (et le total), mis en avant tour à tour.
        rows = page.locator(".factor")
        texts = [rows.nth(i).locator(".factor-label").inner_text() for i in range(rows.count())]
        for s in [x for x in scenes if x.meta and x.meta.get("factor")]:
            lab = s.meta["factor"]
            idx = next((i for i, t in enumerate(texts) if t.startswith(lab)), 0)
            page.evaluate("""i => { const rs = [...document.querySelectorAll('.factor')];
                rs.forEach((r, j) => { r.style.opacity = j === i ? '1' : '0.28';
                  r.style.background = j === i ? 'rgba(23,163,90,.10)' : 'transparent';
                  r.style.borderRadius = '14px'; r.style.paddingLeft = r.style.paddingRight = '8px'; });
                rs[i].scrollIntoView({block: 'center'}); }""", idx)
            page.wait_for_timeout(250)
            _shot(page, out / f"{s.key}.png")
        page.evaluate("document.querySelectorAll('.factor').forEach(r => { r.style.opacity='1'; r.style.background='transparent'; })")

        # Cotes.
        box = page.evaluate("""() => {
            const g = document.querySelector('.odds-grid');
            const end = document.querySelector('.legend') || g;
            let top = g.getBoundingClientRect().top + window.scrollY - 70;
            const bottom = end.getBoundingClientRect().bottom + window.scrollY + 16;
            return {x: 0, y: Math.max(0, top), width: window.innerWidth, height: bottom - Math.max(0, top)};
        }""")
        page.screenshot(path=str(out / "cotes.png"), full_page=True, clip=box)

        # Méthode : l'onglet Forces, réduit aux deux équipes du match (sans numéro de rang).
        if any(x.key == "methode" for x in scenes):
            open_("#/forces")
            page.add_style_tag(content=".rank{display:none!important}")
            page.evaluate("""names => { document.querySelectorAll('.rank-row').forEach(r => {
                const n = r.querySelector('.rank-name').textContent.trim();
                if (!names.includes(n)) r.style.display = 'none';
                else { r.style.padding = '18px 0'; } }); }""", [TEAMS[g["home"]].name, TEAMS[g["away"]].name])
            page.evaluate("window.scrollTo(0,0)")
            page.wait_for_timeout(250)
            _shot(page, out / "methode.png")
        browser.close()
    srv.shutdown()
    return {"home": logos[".hero .hero-team:first-child svg"], "away": logos[".hero .hero-team:last-child svg"]}


def _shot(page, path: Path) -> None:
    page.screenshot(path=str(path))


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


def compose(scene: Scene, shot: Path | None, logos_png: dict, g: dict, out: Path) -> Path:
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    if scene.key in ("intro", "outro", "cta"):
        _title_card(canvas, scene, logos_png, g)
    else:
        # Bandeau titre.
        f = font(64)
        d.text((W // 2, 210), scene.title, font=f, fill=INK, anchor="mm")
        d.rounded_rectangle([W // 2 - 40, 265, W // 2 + 40, 273], 4, fill=(23, 163, 90))
        fr_ = phone_frame(shot)
        top = 300
        maxh = H - top - 340   # place pour les sous-titres
        if fr_.height > maxh:
            fr_ = fr_.crop((0, 0, fr_.width, maxh))
        canvas.paste(fr_, ((W - fr_.width) // 2, top), fr_)
    path = out / f"{scene.key}_frame.png"
    canvas.save(path)
    return path


def _title_card(canvas: Image.Image, scene: Scene, logos: dict, g: dict) -> None:
    d = ImageDraw.Draw(canvas)
    home, away = g["home"], g["away"]
    fav = home if g["p_home"] >= 0.5 else away
    p = round(max(g["p_home"], 1 - g["p_home"]) * 100)
    green = (23, 163, 90)
    if scene.key == "intro":
        d.text((W // 2, 300), "PRONO NBA DU SOIR", font=font(52, "SemiBold"), fill=green, anchor="mm")
        lh, la = logos["home"].resize((330, 330)), logos["away"].resize((330, 330))
        canvas.paste(lh, (120, 470), lh)
        canvas.paste(la, (W - 450, 470), la)
        d.text((W // 2, 635), "vs", font=font(56, "Medium"), fill=MUTED, anchor="mm")
        d.text((285, 850), nick(home), font=font(52), fill=INK, anchor="mm")
        d.text((W - 285, 850), nick(away), font=font(52), fill=INK, anchor="mm")
        d.text((285, 910), "à domicile", font=font(34, "Medium"), fill=MUTED, anchor="mm")
        d.text((W // 2, 1150), f"{p} %", font=font(230), fill=INK, anchor="mm")
        d.text((W // 2, 1310), f"pour les {nick(fav)}", font=font(56, "SemiBold"), fill=INK, anchor="mm")
        tip = g.get("tip_utc")
        if tip:
            t = datetime.fromisoformat(tip).astimezone(ZoneInfo("Europe/Paris"))
            d.text((W // 2, 1400), f"Coup d'envoi {t:%H:%M}", font=font(40, "Medium"), fill=MUTED, anchor="mm")
    elif scene.key == "cta":
        icon = ROOT / "app" / "public" / "icons" / "icon-512.png"
        if icon.exists():
            ic = Image.open(icon).convert("RGBA").resize((300, 300))
            m = Image.new("L", ic.size, 0)
            ImageDraw.Draw(m).rounded_rectangle([0, 0, 300, 300], 66, fill=255)
            canvas.paste(ic, ((W - 300) // 2, 380), m)
        d.text((W // 2, 820), "Un prono expliqué", font=font(76), fill=INK, anchor="mm")
        d.text((W // 2, 910), "chaque soir", font=font(76), fill=INK, anchor="mm")
        d.rounded_rectangle([W // 2 - 300, 1030, W // 2 + 300, 1150], 60, fill=INK)
        d.text((W // 2, 1090), "Abonne-toi", font=font(60), fill=(255, 255, 255), anchor="mm")
        d.text((W // 2, 1250), "Appli gratuite : lien dans la bio", font=font(46, "SemiBold"), fill=green, anchor="mm")
    else:
        lf = logos["home" if fav == home else "away"].resize((360, 360))
        d.text((W // 2, 330), "PRONOSTIC", font=font(54, "SemiBold"), fill=green, anchor="mm")
        canvas.paste(lf, ((W - 360) // 2, 440), lf)
        d.text((W // 2, 900), f"{nick(fav)} gagnant", font=font(84), fill=INK, anchor="mm")
        d.text((W // 2, 1030), f"{p} %", font=font(150), fill=INK, anchor="mm")
        d.text((W // 2, 1150), "selon notre modèle", font=font(42, "Medium"), fill=MUTED, anchor="mm")
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
        asyncio.run(edge_tts.Communicate(text, VOICE, rate="+10%", pitch="+2Hz", proxy=proxy).save(str(mp3)))
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
    scenes = script(g, len(today["games"]), ratings)
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
        durs = [duration(a) + 0.55 for a in audios]

        clips = []
        for i, (s, dur) in enumerate(zip(scenes, durs)):
            shot = tmp / f"{s.key}.png" if s.key not in ("intro", "outro", "cta") else None
            frame = compose(s, shot, logos, g, tmp)
            clip = tmp / f"clip_{i}.mp4"
            n = int(dur * FPS) + int(FADE * FPS) + 2
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
