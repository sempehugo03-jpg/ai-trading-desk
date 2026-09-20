# Discovery Engine V2 — le marché d'abord

V2 supprime le catalogue fermé de familles de stratégies.

Le moteur mesure le marché, apprend des seuils sur les quantiles réellement observés, vérifie que le signal garde le même sens sur une deuxième période chronologique, puis fige ce motif avant validation et OOS.

Il n'existe aucun champ `family` dans `StrategyV2`.

## Gates progressifs

- PASS
- PROMISING
- UNCERTAIN
- REJECTED

Une idée positive mais rare est donc conservée en UNCERTAIN au lieu d'être détruite immédiatement.

## Chronologie par défaut

- 0–20 % : découverte A
- 20–40 % : confirmation de découverte B
- 40–60 % : recherche adaptative
- 60–75 % : validation
- 75–90 % : OOS protégé
- 90–100 % : volontairement inutilisé par V2

L'OOS ne revient jamais dans la mémoire adaptative.

Le dernier 10 % n'est pas présenté comme une blind box vierge, car V0/V1 ont déjà exploré cet historique. La vraie blind box devra être un échantillon séparé ou du futur paper/live.

## Objectif

Trouver plusieurs petits edges indépendants qui pourront ensuite être assemblés en portefeuille vers la cible ~10 % net/mois, >=1 trade/jour, drawdown maîtrisé et contraintes prop-firm si les données le permettent.
