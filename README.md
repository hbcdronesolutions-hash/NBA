# Pronos NBA

Probabilité de victoire de chaque équipe pour les matchs NBA de la nuit, expliquée par les facteurs qui l'ont fait bouger. Usage personnel.

- `engine/` : le moteur Python (collecte, notes, prévisions, backtest, journal) — tourne sur ton PC.
- `app/` : l'app mobile (PWA installable sur l'écran d'accueil du téléphone).

## Les écrans

| Onglet | Contenu |
|---|---|
| **Résultats** | Chaque soirée : score final, pronostic de l'app (juste ou faux), pari conseillé (pastille verte) et son gain en unités. Avant le 15/11 : saison rejouée, marquée « Rejoué ». |
| **Ce soir** | Matchs de la nuit (heure française), probabilité de chaque équipe, cote minimum colorée, repère des bookmakers sur la barre, alerte quand l'écart dépasse 5 points de %. |
| Détail d'un match | 3 onglets. **Vainqueur** : écart prévu, ce qui fait pencher, absents, cotes. **Écart** : « gagne de X ou + » (1 à 15 pts) pour chaque équipe, probabilité et cote minimum. **Joueurs** : prévision points / rebonds / passes / P+R+P, puis « plus de / moins de » pour chaque ligne, probabilité et cote minimum. |
| Désaccord bookmakers | Petit encart en haut de « Ce soir » : le match où notre algorithme et les bookmakers sont le plus en désaccord (notre % contre le leur). Information, pas un conseil de pari : test réaliste sur 2 saisons à −3,8 %. Suivi dans Résultats et Bilan. |
| **Sélection** | Matchs au-dessus du seuil (curseur 60–80 %, 70 % par défaut), badges Très sûr / Sûr / Correct, probabilité « tous justes », cote minimum du combiné si toutes les pastilles sont vertes. |
| **Forces** | Les 30 équipes : note nette, attaque, défense, évolution sur 15 matchs. |
| **Bilan** | Réussite globale et sur 7 jours, calibration, face aux bookmakers, référence backtest, journal complet. |

Pastilles : **vert** = cote du bookmaker ≥ cote minimum, **gris** = ne pas miser, **orange** = plus de 15 % au-dessus du minimum, à vérifier (blessé, transfert…).

## Installation (une fois, sur ton PC)

```bash
# Moteur
cd engine
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt

# App
cd ../app
npm install
npm run build
```

Le dépôt contient les paramètres réglés par le backtest sur données réelles (`data/params.json`) et le journal. La base (`data/pronos.sqlite`) se reconstruit avec `python -m pronos init` (~2 min). `python -m pronos demo` reste disponible pour une ligue simulée.

## Données réelles

```bash
cd engine
python -m pronos init        # 4 saisons + saison en cours via ESPN (déjà fait, ~2 min)
python -m pronos backtest    # règle les paramètres et écrit data/params.json
python -m pronos matin       # chaque matin : résultats, calendrier, stats joueurs
python -m pronos soir        # avant les matchs : blessures, cotes, prévisions, journal
python -m pronos serve       # affiche l'adresse à ouvrir sur le téléphone (même Wi-Fi)
```

Sur le téléphone : ouvrir l'adresse, puis **Partager → Sur l'écran d'accueil** (iPhone) ou **Installer l'application** (Android).

- Cotes françaises (Betclic, Unibet, Winamax, PMU, Parions Sport, NetBet) : clé gratuite sur the-odds-api.com, puis `export ODDS_API_KEY=...` (ou secret GitHub `ODDS_API_KEY`). L'app prend la meilleure cote française par équipe ; sans clé, cotes DraftKings via ESPN.
- Sources : ESPN (calendrier, scores, box scores, cotes DraftKings) et rapport officiel des blessures NBA. stats.nba.com bloque les serveurs cloud ; ESPN non.
- Automatisation : tâche planifiée (Planificateur de tâches Windows, `cron` sur Mac/Linux), par ex. `matin` à 9 h et `soir` à 18 h.

