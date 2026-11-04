# Initialiser un autre projet

La factory fonctionne sans agent particulier, sans fournisseur de modèle et sans STH. Le démarrage génère uniquement une configuration de contrôle des tests d'un dépôt existant ; il ne crée pas de dépôt, n'installe aucune dépendance et ne modifie ni son code ni sa configuration Git.

Prérequis : Python 3.12+, Git, Linux/POSIX. Le modèle Node exige aussi un Node prenant en charge `node --test`. Les dépendances du projet restent à installer par son propriétaire, dans l'environnement d'exécution choisi.

Depuis l'interface CLI intégrée :

```sh
python3 factory.py init --destination /chemin/configuration-neuve --template python
python3 factory.py doctor --repo /chemin/mon-projet \
  --policy /chemin/configuration-neuve/operator-policy.json
python3 factory.py plan --plan /chemin/configuration-neuve/plan.json \
  --policy /chemin/configuration-neuve/operator-policy.json
python3 factory.py run --repo /chemin/mon-projet --output /chemin/nouveau-run \
  --plan /chemin/configuration-neuve/plan.json \
  --policy /chemin/configuration-neuve/operator-policy.json
```

Pour Node, choisir `--template node`. Les deux modèles exécutent réellement la suite du projet et échouent si aucun test n'est découvert. Une réussite ne prouve pas que les tests sont suffisants : la politique et les contrôles doivent être relus par l'opérateur.

L'API Python correspondante est `initialize_project(destination, template='python')`, puis `doctor(repo, policy, sth=None)`. Le dossier de configuration doit être absent et son parent doit déjà exister. Un dossier existant, même vide, ou un symlink est refusé : aucun fichier humain n'est écrasé. Le dossier de run doit être neuf et situé hors du dépôt source. Les chemins des exécutables sont absolus et correspondent à la machine où la configuration est générée ; après un changement de machine, régénérer ou relire la politique.

`doctor` vérifie Python, Git, le dépôt et la présence des exécutables autorisés. Il n'exécute jamais les commandes du projet et ne lit aucun credential. Un résultat `ready` indique seulement que ces prérequis locaux sont présents. Il ne valide ni les tests, ni l'authentification du fournisseur, ni une isolation système. La présence de Docker, Podman ou bwrap n'établit pas qu'une sandbox est utilisable.

L'exécution locale est destinée aux commandes et dépôts relus. Les worktrees ne sont pas des sandboxes de sécurité. Un agent de code non fiable exige un backend isolé explicitement configuré et vérifié ; aucun modèle ni credential n'est choisi automatiquement. Les adaptateurs d'agents restent interchangeables via la politique opérateur.
