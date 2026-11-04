# Validation v2 — 4 novembre 2026

Code source exécuté : `9be2099643f18f135f0ab586d0bc2864c6ba0e23`, branche locale `factory/v2`.

**89 tests réussis, aucun ignoré** avec le vrai CLI STH et les tests de conteneurs activés. Le journal exact est conservé dans [tests.txt](tests.txt).

```sh
STH_BIN=/workspace/sth-bin/sth \
STH_TEST_CONTAINER_IMAGE=python@sha256:e6dae589c1c05976188fd3bd019afd091445fc533ed2ea29001beddc7368a9c8 \
python3 -m unittest discover -s tests -v
```

Lots développés en TDD par cinq agents, intégrés par le superviseur et relus indépendamment :

- contrat JSON neutre et adaptateurs commande/Codex/Claude ;
- isolation Docker optionnelle, sans montage de credentials, miroir, journaux ou socket dans le runtime ;
- initialisation et diagnostic de projets Python et Node ;
- suivi/revue et cockpit HTTP local en lecture seule ;
- préparation GitHub et création de brouillon uniquement sur demande distincte ;
- état durable SQLite, verrou exclusif, reprise contrôlée et réessais explicites bornés.

Les tests ont d'abord échoué sur les modules absents, puis passé après implémentation. La revue a aussi identifié et fait corriger l'absence de stdin interactif Docker, la gestion d'un échec SQLite après Popen et la récupération d'un archivage de tentative partiellement effectué. Ces cas sont couverts par régression.

## Exécution réelle

- STH Alpha 0.2.44 : bridge, lecture d'asset local, travail humain conservé et contrôle de patchs combinés.
- Python et Node : deux implémentations distinctes du même contrat, huit scénarios de cycle de vie. Ce sont des fixtures déterministes, pas deux modèles IA.
- Docker : trois tests réels de frontière, transmission stdin JSON et arrêt après mort du client ; une quatrième intégration couvre `Factory.run`, deux tâches isolées, collecte et contrôle du code combiné.
- Reprise : véritable SIGKILL du superviseur, refus de reprise tant qu'un groupe de processus est actif, absence de replay d'une tâche terminée et retry explicite d'une tâche interrompue.
- Adoption : suites Python et Node réellement lancées sans STH, suite vide refusée, configuration sans écrasement de fichiers humains.
- Cockpit : vrais tests HTTP et Chromium. Une fixture XSS reste du texte. Les nouvelles captures montrent aussi le cockpit réel sur un run de conteneurs réussi, avec patch et logs.
- GitHub : préparation purement locale validée et contrôles de création testés par mocks ; aucun appel de création réel, push, merge, publication ou déploiement.

## Limites et statut exact

Le CLI Codex de l'hôte est installé et indique une session ChatGPT ouverte. Le probe réalisé avec le HOME éphémère et l'environnement épuré du runtime répond toutefois `Not logged in` (code 1). Aucun credential n'a été créé, copié ou transmis. L'authentification de développement dans le runtime n'est donc pas configurée et **aucun modèle réel n'a été appelé**. Claude n'est pas installé ; son adaptateur est testé par stub, ses options ont été vérifiées dans sa documentation officielle.

Le backend conteneur impose actuellement `network=none` : une connexion à un fournisseur distant reste non implémentée. Les mesures facultatives de consommation sont déclaratives, sans plafond financier imposé au fournisseur. Le daemon disponible est rootful, le runtime nonroot ; le noyau est partagé et le snapshot n'a aucun quota disque strict. Les limites sont détaillées dans [ISOLATION](../../docs/ISOLATION.md) et [DURABILITY](../../docs/DURABILITY.md).

L'exécution exactement une fois d'effets externes arbitraires n'est pas garantie. Les réessais sont manuels et les preuves restent modifiables par l'utilisateur hôte. L'état n'est pas une queue distribuée. La création GitHub distante et son authentification restent non validées ; la correspondance d'une branche distante avec le patch local exige une revue séparée.

Le build source du CLI STH précédemment refusé sur `storage.googleapis.com` n'a pas été retenté ni contourné. Les tests utilisent le binaire officiel vérifié, sans dépendance au backend privé.

Les fichiers PDF, captures, vidéos et scripts de reproduction sont préparés séparément dans `/workspace/sth-factory-v2-report`. Leur disponibilité native ChatGPT est vérifiée après enregistrement ; leur transmission RCS n'est pas supposée.
