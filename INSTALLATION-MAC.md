# Installation locale du 4 novembre 2026

Source restaurée depuis le Space STH, version 4110b6c6312b621344e0bc213f834ae768689d86, avec corrections locales de navigation du cockpit et synchronisation du test d’annulation. Les archives originales restent dans le dossier de travail Codex.

## Ouvrir le cockpit

Double-cliquer sur `start-cockpit.command`, ou exécuter ce fichier dans Terminal. Il utilise Python 3.12 installé sur ce Mac et sert uniquement sur 127.0.0.1:51240. Ouvrir le lien complet imprimé, y compris sa partie après #. Le jeton change à chaque lancement. Arrêter le serveur avec Ctrl+C dans son terminal. Ne pas lancer une seconde instance sur le même port.

Les runs de démonstration sont dans `/Users/hugo/Developer/sth/sth-factory-runs/local-validation`. Le run livré contient trois tâches déterministes réussies, sans modèle IA. Le cockpit est en lecture seule.

## Vérifier

Depuis ce dossier :

```sh
TMPDIR="$(cd "${TMPDIR:-/tmp}" && pwd -P)" /Users/hugo/.local/bin/python3.12 -m unittest discover -s tests -v
```

Le chemin temporaire canonique évite le lien système /var sur macOS, que les vérifications de chemins refusent volontairement. Résultat de la validation : 108 tests, réussite avec 5 intégrations optionnelles ignorées. Aucun fournisseur IA réel ni backend conteneur n’a été validé.

Les API gardent le contrôle de jeton, Host, Origin et Fetch Metadata. Seule la navigation initiale vers la page HTML vide peut provenir d’un lien externe ; cette page ne contient ni jeton ni données de run. Les worktrees ne sont pas des sandboxes.
