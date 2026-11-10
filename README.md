# 📈 ENSIM Trade Center — trader Taha

Trader automatique pour l'ENSIM Trade Center (TP2 BI). Toutes les 30 minutes, un workflow GitHub Actions lit le marché, calcule mon signal et réécrit `decision.json` (une valeur entre -1 et +1 par produit), que le marché de l'organisateur lit à chaque tick.

**Dashboard :** https://taharachedi.github.io/ensim-trader-taharachedi/
**Fichier de décision :** https://raw.githubusercontent.com/taharachedi/ensim-trader-taharachedi/main/decision.json

## 1. Pipeline

| Étape | Fichier | Rôle |
|---|---|---|
| Acquisition | `scripts/algorithm.py` → `fetch_json` | 3 flux publics de l'organisateur : `market.json` (historique des prix), `holdings.json` (mon portefeuille), `leaderboard.json` (valeur totale de chaque trader) |
| Signal | `scripts/algorithm.py` → `analyze` / `compute_signal` | prévision de cycle, voir §2 |
| Contrôle du budget | `apply_budget_guard` (fourni) | un achat ne descend jamais sous 50 € de cash |
| Décision | `decision.json` | lu par le marché à chaque tick |
| Journal | `docs/data/decision_log.json` | décision, raison, portefeuille et classement à chaque exécution |
| Évaluation | `scripts/backtest.py` → `docs/data/backtest.json` | backtest walk-forward contre les 3 baselines |
| Automatisation | `.github/workflows/auto_decide.yml` | toutes les 30 min + déclenchement manuel |
| Restitution | `docs/index.html` | dashboard Chart.js (GitHub Pages) |

## 2. Mon signal : « prévision de cycle »

**Ce que j'ai observé dans les données.** Sur les 328 premiers ticks, chaque produit suit un cycle très régulier, avec une légère tendance de fond : environ **48 ticks pour A, 96 pour B et 24 pour C**. Un modèle sinusoïdal explique 98 % de la variance (R² = 0,98). Le code public du marché confirme cette structure : le prix est la moyenne entre une tendance cyclique et le prix précédent ajusté par la demande, plus un bruit. Les paramètres exacts sont secrets, donc je les **estime** à partir des prix observés, sans jamais les lire.

**Comment je décide, à chaque exécution et pour chaque produit :**
1. J'ajuste `prix ≈ a + b·t + c·sin(2πt/P) + d·cos(2πt/P)` par moindres carrés, en cherchant la période P (entre 12 et 129 ticks) qui colle le mieux.
2. Je prévois le prix H ticks plus tard, avec H = 30 % de la période, c'est-à-dire là où le cycle se dirige.
3. `signal = 10 × (prévision − prix) / prix × R²`, borné entre -1 et +1. Si la prévision est au-dessus du prix, j'achète ; en dessous, je vends. La taille de l'ordre est proportionnelle à l'écart attendu **et** à la confiance (R²).
4. Avec moins de 36 ticks d'historique, je ne fais rien : on ne peut pas voir de cycle.

**Pourquoi ce choix plutôt qu'une moyenne mobile ou des bandes de Bollinger ?** Une moyenne mobile réagit *après* le retournement du cycle, puisqu'elle est en retard par construction. Sur un marché aussi périodique, prévoir la phase du cycle permet d'acheter près des creux et de vendre près des sommets, au lieu de suivre le mouvement avec retard.

**Réglage des paramètres.** J'ai testé un horizon entre 15 et 35 % de la période et un gain entre 5 et 20. J'ai choisi **30 % / 10**, une valeur au milieu de la zone stable, et pas la combinaison qui donnait le meilleur chiffre (35 % / 20). Prendre le maximum d'un backtest, c'est sur-ajuster l'historique.

## 3. Structure de la décision (CM1) : exclure avant de comparer

