# AI Trading Desk — livraison LAB V0.1

## Résultat vérifié

Le laboratoire a été construit et exécuté localement. **79 tests exécutés,
0 échec, 0 erreur, 0 test ignoré**, sous Python 3.13.5.

Deux exécutions complètes de la démonstration synthétique ont été comparées.
Les fichiers de données, rapports, trades, valorisations et journaux sont identiques
octet par octet entre les deux exécutions.

Chaque exécution utilise **720 bougies M1 artificielles** et
produit **784 événements de journal**. Ce volume est
un test technique, pas un échantillon validant une stratégie ou un rendement mensuel.

## Contenu du lot

Import CSV M1 avec contrôles de qualité et fuseau ; agrégation de fenêtres M5/M15/H1/H4
complètes et clôturées ; simulateur LONG/SHORT avec ordres à l'ouverture suivante ;
bid/ask, spread, slippage et commissions ; traitement conservateur des cas ambigus ;
gaps de prix, rejets d'entrée, limites de durée et fin de session ; contrôle de risque
mécanique ; journal vérifiable ; métriques ; tests ; documentation et workflow CI préparé.

## Vérifications importantes

Les scénarios couvrent les prix non finis, OHLC invalides, doublons, données manquantes,
fuseaux et changement d'heure, absence de bougie agrégée partielle, exclusion de
valeurs futures, reproductibilité, absence d'entrée rétroactive, LONG/SHORT bid/ask,
stop et objectif dans la même minute, stop au prix d'un gap, calcul des coûts une seule
fois, rapprochement du solde, NO TRADE, veto de spread/risque, une position maximum,
valorisation des positions encore ouvertes, fermeture à minuit même en session 24 heures,
altération du journal et préservation des expériences existantes.

Les tests complets sont dans `validation/tests.txt`. Le résultat machine est dans
`validation/verification.json`. Ils prouvent ces cas testés, pas l'absence de toute erreur.

## Publication GitHub : non effectuée

Dépôt lu : `sempehugo03-jpg/ai-trading-desk`.
Commit de base lu : `b56a75f5607357fca5618cf5a2f66b697cdf3a89`.
Le dépôt contenait uniquement son README lors du contrôle.

Tentative de création de branche `lab/v0.1` :
`403 Resource not accessible by integration`.

**Aucune branche ni aucun commit n'ont été créés par cette livraison.** Les
écritures n'ont pas été poursuivies après ce refus. Le workflow GitHub Actions est
fourni, mais n'a pas été exécuté à distance. Seul Python 3.13.5 a été testé ici.

## Rentabilité et suite

**Aucune stratégie rentable démontrée. Aucun historique réel téléchargé. Aucun
agent autonome ou service 24/5 lancé. Aucun ordre réel ni compte courtier connecté.**

Le contrôleur synthétique n'a pas été optimisé pour afficher +10 %. Ses performances
ne constituent pas une estimation de ce qui arriverait sur le marché.
La cible du projet reste environ +10 % net/mois et au moins une opportunité quotidienne
en moyenne pour le portefeuille, sans trade forcé ni dépassement caché du risque.

La prochaine phase est l'intégration d'un historique réel traçable, des conventions
du fournisseur, des calendriers, des coûts et d'un protocole hors échantillon.
Les limites de risque et le budget de recherche doivent être définis avant recherche.
La publication par l'intégration GitHub exige d'abord une autorisation d'écriture valide.

## Reproduire

Depuis le dossier extrait :

```bash
python -m unittest discover -s tests -v
python scripts/verify.py --out runs/mon-controle-v01
```

Aucune clé API ni dépendance externe n'est nécessaire. Le dossier de sortie doit
être nouveau. Aucun processus ne continue à tourner après la commande.

## Empreintes du contrôle livré

- Code des modules : `3c7217cdec390104b279f20ee46c944a02f15527c76c02f0d3a4171d87603766`
- Données normalisées : `5ddb907173491c46c4e443db9cc6db8b1ba10bccc735952b428a60f799d6735e`
- Résultat : `47a4e5d35195aba4eab4b37198ca5dc5617cc4330798e5774407cd606c16dca2`
- Dernier hash du journal : `68fc4bcb2302690e434e30f39a64198e557fff1f4408f43bba460e501d3e8c82`

Le fichier `MANIFEST.sha256` liste les empreintes des fichiers de l'archive, hors
le manifeste lui-même. Le journal n'est pas un stockage immuable : un ancrage externe
reste nécessaire pour détecter certaines réécritures ou troncatures.