## Mise à jour automatique (GitHub Actions)

Le fichier `.github/workflows/pronos.yml` tourne tout seul, sans PC allumé :

| Heure (Paris, hiver) | Ce qui se passe |
|---|---|
| 10h17 | Résultats de la nuit, calendrier, box scores, prévisions |
| 17h47 | Rapport des blessures, cotes, prévisions mises à jour |
| 23h37 | Dernier rapport des blessures avant les matchs |
| Lundi 6h23 | Backtest et réglage des paramètres |

À chaque passage : collecte (ESPN + rapport officiel NBA), prévisions, journal (`data/journal.csv`, versionné), construction de l'app et mise en ligne sur GitHub Pages. Une prévision peut être mise à jour jusqu'au coup d'envoi, puis elle est figée.

Mise en place (une fois) : **Settings → Pages → Source : GitHub Actions**. Lancement manuel : onglet **Actions → Pronos NBA → Run workflow**. Clé The Odds API facultative : secret `ODDS_API_KEY`.

## Vidéo de la prédiction du soir (compatible TikTok)

`python -m pronos video` fabrique une vidéo verticale (1080×1920) du match le plus sûr du soir : bilan de la veille
(résultats qui défilent), match du soir (autres matchs floutés), analyse statistique détaillée (niveau pour 100
possessions, tendance, rythme, absents joueur par joueur, contexte, fiabilité vérifiée), voix off naturelle
(`edge-tts`) et sous-titres.

Aucun contenu de jeux d'argent (règles TikTok) : ni cotes, ni bookmakers, ni vocabulaire de pari, à l'écran comme dans
la voix. Le fichier `.txt` contient le texte de la voix off et une légende avec des hashtags neutres.

Automatique chaque jour à 18h23 (Paris) via `.github/workflows/video.yml`. Lien fixe vers la dernière vidéo :
https://github.com/hbcdronesolutions-hash/NBA/releases/download/video-du-soir/prono-du-soir.mp4
(aussi dans **Actions → Vidéo du prono → Artifacts**). Lancement manuel possible, avec un identifiant de match.

## Le modèle (fiche de conception V1)

1. **Force de base** : attaque / défense pour 100 possessions, corrigées de la force des adversaires, demi-vie de 60 jours, a priori de saison passée (70 %, ≈ 8 matchs).
2. **Effectif du soir (v1.1)** : valeur de chaque joueur mesurée sur 4 saisons (régression « avec / sans » sur l'écart au score, a priori tiré des statistiques individuelles). Ce soir, force de l'effectif disponible (rapport des blessures, effectifs officiels, minutes des 10 derniers matchs de l'équipe) comparée à celle des derniers matchs. Backtest 2025-26 + 2026-27 avec les rapports de blessures d'époque (information réellement disponible avant le match) : log loss 0,595 → 0,5845, bons vainqueurs 68,6 % (69,0 % sans) ; avec les joueurs réellement présents connus d'avance : 0,581 et 69,7 % (bookmakers 0,568).
3. **Contexte** : terrain +1,8 · veille −2,1 · 3 en 4 −0,6 · Denver/Utah +1,5 · −0,15 par 1 000 km et par heure de décalage.
4. Croisement Four Factors : retiré (n'apporte rien au backtest).
5. **Probabilité** : loi normale, écart-type 13,7 points.

Cote minimum = (1 + marge) ÷ probabilité, arrondie au centième supérieur ; marge 5 % (vainqueur, écart), 10 % (joueurs).

Joueurs (section 9) : minutes attendues (10 derniers matchs) × rendement par minute, corrigé par l'adversaire (élasticité 0,72), le rythme du match et les coéquipiers absents (+35 % de la part absente). Dispersion tirée de l'historique du joueur. Chaque prévision est enregistrée avant le match et n'est jamais modifiée.

Tests : `cd engine && pytest`.