- **Actions impossibles, exclues d'office :** vendre plus que je ne possède (le marché tronque l'ordre) ; dépenser l'argent que je n'ai pas (le budget guard réduit l'achat et garde 50 € de réserve).
- **Paris « tout ou rien », exclus pour cause de risque :** le signal n'atteint ±1 que si le mouvement prévu dépasse 10 % **avec** un cycle fiable. Quand le cycle est incertain (R² faible), les ordres deviennent automatiquement petits.
- **Seules les actions restantes sont comparées :** acheter, vendre ou attendre, selon la prévision.

## 4. Résultats (backtest walk-forward sur l'historique réel, ticks 1-328)

Règles identiques au marché : départ à 1 000 € + 1 000 unités de chaque produit. À chaque tick, le signal ne voit que le passé, et l'ordre s'exécute au prix du tick suivant. Les baselines suivent les mêmes lois que dans le code du marché (moyenne de 20 simulations).

| Trader | Valeur finale | Rendement | Volatilité / tick | Pire drawdown |
|---|---|---|---|---|
| **Mon algorithme** | **37 356** | **+113,5 %** | 0,95 % | -17,4 % |
| random_trader | 17 208 | -1,7 % | 0,88 % | -16,0 % |
| random_buyer | 17 487 | -0,1 % | 1,23 % | -18,7 % |
| random_seller | 18 060 | +3,2 % | 0,09 % | -0,5 % |
| ne rien faire | 17 461 | -0,2 % | 1,17 % | -17,8 % |

**Ce que j'ai optimisé (CM2), et ce que j'ai sacrifié :** je vise le rendement **à risque contrôlé**, pas la valeur finale seule.
- Rendement / volatilité : 119, contre 36 pour la meilleure baseline (random_seller).
- **Ce que je sacrifie :** random_seller est beaucoup plus stable (volatilité 0,09 %, drawdown -0,5 %), parce qu'il ne fait que convertir ses produits en cash. Mon algorithme garde des produits en portefeuille et subit donc leurs variations.
- Le pire drawdown (-17,4 %) a lieu vers le tick 35, **pendant la période d'attente initiale** : avant 36 ticks, l'algorithme ne fait rien et subit le marché comme « ne rien faire ». Une fois le signal actif, les baisses restent nettement plus faibles que celles de random_trader (voir le graphique de drawdown).

## 5. Dashboard : choix des graphiques (qui, quelle décision, pourquoi ce type)

| Visuel | Pour qui | Décision | Pourquoi ce type |
|---|---|---|---|
| Cartes de KPI | moi, à chaque exécution | « est-ce que je bats les baselines ? » | un chiffre + une comparaison, lisible en 5 secondes |
| Courbes de valeur dans le temps (moi + 3 baselines) | moi / l'enseignant | garder ou changer la stratégie | des courbes superposées montrent **quand** l'écart se crée, pas seulement le score final |
| Classement réel en direct | moi | où j'en suis vraiment | un tableau, car on compare des montants exacts à un instant précis |
| Drawdown dans le temps (aire) | moi | « la stratégie prend-elle trop de risque ? » | l'aire sous zéro rend la profondeur et la durée des pertes visibles |
| Nuage rendement / volatilité | moi / l'enseignant | arbitrage rendement / risque | une position sur 2 axes, c'est exactement la question multi-objectif |
| Prix + prévision par produit | moi | comprendre **pourquoi** j'achète ou je vends | on voit la phase du cycle et le point visé |
| Journal des décisions | moi / l'enseignant | expliquer la trajectoire | un tableau chronologique, avec une raison par ligne |

## 6. Limites (honnêtement)

- **Enregistrement :** le marché ne lit que les traders inscrits par l'organisateur dans `traders/registry.json`. J'ai envoyé mon URL le 10/11/2026. En attendant, le script tourne avec un portefeuille par défaut et le dashboard le signale.
- **Mon propre impact sur les prix est ignoré dans le backtest :** la demande moyenne de tous les traders fait bouger le prix. Comme je suis 1 trader sur environ 6, acheter fait un peu monter le prix contre moi. Les vrais résultats seront donc probablement inférieurs au backtest.
- **Changement de régime :** si l'organisateur modifie les paramètres secrets (période, amplitude), le R² baissera et le signal se réduira de lui-même. Mais l'algorithme mettra quelques cycles à réapprendre.
- **Ticks irréguliers :** les ticks n'arrivent pas toutes les heures (328 ticks en 2 mois). Mon workflow tourne toutes les 30 minutes, mais le marché ne lit que ma dernière décision au moment du tick.
- **Cash limité :** avec 1 000 € au départ, les achats simultanés sur A, B et C ne peuvent pas tous être servis. Le marché exécute dans l'ordre A, B, C, donc C reçoit ce qui reste.

## 7. Mode manuel

`decision.json` peut toujours être modifié à la main depuis GitHub. C'est la stratégie « valeur constante » du sujet. Je garde l'automatique, parce que les cycles de C (24 ticks) sont trop rapides pour être suivis à la main.
