# Premier pilote STH : mesurer, corriger, vérifier

Le résultat recherché est une tâche terminée avec un patch relisible, des tests et une mesure avant/après. La Factory apporte déjà le graphe de tâches, les espaces Git séparés, la reprise et le cockpit. Un harness fournit le travail du modèle à l'intérieur de chaque tâche.

L'article [How we made claude.ai 3x faster](https://claude.dev/blog/how-we-made-claude-ai-faster/) décrit une boucle fondée sur des mesures, des changements relus puis une vérification après livraison. L'article [Software factory de CircleCI](https://circleci.com/blog/software-factory/) distingue les contrôles rapides pendant le travail et la validation indépendante avant intégration. Notre adaptation commence par une seule boucle locale, dont on conserve les preuves.

## Cas proposé, pas encore exécuté

Dans le CLI public STH, la découverte des skills d'un catalogue parcourt une liste de chemins. Le code inspecté contient `internal/scanner/flat.go` et les tests de son tri, de ses doublons et de ses exclusions. Une liste fixe de 10 000 entrées permettrait de mesurer ce parcours sans compte ni réseau.

1. Ajouter `BenchmarkFlatSkillScannerLargeTree` avec une liste déterministe et vérifier le résultat attendu hors de la boucle chronométrée.
2. Mesurer le commit de référence :
   ```sh
   go test ./internal/scanner -run '^$' -bench '^BenchmarkFlatSkillScannerLargeTree$' -benchmem -count=5
   ```
3. Confier au harness une optimisation du scanner, avec la même entrée et les mêmes résultats attendus.
4. Relancer le benchmark et les contrôles ciblés :
   ```sh
   go test ./internal/scanner ./internal/artifact ./internal/frontmatter -count=1
   ```
5. Comparer `ns/op`, `B/op` et `allocs/op`, conserver les sorties et le patch, puis utiliser la CI complète pour l'intégration.

Le benchmark ci-dessus **reste à créer**. Aucun gain n'est revendiqué. La mesure temporelle varie selon la machine et la charge ; une seule exécution plus rapide ne suffit pas. Le nombre de tâches terminées et la durée de la Factory ne prouvent pas que STH est devenu plus rapide.

Le checkout inspecté le 4 novembre 2026 était au commit `90d271a`, sur une branche de travail avec des modifications locales. Il ne constitue pas une preuve du `main` public actuel. Le pilote devra épingler son commit de départ et préparer les dépendances Go dans son environnement d'exécution ; la Factory ne reprend pas implicitement le cache ou les credentials du shell.

## Rendre le projet utilisable par d'autres

Le cœur Python et Git fonctionne avec la [démo](../README.md) et le [démarrage portable](QUICKSTART.md), sans compte IA. Le fichier `start-cockpit.command` est un raccourci propre au Mac d'installation, pas un installateur portable. Le code est MIT ; les visuels Buddy conservent les droits décrits dans `THIRD_PARTY_NOTICES.md`.

La prochaine preuve à produire est un vrai changement par un harness authentifié, suivi des mêmes tests indépendants. Le provisionnement du fournisseur reste à définir. La source est diffusée dans [Skills-transfer-hub/sth-factory](https://github.com/Skills-transfer-hub/sth-factory). La disponibilité d'un adaptateur ou une réponse d'un fournisseur simulé ne prouve pas qu'un modèle a réalisé le travail.
