# Reprise durable et réessais explicites

Chaque nouveau run crée `state.sqlite3`, avec transactions SQLite `synchronous=FULL`, état des tâches, nombre de tentatives, processus lancés et événements. `run.lock` est verrouillé par `flock` : deux superviseurs ne peuvent pas reprendre simultanément le même run. Le journal JSONL et le résumé restent lisibles sans SQLite.

```sh
python3 factory.py resume --repo /chemin/projet --output /tmp/factory-runs/run-1 \
  --policy /chemin/operator-policy.json
# Seulement après examen de la tentative :
python3 factory.py resume --repo /chemin/projet --output /tmp/factory-runs/run-1 \
  --policy /chemin/operator-policy.json --retry-task implement
```

La reprise exige le dépôt, la politique et le CLI STH éventuel d'origine. Elle refuse une source changée, des patchs réussis altérés et une préparation inachevée. Le commit, le plan et l'empreinte source sont conservés. Les résultats réussis sont réutilisés sans lancer leur runtime. Les tâches en cours au crash deviennent `interrupted` et leurs dépendants sont bloqués ; elles ne sont pas relancées par défaut.

`max_attempts` vaut 1 par défaut et ne peut dépasser 3. La politique d'origine doit autoriser le réessai. Le délai global fixé à la création du run persiste entre les reprises et s'écoule aussi pendant l'arrêt du superviseur. Un budget expiré impose un nouveau run. Les anciens worktrees et preuves sont déplacés sous `attempts/<id>/<numéro>/`, sans suppression de leurs modifications. L'archivage est récupérable après un arrêt entre les déplacements et la transition SQLite.

Les processus sont enregistrés après leur lancement et toujours arrêtés/attendus même si cet enregistrement échoue. Une reprise refuse un ancien groupe de processus qui semble encore actif : elle ne tue pas un PID ambigu. L'opérateur doit contrôler les survivants. L'identité Linux est conservée pour diagnostic, sans autoriser la suppression d'un PID réutilisé.

Un conteneur peut survivre au client Docker et au superviseur. Avant le réessai explicite d'une tâche interrompue, la factory vérifie le nom, le label et l'image épinglée du conteneur enregistré puis supprime uniquement celui-ci. Les fichiers de contrôle ne sont pas montés. Les tâches interrompues non réessayées ne sont pas relancées. Une supervision externe reste nécessaire pour garantir l'arrêt des charges après la mort brutale du superviseur.

Un réessai peut répéter un effet externe antérieur au crash. La factory ne garantit pas l'exécution exactement une fois de commandes arbitraires. Aucun réessai automatique : l'opérateur examine les preuves avant sa demande. Les opérations GitHub ont leurs propres reçus empêchant une nouvelle création après une réponse incertaine.

La base et les journaux restent modifiables par l'utilisateur hôte. En mode local, un runtime sous le même utilisateur peut les altérer. C'est un état de développement durable, pas une preuve inviolable. Le conteneur limite l'accès via les montages, sans protéger contre une faille du noyau ou du daemon.

Tests : persistance après réouverture, exclusion mutuelle, bornes des réessais, réutilisation sans replay, refus de patch altéré, archivage partiel, arrêt d'un processus si SQLite échoue et véritable SIGKILL du superviseur suivi d'une reprise explicite.
