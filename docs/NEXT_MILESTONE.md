# Prochain jalon : LAB V0.2A — données et calibration

## Ne pas démarrer par neuf agents

Le premier besoin est un historique identifié et un modèle d'exécution calibré.
Le test synthétique valide des mécanismes, pas leur réalisme sur le marché.

## Prérequis à obtenir

Choisir un fournisseur/courtier, ses instruments exacts et son historique bid/ask.
Vérifier accès, droit d'usage, périodes, spread, ticks ou granularité disponible,
coûts, tailles de contrat, pas, marges, calendrier et fuseau de chaque actif.
Aucun abonnement payant ou clé n'est demandé dans cette livraison.

Définir avant recherche le risque acceptable, la limite de drawdown, les coûts
inclus dans « net », le budget d'expériences et la règle de décision statistique.
Les plafonds de la démo ne constituent pas un accord pour le réel.

## Travail prévu

1. Adaptateur d'import avec métadonnées de provenance et contrôles de couverture.
2. Calendriers/sessions, ticks bid/ask si disponibles, latence et fills non garantis.
3. Taille de contrat, unités de cotation, pas de lot et conversions EUR correctement datées.
4. Découpage chronologique développement/validation/holdout, avec séparation explicite
   des folds, purge des observations qui se chevauchent et holdout final isolé.
5. Registre durable de chaque expérience, budgets et échecs ; seulement ensuite
   premières hypothèses de recherche en nombre borné.

## Conditions de passage

Un export réel traçable est ingéré sans correction silencieuse ; plusieurs
scénarios d'exécution sont rapprochés de calculs manuels bid/ask ; les coûts et
limites sont documentés ; le holdout ne rentre pas dans la boucle d'optimisation.
Aucune rentabilité n'est revendiquée avant ces éléments et leurs évaluations.

## Livraison distante

L'écriture via l'intégration GitHub a répondu 403 sur la création de branche.
Il faut une autorisation d'écriture valide pour cette connexion et ce dépôt avant
de publier par ce canal. Ne pas confondre cette permission avec celles d'un
workflow GitHub Actions. Ne pas changer la visibilité pour tenter de la remplacer.
