# Instructions pour les prochaines contributions

## Priorité et périmètre

Travailler uniquement sur AI Trading Desk, jamais sur Fabrya.
Lire `docs/MASTER_MISSION_V1.md` et `docs/EXECUTION_ASSUMPTIONS.md`.
La cible de rendement est une hypothèse de recherche, pas un critère justifiant
une hausse automatique du risque. Ne pas annoncer un edge à partir du jeu synthétique.

## Rôles de travail prévus — pas des services actuellement lancés

**Data** : conventions de prix/heure, provenance, licence, qualité et calendrier.
**Execution** : simulateur, coûts, remplissages et rapprochement des soldes.
**Risk** : règles mécaniques indépendantes ; aucune décision textuelle ne les contourne.
**Red Team/QA** : cas adverses, tests de causalité et comparaison à des calculs manuels.
**Research/Statistics** : seulement après validation des données et du simulateur ;
registre de tous les essais, budget borné et holdout final isolé.

Ces rôles sont des responsabilités de développement. Ne pas prétendre que plusieurs
agents autonomes ont travaillé si aucun tel processus n'a été exécuté.

## Contraintes

- Aucun ordre réel, adaptateur courtier en écriture, clé API ni achat de données.
- Aucune recherche agentique automatique dans cette V0.1.
- Ne pas ouvrir/réutiliser un holdout pour corriger une stratégie après avoir vu son score.
- Les callbacks Python du LAB sont de confiance ; ils ne sont pas isolés. Ne pas exécuter
  de code arbitraire produit par un modèle avant d'avoir ajouté un environnement isolé.
- Même entrée, même configuration, même version de code : mêmes résultats et logs.
- Toute correction doit ajouter un test qui échoue avant la correction.
- Un test vert démontre le cas testé ; ne jamais le présenter comme une certification.
- La chaîne de hachage n'est pas un stockage immuable ; préserver cette distinction.
- En cas d'échec d'autorisation GitHub, arrêter les écritures et signaler l'erreur ;
  ne pas demander de secret dans la conversation, ni contourner les contrôles d'accès.

## Vérification obligatoire avant livraison

```bash
python -m unittest discover -s tests -v
python scripts/verify.py --out runs/nouveau-controle
```

Conserver le compte rendu, le nombre de tests réellement exécutés, les limitations,
les fichiers modifiés et le commit réellement obtenu, ou l'absence de commit.
