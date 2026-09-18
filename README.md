# AI Trading Desk — LAB V0.2

**Laboratoire Python hors ligne. Prototype technique testé sur données synthétiques.**

Ce lot construit le socle de simulation. Il ne contient ni connexion à un courtier,
ni ordres réels, ni équipe autonome de modèles, ni stratégie validée rentable.

La cible du projet reste **environ +10 % net/mois et au moins une opportunité par
jour de marché en moyenne pour le portefeuille**. Elle n'est pas démontrée. Aucun
trade ne doit être forcé pour l'atteindre.

## Démarrage

Depuis le dossier extrait, avec Python 3.11 ou supérieur :

```bash
python -m unittest discover -s tests -v
python -m trading_lab.demo --out runs/premier-test
```

Aucune bibliothèque externe ni clé API n'est nécessaire pour ces commandes.
Les calculs utilisent seulement la bibliothèque standard. L'installation en
paquet est facultative : `python -m pip install -e .`.

Le dossier de sortie doit être nouveau : les expériences existantes ne sont pas
écrasées. Une vérification complète est disponible :

```bash
python scripts/verify.py --out runs/verification-v01
```

## Ce qui est implémenté

- Import CSV de bougies **M1 bid** avec fuseau horaire explicite et spread en unités de prix.
- Rejet des NaN, infinis, prix invalides, doublons, désordre et minutes manquantes.
- Agrégation M5, M15, H1 et H4 en UTC, uniquement sur fenêtres complètes et clôturées.
- Stratégie de contrôle déterministe ; entrée au plus tôt à l'ouverture suivant la décision.
- Simulation LONG/SHORT : bid/ask, spread, slippage, commissions, stops, objectifs,
  écarts de prix à l'ouverture, durée maximale et clôture horaire de session.
- Veto de risque mécanique : une position au maximum, risque par trade, spread,
  réserve de perte journalière, drawdown et arrêt des nouvelles entrées.
- Journal JSONL à chaîne de hachage et vérification, incluant les NO TRADE.
- Statistiques nettes en R et en devise de cotation ; rapprochement de trésorerie,
  valorisation des positions ouvertes et absence de faux remplissage en fin de fichier.
- Tests, démonstration reproductible et workflow GitHub Actions préparé.

## Ce qui n'est PAS implémenté

Pas de données réelles téléchargées ; pas de paper trading connecté ; pas de
backtest sur plusieurs années ; pas de sélection de stratégies ; pas de validation
hors échantillon, walk-forward ou Monte-Carlo ; pas d'orchestration d'agents ; pas
de portefeuille multi-actifs ; pas de marges, tailles de lots de courtier ou
conversion EUR ; pas d'exécution réelle. Aucun processus ne reste en service
après la fin de la commande.

Les bornes de risque présentes sont **des paramètres de test**, pas une validation
du risque à engager sur un compte. Un gap peut dépasser un stop ou une limite.

## Format CSV

```csv
timestamp_open,bid_open,bid_high,bid_low,bid_close,spread_price
2025-01-06T12:00:00+00:00,2500.0,2501.0,2499.5,2500.5,0.08
2025-01-06T12:01:00+00:00,2500.5,2501.2,2500.1,2500.8,0.10
```

Les données d'exemple ci-dessus sont inventées. `timestamp_open` désigne le début
de la minute ; sa clôture n'est disponible qu'une minute plus tard. Les prix sont
BID, jamais un mélange bid/ask/mid. `spread_price` n'est ni un nombre de pips ni
une valeur brute en points. Les conventions du fournisseur doivent être vérifiées
avant toute conversion. Les séries sont contiguës dans cette V0.1 : les fermetures
et trous de cotation nécessitent un calendrier explicite dans la V0.2.

```bash
python -m trading_lab.demo --csv data/mon-export-normalise.csv --out runs/test-csv-001
```

Cette commande applique uniquement la stratégie de contrôle : elle ne lance
aucune recherche automatique. Un CSV fourni n'est pas déclaré authentique par
le logiciel. Son utilisation/licence reste à vérifier.

## Livrables d'une exécution

`report.json` contient les hypothèses et statistiques, l'empreinte des données,
celle du code, celle du résultat, ainsi que l'état du journal. `trades.json`,
`equity.json` et `journal.jsonl` conservent les détails. Pour l'exemple intégré,
`synthetic_m1.csv` est aussi écrit.

Les montants sont exprimés dans la devise de cotation du modèle ; ils ne
représentent pas un compte de 80 000 EUR. Les quantités sont des unités théoriques
de sous-jacent, **pas des lots envoyables à MT5**.

## Limites à lire avant d'interpréter les chiffres

Le journal est vérifiable, pas inviolable. Une copie externe du dernier hash
est nécessaire pour détecter une troncature ; un stockage externe de confiance
sera nécessaire pour des preuves en temps réel.

Les bougies M1 ne donnent pas le trajet exact des prix, la file d'attente d'un
ordre ni la latence réelle. Un stop a priorité lorsque stop et objectif sont
touchés dans la même minute et que leur ordre est inconnu. Cette règle ne
transforme pas les bougies en ticks. Le drawdown publié est échantillonné aux
clôtures M1, pas un maximum intraminute.

Voir [les hypothèses](docs/EXECUTION_ASSUMPTIONS.md), [la mission](docs/MASTER_MISSION_V1.md)
et [le prochain jalon](docs/NEXT_MILESTONE.md).

## État de publication

Dépôt cible : `sempehugo03-jpg/ai-trading-desk`.
Base lue : `b56a75f5607357fca5618cf5a2f66b697cdf3a89` (README seulement).
Lors de cette livraison, la création de `lab/v0.1` a été refusée par GitHub :
`403 Resource not accessible by integration`. Ce lot est livré en archive
locale ; aucun commit distant ni succès de CI distante n'est revendiqué.

Ne jamais ajouter de clés, identifiants courtier ou données privées dans le dépôt.
Le dépôt cible était public lors de sa dernière lecture.


## LAB V0.2 — real data gate

V0.2 adds the five-asset research universe, exact BID/ASK M1 support, chronological holdouts, walk-forward windows, cost stress tests and an append-only experiment registry.

Smoke-test real data:

```bash
npm install
npm run data:smoke
python scripts/check_real_data.py
```

See `docs/DATA_SOURCE_V02.md` and `docs/LAB_V02.md`.
