# Discovery Engine V3

V3 supprime le catalogue de familles de stratégies. Il recherche des programmes symboliques composés à partir de données du marché cible et d'autres actifs : retours, tendance, volatilité, structure, spread, heure/jour, puis opérateurs génériques `+ - * / abs min max`.

Le moteur peut donc découvrir des expressions du type :

`(self.ret1_atr - US500.ret1_atr) / (1 + abs(USDJPY.trend_10_40))`

Aucun objectif de 1 trade/jour. Le nombre de trades sert uniquement à mesurer la qualité statistique de la preuve.

Découpage V3 :
- 0–22.5% Discovery A
- 22.5–45% confirmation Discovery B
- 45–60% Research adaptatif
- 60–70% Validation adaptative
- 70–80% OOS1 non adaptatif
- 80–90% OOS2 non adaptatif
- 90–100% réserve historique

La réserve historique n'est pas revendiquée comme blind box, car les versions antérieures ont déjà touché l'historique. La vraie blind box doit être un dataset séparé ou du futur paper/live.

`--forever` enlève le plafond prédéfini du nombre de candidats : la recherche continue jusqu'à arrêt de la machine. Les seules limites deviennent CPU/RAM/temps/stockage. `--max-depth` et `--max-rules` contrôlent la complexité des programmes et peuvent être augmentés dans de futures campagnes.

V3 compte aussi le nombre total de programmes testés afin de durcir la sélection lorsque le data-mining augmente.


Pour éviter de saturer la RAM, une exécution ne charge qu'un sous-ensemble de contextes inter-marchés (`--context-width`). En mode `--forever`, ces sous-ensembles tournent à chaque vague de recherche : il n'y a pas de liste fixe de relations autorisées, seulement une contrainte physique de mémoire par vague.
