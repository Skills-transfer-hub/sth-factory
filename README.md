# STH Factory — version locale v2

Orchestrateur open source indépendant des agents et fournisseurs (Python 3.12+, Git, Linux/POSIX), sous MIT. Il planifie des tâches, conserve leur état SQLite, produit des patchs et propose un cockpit local de revue. Aucun agent, modèle, SDK fournisseur ou backend privé STH Code n'est obligatoire. Aucun merge, push ou déploiement automatique.

Buddy 3D accompagne les états réellement observés du run sélectionné, avec animations officielles, pause et préférence de réduction des mouvements. **Le code est MIT ; les visuels, animations et modèle Buddy restent à droits réservés**, copiés et distribués avec cette factory sur autorisation spécifique de STH. Voir [provenance et droits](docs/BUDDY-3D.md) et `THIRD_PARTY_NOTICES.md`. Cette autorisation n'accorde pas une licence générale sur la mascotte.

Le cœur échange un contrat JSON versionné avec des processus configurés par l'opérateur. Des adaptateurs facultatifs de commande générique, Codex et Claude sont fournis, sans préférence fournisseur. La conformité est éprouvée avec deux implémentations distinctes Python et Node. Ce sont des processus déterministes ; aucun modèle réel n'a été validé. STH fournit seulement des assets via son bridge optionnel.

La v2 ajoute l'isolation Docker optionnelle réellement testée, une reprise durable avec réessais explicites et bornés, `init`/`doctor` pour Python et Node, `status`/`review`, un cockpit local en lecture seule et la préparation de PR. La création d'un brouillon est une opération distincte, uniquement sur demande, sans push.

Validation : [89 tests réussis avec STH et Docker réels](evidence/v2/VALIDATION.md). Les résultats du MVP v1 sont conservés séparément dans `evidence/VALIDATION.md`.

```sh
python3 factory.py init --destination /tmp/project-config --template python
python3 factory.py doctor --repo /chemin/projet --policy /tmp/project-config/operator-policy.json
python3 factory.py run --repo /chemin/projet --output /tmp/factory-runs/run-1 \
  --plan /tmp/project-config/plan.json --policy /tmp/project-config/operator-policy.json
python3 factory.py status --run-dir /tmp/factory-runs/run-1
python3 factory.py review --run-dir /tmp/factory-runs/run-1
python3 factory.py serve --runs-root /tmp/factory-runs --port 8765
```

Le cockpit reste local : le lancer n'est pas un déploiement. Son URL contient une capacité temporaire à ne pas publier. Documentation : [QUICKSTART](docs/QUICKSTART.md), [RUNTIME-CONTRACT](docs/RUNTIME-CONTRACT.md), [ISOLATION](docs/ISOLATION.md), [DURABILITY](docs/DURABILITY.md), [COCKPIT](docs/COCKPIT.md), [GITHUB](docs/GITHUB.md).

```sh
python3 -m unittest discover -s tests -v
python3 demo.py --output /tmp/sth-factory-demo
# Avec un CLI STH installé et vérifié :
STH_BIN=/absolute/path/sth python3 -m unittest discover -s tests -v
python3 demo.py --output /tmp/sth-factory-real-demo --sth /absolute/path/sth
```

Utiliser un nouveau répertoire de sortie à chaque exécution. La démonstration crée un dépôt jetable, préserve des modifications humaines, lance deux tâches indépendantes, réunit leurs patchs dans une troisième et vérifie un calcul utilisant les deux modules produits. Avec `--sth`, un asset de bibliothèque est créé **dans le dépôt jetable**, puis lu par le vrai bridge et transmis au processus déterministe. Sans `--sth`, ce chemin STH est explicitement absent.

Une exécution réelle de cette démonstration a réussi avec **STH Alpha 0.2.44**, pas seulement avec un mock. Les [preuves et limites](evidence/VALIDATION.md) distinguent cette validation de l'exécution d'un modèle.

Pour lancer un plan déjà préparé :

```sh
python3 factory.py plan --plan plan.json --policy operator-policy.json
python3 factory.py run --plan plan.json --policy operator-policy.json \
  --repo /absolute/path/repository --output /absolute/path/new-run \
  --sth /absolute/path/sth --cancel-file /absolute/path/cancel-marker
```

Le dossier de sortie doit être hors du dépôt source. Le plan et la politique produits par `demo.py` sont des exemples exécutables : `run/plan.json` et `run/policy.json`. La politique doit être relue et conservée par l'opérateur, hors du contrôle des agents ; elle autorise des argv complets avec exécutables absolus. Le plan référence leurs noms, jamais une commande shell. Les champs `prompt`, les assets et le dépôt sont des données non fiables. Leur contenu ne donne aucun droit.

La politique contrôle `workers`, `max_tasks`, `max_attempts` (1 à 3), `task_timeout`, `run_timeout`, `max_output_bytes`, `commands` et le backend `isolation`. Les réessais demandent `resume --retry-task ID` ; ils ne sont jamais déclenchés par les sorties des agents. Le budget global du run n'est pas remis à zéro lors d'une reprise. Les consommations facultatives sont déclaratives : aucun budget financier fournisseur n'est imposé. Les modifications d'une tentative sont archivées avant un nouvel essai.

Le CLI Codex de l'hôte indique une session ChatGPT existante, mais le runtime reçoit un HOME neuf et n'en hérite pas : le probe dans cet environnement répond `Not logged in`. Aucun credential n'est créé ou copié. L'authentification de développement dans le runtime et l'accès d'un agent isolé à un modèle distant restent à configurer ; le backend Docker impose actuellement `network=none`.

Voir [l'architecture et les contrats](ARCHITECTURE.md) et [les frontières de sécurité](SECURITY.md) avant d'ajouter un runtime. **Un worktree n'est pas une sandbox de sécurité.** Les tests déterministes sont exécutables sur la machine locale ; un agent traitant du code hostile exige une isolation système indépendante.

### Atelier visuel : une tâche, un Buddy

Le cockpit affiche un poste par tâche réelle, y compris les tâches parallèles. Les Buddies au travail s’animent avec les rendus 3D officiels ; attente, succès et erreur ont une pose propre. Les états individuels, dépendances, logs et patchs viennent du moteur. Recherche, filtres et pagination de 24 postes limitent le rendu des gros lots. Le code reste agnostique aux agents, STH est facultatif ; les visuels Buddy conservent leurs droits réservés. Voir [le contrat visuel](docs/FACTORY-VIEW.md) et [la provenance](docs/BUDDY-3D.md).

Validation visuelle facultative (Playwright + Chromium), 31 tâches et 3 processus simultanés :

```sh
python3 examples/validate_factory_floor.py --output /tmp/factory-floor-proof
```

Ce scénario utilise des processus déterministes, aucun modèle IA. Le cockpit reste local et en lecture seule.
