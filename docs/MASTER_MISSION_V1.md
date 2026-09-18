# MASTER MISSION — AI TRADING DESK V1

## Objectif accepté

Construire un processus : données → hypothèses → tests → contradiction → sélection
→ portefeuille → contrôle du risque → simulation → mesure → recherche.

Cible expérimentale : environ **+10 % net/mois**, aussi régulier que possible,
avec **au moins une opportunité par jour de marché en moyenne au niveau du portefeuille**.
La cible n'est pas une promesse ; NO TRADE reste autorisé. Le système doit pouvoir
conclure « objectif non démontré », sans masquer les pertes ni augmenter le risque
pour afficher le rendement demandé.

## Univers et recherche

Univers final initial : XAUUSD, NAS100, US500, EURUSD et GBPUSD. Les symboles exacts,
contrats, horaires et conditions dépendent du fournisseur à valider. Le premier
LAB utilise un seul instrument synthétique pour vérifier le logiciel.

Style intraday/scalping, contexte multi-horizons possible. Aucune famille de
stratégies n'est imposée ni présumée rentable. Plusieurs logiques complémentaires
peuvent former un portefeuille, avec une cible de 3 à 5 stratégies au maximum
seulement si elles apportent un avantage prouvé.

## Architecture cible

L'orchestrateur coordonne Régime, Macro, Structure, Stratégiste, Timing, Red Team,
Risk Manager et Portfolio. Il ne décide pas par un vote entre textes d'agents.
Les chiffres viennent des données. Le Risk Manager est mécanique et possède un
veto non contournable. Les rôles peuvent rester de simples modules lorsque cela
suffit ; multiplier les appels de modèles n'est pas un objectif.

Research et Statistics fonctionnent dans un circuit séparé. Une modification
crée une nouvelle version. Les pertes récentes n'autorisent pas à changer librement
la stratégie active. Aucune stratégie nouvelle n'est autorisée en live avant validation.

## Protocole cible

1. Définir provenance, conventions, licence, coûts, budget d'expériences et limites de risque.
2. Rechercher sur les données de développement ; conserver tous les essais, y compris les rejets.
3. Valider chronologiquement, faire du walk-forward et des stress tests de coûts,
   paramètres, régimes, exécution et dépendance aux trades exceptionnels.
4. Comparer au contrôle mécanique simple et tenir compte des essais multiples.
5. Utiliser un holdout final gelé et tenu à l'écart de la boucle de recherche.
6. Paper trading prospectif : décisions enregistrées avant les résultats, sans sélection
   discrétionnaire, seuil d'observations et règle d'arrêt fixés avant de regarder les résultats.
7. Envisager seulement ensuite une exposition réelle limitée, soumise à autorisation
   explicite. Aucune étape de ce lot ne permet le réel.

La préparation d'un portefeuille virtuel de 80 000 EUR appartient au paper trading,
après validation des conversions, tailles de contrat, marges et coûts. La V0.1
ne prétend pas le reproduire.

## Mesure et réussite

Mesurer espérance nette, distribution des rendements mensuels, fréquence, drawdown,
profit factor, R, coûts, régimes, actifs, sessions et divergences historique/hors
échantillon/paper. Rapporter les incertitudes. Ni le win rate ni un score de confiance
inventé par un modèle ne sont une probabilité de gain mesurée.

Une stratégie doit rester positive après coûts, être cohérente hors échantillon,
résister aux stress raisonnables et respecter le budget de risque accepté.
Les seuils précis, le budget de recherche et le drawdown acceptable pour la phase
suivante restent à fixer avant cette phase. Les paramètres du contrôle synthétique
ne remplacent pas cette décision.

## État actuel

LAB V0.1 : prototype hors ligne, tests logiciels et démonstration synthétique.
Aucune preuve de rentabilité ; aucune recherche sur données réelles ; aucun service
24/5 ; aucun agent de trading autonome déployé. Publication GitHub non effectuée
lors de cette livraison en raison d'un refus d'écriture 403.
