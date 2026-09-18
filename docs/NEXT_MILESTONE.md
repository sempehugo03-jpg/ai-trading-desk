# Prochain jalon : Research Desk V0.1

## Condition préalable

Ne pas lancer les agents de recherche avant que le smoke test données réelles V0.2 passe sur les cinq instruments et que le split chronologique initial soit figé.

## Première mission du Research Desk

1. Générer des hypothèses explicites et testables, sans accès au holdout final.
2. Transformer chaque hypothèse en stratégie exécutable versionnée.
3. Tester IS puis validation, avec registre exhaustif des essais.
4. Appliquer walk-forward et stress spread/slippage.
5. Rejeter les stratégies instables avant toute lecture du holdout final.
6. Construire seulement ensuite un portefeuille de 3 à 5 stratégies complémentaires.

## North Star

La cible de recherche reste environ 10 % net/mois et au moins une opportunité quotidienne en moyenne au niveau du portefeuille. Elle ne permet jamais de contourner les règles de robustesse, drawdown, coûts, OOS ou Risk Manager.

## Interdictions

- aucun capital réel ;
- aucune optimisation sur le holdout final ;
- aucune suppression rétroactive d’un essai perdant ;
- aucune modification live d’une stratégie après quelques pertes ;
- aucune affirmation de performance avant données réelles, OOS et paper live.
