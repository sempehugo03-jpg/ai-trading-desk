# Conventions d'exécution et limites — V0.1

## Temps et données

Une bougie est l'intervalle `[timestamp_open, timestamp_open + 1 minute)`.
Sa clôture est disponible à la borne droite. Les timestamps doivent inclure un
fuseau ; ils sont normalisés en UTC. Les fenêtres d'agrégation sont ancrées en UTC.
Pas de bougie partielle ou incomplète renvoyée comme clôturée. Les heures de
session sont des constantes UTC de test, pas un calendrier complet des places
financières. Les fêtes, interruptions, changements d'heure des places et fermetures
du courtier sont à traiter explicitement dans la V0.2.

Un trou temporel arrête la simulation ; il n'est pas comblé par un faux prix.
Un écart de prix entre deux minutes consécutives est en revanche simulé.

## Prix, coûts et ordres

Les OHLC représentent le BID. L'ASK est reconstruit par `bid + spread_price`.
Le spread est supposé constant à l'intérieur de chaque minute ; il peut changer
entre minutes. Cette approximation ne remplace pas les ticks bid/ask historiques.

La stratégie voit uniquement un tuple de bougies clôturées. Un signal à la clôture
est placé pour l'ouverture suivante. Le calcul et la transmission sont supposés
sans délai supplémentaire à cette frontière ; un test de latence réaliste sera
nécessaire. Aucun fill rétroactif sur la bougie du signal.

LONG : entrée ask + slippage ; sortie au bid. SHORT : entrée bid - slippage ;
sortie à l'ask. Les sorties au marché et stops ont un slippage défavorable.
Les objectifs sont des limites remplies exactement au niveau demandé ; on ne
leur applique pas de prix moins bon que la limite. Un simple contact du prix
est supposé suffire : **probabilité de remplissage et file d'attente non modélisées**.
Un gap au-delà d'un objectif ne reçoit aucune amélioration de prix.

Si le stop est dépassé dès l'ouverture, sa sortie utilise cette ouverture,
avec slippage, pas le niveau de stop théorique. Si un objectif est atteint à
l'ouverture, cet événement connu précède le mouvement intraminute. Sinon, lorsque
les deux bornes sont touchées, le stop a priorité. L'heure exacte d'une sortie
intraminute est inconnue : le log donne la minute et l'heure de constat, pas
une seconde inventée.

Les entrées dont la géométrie stop/entrée/objectif devient invalide sont rejetées.
Une commande sans prochaine bougie reste non remplie. Une position encore ouverte
en fin de fichier est valorisée, jamais transformée en trade clôturé inventé.

## R et comptabilité

`risque initial par unité = |entrée exécutée - stop| + slippage de sortie + 2 × commission par côté`.

Le budget vaut `cash avant entrée × risk_fraction`. Les unités théoriques valent
`budget / risque par unité`. Le slippage d'entrée est déjà dans le prix d'entrée.
Les commissions d'entrée et de sortie sont chacune déduites une seule fois.
Un stop sans gap donne donc environ -1 R net dans ce modèle. Un gap peut faire pire.

Pas de conversion de devises, de lots, de pas de cotation, de contrat, de marge,
de financement ou de liquidité disponible. Ne pas envoyer les quantités à un courtier.

Paramètres par défaut **du test** : 0,25 % de budget par trade, réserve de perte
journalière 1 %, seuil de drawdown 5 %, une position à la fois. Les stops, sorties
et nouveaux signaux restent mécaniques. Le contrôle ne garantit pas qu'une perte
ne dépassera jamais le seuil lors d'un gap. Le drawdown est observé aux clôtures M1.

## Journal et reproductibilité

Chaque décision est écrite lors de son passage dans la simulation, avant la
prochaine bougie. Il s'agit d'horodatages **historiques simulés**, pas d'une preuve
que le système prédisait le marché à ces dates. Le mode est explicitement journalisé.

Le JSONL est chaîné par SHA-256, vérifié avant ajout, avec verrou d'écriture
coopératif. Ce n'est pas une base à haut débit ni un stockage immuable. Une
troncature ne peut être détectée sans un dernier hash conservé ailleurs ; une
réécriture complète avec recalcul peut tromper un vérificateur sans ancrage externe.
Le stockage prospectif exigera un service externe fiable et des contrôles d'accès.

Une même version de code, configuration et données donne les mêmes résultats
sur l'environnement testé. Cela n'implique pas une égalité bit à bit garantie
entre toutes les architectures ou versions de Python.

Les callbacks Python sont de confiance. Fournir uniquement le passé à leur interface
n'empêche pas un callback malveillant de lire d'autres fichiers/globaux. L'isolation
de code de recherche reste un prérequis avant toute exécution de code généré.

## Sources techniques consultées

- MetaQuotes, `copy_rates_range`, conventions de barres et UTC :
  https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py
- Python, dates avec/sans fuseau : https://docs.python.org/3/library/datetime.html
- Python, découverte et lancement des tests : https://docs.python.org/3/library/unittest.html
- GitHub, tests Python dans Actions : https://docs.github.com/actions/guides/building-and-testing-python

Les règles de remplissage, seuils et restrictions ci-dessus sont des choix de
modélisation propres à cette V0.1, pas des règles universelles de courtier.
