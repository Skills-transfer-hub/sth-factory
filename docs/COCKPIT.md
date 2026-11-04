# Cockpit local, suivi et revue

Le cockpit est une interface fonctionnelle en lecture seule. Il affiche les exécutions d'un dossier choisi par l'opérateur, les tâches et leurs dépendances, les états, les derniers événements, les logs et les patchs. Il n'exécute aucun contenu lu et ne possède aucune route de lancement, merge, publication, déploiement ou création de PR.

```sh
python3 cockpit.py --runs-root /absolute/path/factory-runs --port 8765
```

Chaque enfant direct de `--runs-root` peut être une exécution : `factory-runs/run-one/summary.json`, `factory-runs/run-one/plan.json`, etc. Le serveur imprime un lien local contenant une capacité aléatoire après `#`. Ouvrir ce lien complet ; la capacité reste en mémoire de la page et est retirée de la barre d'adresse. Recharger sans le lien complet demande de rouvrir le lien initial. Ne pas partager le lien ni exposer le port par un tunnel sans contrôle d'accès supplémentaire.

Le serveur lie uniquement `127.0.0.1`. Les API exigent la capacité dans `Authorization: Bearer ...` ; le shell HTML public ne contient aucune donnée de run. Les en-têtes Host, Origin et Sec-Fetch-Site sont vérifiés. Pas de CORS, de ressources tierces ni de scripts embarqués ; CSP, `no-store`, `nosniff` et protection contre l'encadrement sont activés. Toutes les données de runs sont insérées par `textContent`, jamais comme HTML. Les identifiants, traversées et symlinks sont refusés ; les fichiers non réguliers sont refusés sans blocage sur les FIFO. Les fichiers sont ouverts relativement à des descripteurs de répertoires avec `O_NOFOLLOW`.

`monitoring.status(run_dir)` lit le résumé, le plan et une fin bornée du journal. Les événements permettent un suivi pendant l'exécution, avant le résumé final. Un nouveau `run_started` ou `run_resumed` après un résumé ancien prend priorité sur celui-ci. Les états inconnus sont affichés comme données. Une dernière ligne d'événement partielle est ignorée avec avertissement. Le module ne crée pas de base SQLite et ne modifie pas les preuves.

`monitoring.review(run_dir, task=None, max_bytes=65536)` retourne des fins de logs et un patch bornés. Le maximum par fichier est 1 MiB ; au-delà de 64 tâches, sélectionner une tâche. Un patch tronqué est une **prévisualisation uniquement**, pas un patch à appliquer. L'API distingue explicitement cette troncature. Les métadonnées JSON sont limitées à 1 MiB et la liste à 200 runs.

Les limites du MVP restent applicables : les preuves locales sont modifiables par le même utilisateur système et les logs peuvent contenir des informations sensibles. La capacité protège l'accès HTTP, pas les fichiers d'un hôte compromis. Les worktrees ne sont pas des sandboxes. Aucun fournisseur ou modèle n'est requis pour le cockpit.

Tests : `python3 -m unittest discover -s tests -p 'test_monitoring.py' -v` et `python3 -m unittest discover -s tests -p 'test_cockpit.py' -v`. Ils font de vrais appels HTTP locaux et vérifient l'accès autorisé, le refus des origines/hôtes/capacités incorrects, les méthodes d'écriture, les traversées, symlinks, métadonnées invalides et la limitation des logs.

## Atelier de production

La vue affiche un poste et un Buddy officiel par tâche réellement planifiée ou observée. Le statut appartient à la tâche : un échec du run ne recolore pas les postes réussis. L'activité running exige un superviseur actif ; une lecture échouée fige les anciens états running en activité non vérifiée. Aucun pourcentage ni événement décoratif n'est ajouté.

Recherche, filtres d'état et pages de 24 cartes permettent de parcourir les gros lots. Les compteurs portent sur toutes les tâches. Les cartes sont conservées par identifiant pendant l'actualisation pour préserver animation et focus. Une sélection donne accès aux seules preuves de cette tâche ; les réponses tardives sont ignorées. Les animations sont limitées aux postes au travail visibles dans l'onglet actif. Une commande globale et `prefers-reduced-motion` permettent leur pause. Sans tâche, aucun Buddy n'apparaît.

Le code du cockpit reste indépendant du fournisseur ; Buddy est une présentation facultative pour les projets qui disposent des droits de réutilisation. La factory reste utilisable en CLI sans mascotte. Les visuels ont des droits réservés, conservés dans `THIRD_PARTY_NOTICES.md`.
