# Pronos NBA

Probabilité de victoire de chaque équipe pour les matchs NBA de la nuit, expliquée par les facteurs qui l'ont fait bouger. Usage personnel.

- `engine/` : le moteur Python (collecte, notes, prévisions, backtest, journal) — tourne sur ton PC.
- `app/` : l'app mobile (PWA installable sur l'écran d'accueil du téléphone).

## Les écrans

| Onglet | Contenu |
|---|---|
| **Ce soir** | Matchs de la nuit (heure française), probabilité de chaque équipe, cote minimum colorée, repère des bookmakers sur la barre, alerte quand l'écart dépasse 5 points de %. |
| Détail d'un match | Écart prévu, ce qui fait pencher (force, terrain, repos, déplacement, absents), absents, cotes (minimum, équilibre, bookmaker). |
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

Le dépôt contient déjà la base réelle (`data/pronos.sqlite` : 2022-23 à aujourd'hui, source ESPN) et les paramètres réglés par le backtest. `python -m pronos demo` reste disponible pour une ligue simulée.

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

- Cotes : créer une clé gratuite sur the-odds-api.com, puis `export ODDS_API_KEY=...` (bookmaker préféré : `ODDS_BOOKMAKER=betclic`).
- Sources : ESPN (calendrier, scores, box scores, cotes DraftKings) et rapport officiel des blessures NBA. stats.nba.com bloque les serveurs cloud ; ESPN non.
- Automatisation : tâche planifiée (Planificateur de tâches Windows, `cron` sur Mac/Linux), par ex. `matin` à 9 h et `soir` à 18 h.

## Le modèle (fiche de conception V1)

1. **Force de base** : attaque / défense pour 100 possessions, corrigées de la force des adversaires, demi-vie de 60 jours, a priori de saison passée (70 %, ≈ 8 matchs).
2. **Effectif du soir** : impact des absents (Out / Doubtful = 100 %, Questionable = 50 %) — calcul maison simple, à affiner.
3. **Contexte** : terrain +1,8 · veille −2,1 · 3 en 4 −0,6 · Denver/Utah +1,5 · −0,15 par 1 000 km et par heure de décalage.
4. Croisement Four Factors : retiré (n'apporte rien au backtest).
5. **Probabilité** : loi normale, écart-type 13,7 points.

Cote minimum = (1 + 5 %) ÷ probabilité, arrondie au centième supérieur. Chaque prévision est enregistrée avant le match et n'est jamais modifiée.

Tests : `cd engine && pytest`.
