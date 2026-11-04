# Validation de l’atelier — 4 novembre 2026

Le cockpit possède un poste et un Buddy 3D officiel par tâche réelle. Il n’exige aucun fournisseur d’agent. Le code reste MIT ; les assets Buddy sont inchangés, autorisés pour cette livraison et conservent leurs droits réservés.

## Résultats exécutés

- 107 tests unitaires et d’intégration réussis, sans skip, avec le CLI STH Alpha 0.2.44 local et le conteneur Python épinglé déjà disponible.
- Un nouveau dépôt Git de démonstration indépendant de STH ; 31 tâches réellement planifiées, 3 workers/processus Python simultanés.
- Résultat attendu : 29 succès, 1 échec volontaire (code 7), 1 tâche bloquée par sa dépendance échouée. Le run échoue conformément au scénario, ses 29 postes réussis restent en succès.
- Avant sélection, zéro Buddy. Toutes les poses réellement décodées. Animation observée des trois tâches en parallèle.
- Pagination 24 + 7 postes, filtres, recherche, sélection des logs réels, ancienne réponse de revue ignorée, focus préservé à l’actualisation.
- Pause et préférence de réduction des mouvements sans arrêter les mises à jour. Suspension des cartes hors écran. Aucun débordement horizontal à 320 et 390 px ; aucun pageerror Chromium.
- Quatre tests de régression supplémentaires du lecteur : décodage différé, aller-retour d’onglet, destruction/listeners/RAF et états pendant la pause.
- Test de projection pur avec 1 000 tâches : maximum 24 cartes par page, 42 pages. Cela ne représente pas 1 000 processus exécutés.
- Le dépôt source de démonstration est inchangé après le run.

## Reproduction

```sh
STH_BIN=/absolute/path/sth \
STH_TEST_CONTAINER_IMAGE=python@sha256:e6dae589c1c05976188fd3bd019afd091445fc533ed2ea29001beddc7368a9c8 \
python3 -m unittest discover -s tests -v
python3 examples/validate_factory_floor.py --output /tmp/new-factory-floor-proof
```

Le second scénario requiert Playwright et Chromium pour la validation seulement. Choisir un dossier de sortie inexistant. Il crée des captures PNG, une vidéo WebM authentique, checks.json et les traces des tâches. L’exemple contient les gates du harness et les paramètres exacts ; aucune API n’est simulée pour fabriquer les états. Seule une réponse HTTP de revue est retardée afin de vérifier la protection contre les courses.

## Limites explicites

Les workers du nouveau scénario sont déterministes, pas des modèles IA. Les adaptateurs CLI existants ne constituent pas une preuve d’appel à un agent réel authentifié. Aucun accès fournisseur n’a été ajouté ni secret copié. La validation d’un vrai fournisseur dans l’isolation choisie reste à faire avec un accès autorisé.

Le cockpit est local et en lecture seule. Il ne lance aucune tâche depuis le navigateur. Le MVP exécute les tâches via la CLI ; ni PR, ni merge, ni publication, ni déploiement n’ont été réalisés. Le scénario visuel utilise des commandes locales de confiance. Les tests de conteneur sont distincts ; les worktrees ne sont jamais une sandbox de sécurité. La capacité HTTP protège l’API, pas un hôte compromis ou des preuves modifiées par le même utilisateur.

Les captures et la vidéo montrent le vrai navigateur pendant l’exécution. MP4 dérivé du WebM sans accélération ni événement ajouté. Le PDF illustré résume les preuves. Leur livraison dans ChatGPT ne prouve pas une transmission RCS/SMS.
