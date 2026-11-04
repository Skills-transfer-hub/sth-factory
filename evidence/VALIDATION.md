# Validation exécutée — 4 novembre 2026

Résultat final : **22 tests réussis, aucun ignoré**, avec `STH_BIN=/workspace/sth-bin/sth python3 -m unittest discover -s tests -v`. Le [journal exact](tests.txt) est conservé. Une démonstration sans STH a également réussi, ainsi qu'une démonstration finale utilisant le vrai binaire STH.

## TDD et revue

Les tests du scheduler, des patchs, des conflits, de l'annulation, des chemins et des changements humains ont été écrits avant `factory.py`. La première exécution a échoué avec `ModuleNotFoundError: No module named 'factory'`. L'implémentation a ensuite rendu la suite verte.

Une revue indépendante par un autre agent a trouvé deux lacunes corrigées et couvertes par régression : empreinte des fichiers non suivis et budget/annulation des commandes Git. Sa seconde revue a identifié l'absence de preuves lors d'une annulation pendant le clone et le besoin de suivre aussi le contenu staged ; ces points sont corrigés et testés.

Une répétition réelle a révélé une course entre deux créations simultanées de worktrees : `failed to read worktrees/multiply/commondir`. Le run historique reste disponible dans `/workspace/sth-factory-validation/run/summary.json`. Un test déterministe de cette course a été ajouté et a d'abord échoué (`test_worktree_metadata_creation_is_serialized`), puis réussi après sérialisation de la création des worktrees. Les runtimes restent parallèles.

## Chaîne STH réelle

Commande exécutée avec succès :

```sh
python3 demo.py --output /workspace/sth-factory-delivery-demo --sth /workspace/sth-bin/sth
```

Le [résumé](real-sth/summary.json) indique `succeeded`, trois tâches réussies et `source_unchanged: true`. Le [journal](real-sth/events.jsonl), les réponses STH et les patchs sont conservés dans `real-sth/`. Le contrôle final a produit `{"integration": "passed", "checks": 2}`.

La démonstration crée un dépôt jetable et un asset local via `library.save`, puis lit cet asset avec le vrai `sth bridge --stdio` dans le worktree d'une tâche de processus. Les tâches produisent `add.py` et `multiply.py`, puis un troisième worktree applique les deux patchs et vérifie leur comportement combiné. Le fichier suivi modifié humainement et le fichier humain non suivi restent présents dans le dépôt source ; aucun module généré n'y est appliqué.

Le binaire officiel **STH Alpha 0.2.44** a été téléchargé depuis le dépôt de releases public. Le SHA256 de l'archive correspond au fichier officiel `SHA256SUMS` : `66c4ab08c0b453b661386f18305565cd6497d2f4cdac18fd05b22338c3af9156`. La signature de release n'a pas été vérifiée. Les métadonnées sont dans [sth-provenance.json](sth-provenance.json). Le binaire et ses notices restent dans `/workspace/sth-bin` ; ils ne sont pas redistribués dans l'archive de la factory.

## Ce que les tests prouvent

- Validation DAG, cycles, dépendances absentes, doublons, budgets et commandes non autorisées.
- Worktrees distincts, patchs transitifs appliqués une seule fois et conflits bloquants.
- Conservation du dépôt source pendant les exécutions normales ; détection des changements suivis, staged et non suivis non ignorés.
- Timeout des tâches et des opérations Git, budget partagé du run, annulation pendant le clone, preuves de préparation et blocage des descendants.
- Arrêt d'un enfant resté dans le même groupe de processus, seuil de sortie et absence d'héritage des secrets d'environnement.
- Rejet des traversées de chemins et symlinks par le faux runtime.
- Échecs du bridge : erreur RPC, mauvaise version, mauvaise corrélation, JSON invalide et absence de binaire pour les assets.
- Contrat de l'adaptateur Codex validé avec un stub d'exécutable : argv et transmission du prompt, sans appel de modèle.
- Limite réelle des worktrees : une commande autorisée peut écrire hors du worktree, preuve explicite par marqueur temporaire.

## Limites et blocages restants

**Aucun modèle de code réel n'a été exécuté.** L'environnement expose un CLI Codex mais aucune authentification de fournisseur configurée. Le runtime de processus testé est déterministe, pas un agent LLM. Le contrat d'adaptation Codex est testé par stub uniquement. L'authentification de développement, l'isolation système et le comportement d'un vrai modèle restent à valider.

La compilation du CLI STH depuis le commit inspecté a été tentée avec Go 1.25.0. Elle reste **bloquée par un refus réseau HTTP Forbidden** lors du téléchargement de `github.com/segmentio/encoding@v0.5.4`, sur la destination redirigée `storage.googleapis.com` du proxy Go. Aucun accès direct, changement de proxy ou contournement de cette restriction n'a été utilisé. La distribution officielle déjà compilée, disponible par les destinations GitHub autorisées, a permis de terminer le test d'intégration réel. Cela ne prouve pas le build ni toute la suite de tests du commit actuel du CLI STH.

Les limites d'isolation, de quotas, d'annulation et de confiance des preuves sont détaillées dans [SECURITY.md](../SECURITY.md). Les fichiers ignorés du dépôt source ne sont pas inclus dans son empreinte. La CI livrée exécute les tests hermétiques et ignore explicitement le test réel sans `STH_BIN` ; aucun workflow distant n'a été déclenché.

Aucun dépôt distant n'a été créé, aucun push, merge, déploiement ou changement de production n'a été effectué. Le dépôt public STH cloné est resté sans modifications. La licence MIT de la factory couvre son nouveau code ; elle ne donne aucun droit sur les composants privés de STH.
