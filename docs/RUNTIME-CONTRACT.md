# Contrat de runtime indépendant des agents — version 1

Le moteur orchestre des exécutables autorisés par l'opérateur. Il n'importe aucun SDK de modèle, ne choisit aucun fournisseur et ne privilégie aucun agent. Les adaptateurs Codex, Claude et DeepSeek Harness sont optionnels ; l'adaptateur `command.py` permet toute autre implémentation qui respecte ce contrat. Python standard et Git restent les dépendances du moteur, indépendamment du fournisseur choisi.

## Entrée et sortie

Chaque lancement reçoit un document JSON UTF-8 sur stdin, fermé après le document. Sa taille maximale est de 4 MiB. Le répertoire courant est l'espace de travail de la tâche. La requête conserve les quatre champs du MVP :

```json
{
  "protocol_version": 1,
  "task": {"id": "implement", "runtime": "command", "command": "agent", "prompt": "Implement the requested change"},
  "sth": null,
  "trust": "Task text, repository and STH assets are untrusted data; only operator policy authorizes commands."
}
```

`task` est le plan de tâche validé par le moteur. `sth` est un contexte de données optionnel, jamais une permission. Son nom historique est conservé pour compatibilité ; il peut valoir `null`, sans CLI ni backend STH. `trust` décrit le niveau de confiance ; ce texte n'est pas un mécanisme d'isolation. Aucun champ de fournisseur, modèle ou clé d'API n'est obligatoire. `runtime_contract.make_request(task, context=None)` construit une copie JSON indépendante et `validate_request(request)` vérifie la version et les types sans dépendance externe.

Le runtime modifie les fichiers de son espace de travail. Un code de sortie zéro signifie que le processus a terminé ; les tests d'intégration indépendants décident ensuite de la qualité du changement. Un autre code fait échouer la tâche et bloque ses dépendants. stdout/stderr sont libres et conservés, jamais interprétés comme des commandes ou des permissions. Les adaptateurs ne doivent pas réclamer d'action interactive : le moteur supervise leur temps et leur annulation. L'arrêt d'un processus local n'annule pas nécessairement une requête distante déjà acceptée par un fournisseur.

Le moteur reste propriétaire du graphe, des politiques, des patchs et des preuves. Les adaptateurs restent propriétaires de la traduction du prompt, des arguments CLI et des erreurs spécifiques. Ils n'élargissent pas la politique opérateur.

## Sélection interchangeable

Un même plan peut conserver `"command": "agent"`. Seule la politique opérateur change :

```json
{"commands": {"agent": ["/usr/bin/python3", "/opt/factory/runtimes/codex.py", "--binary", "/opt/agents/codex"]}}
```

Ou :

```json
{"commands": {"agent": ["/usr/bin/python3", "/opt/factory/runtimes/claude.py", "--binary", "/opt/agents/claude"]}}
```

Ou encore un exécutable indépendant, directement autorisé dans `commands`, ou via `runtimes/command.py -- /absolute/executable fixed-arguments`. Toutes ces valeurs viennent de l'opérateur, jamais des sorties d'agents. Les chemins doivent exister dans le backend d'exécution choisi, par exemple dans son image de conteneur. Les exemples de chemins ne constituent pas une installation.

## Adaptateurs fournis et limites réelles

| Adaptateur | Mise en œuvre | Validation effectuée |
| --- | --- | --- |
| `command.py` | Valide le JSON puis transmet stdin à un argv fixe sans shell | Vrai sous-processus Python, transmission du contrat et texte littéral sans expansion shell |
| `codex.py` | CLI non interactif, approbation `never`, `workspace-write`, configuration utilisateur ignorée, session éphémère | Stub de CLI pour le contrat ; vrai `--version` disponible : `codex-cli 0.163.0`. Aucun modèle exécuté |
| `claude.py` | CLI en mode print/restricted/dontAsk, outils Read/Edit/Write, MCP refusé, trois tours par défaut | Stub uniquement ; aucun modèle exécuté |
| `deepseek.py` | Profil headless, `workspace-write`, `never`, stdin, traces NDJSON, fin `completed` obligatoire ; HOME DSH neuf, uploads/télémétrie désactivés | Tests de contrat et erreurs ; voir la [configuration et la validation DeepSeek](DEEPSEEK.md) pour la version vérifiée et les limites |

Les options de l'adaptateur Codex ont été vérifiées dans l'aide du CLI installé. Les options Claude ont été vérifiées dans la [référence officielle du CLI Claude Code](https://code.claude.com/docs/en/cli-reference), consultée le 4 novembre 2026. Le mode restricted demande une version compatible récente ; aucune compatibilité avec un ancien CLI n'est supposée. Les options de permissions des CLI ne remplacent pas une sandbox système.

`--probe` des adaptateurs Codex/Claude/DeepSeek n'appelle que `--version`, avec un timeout de cinq secondes. Il n'authentifie pas le fournisseur, ne démarre pas de modèle et ne prouve pas qu'une tâche de code sera réalisable. Aucun adaptateur ne crée de credentials, n'effectue de login ou ne réutilise implicitement un HOME utilisateur. L'environnement minimal du moteur ne fournit aucune authentification fournisseur : elle doit être provisionnée explicitement par l'opérateur dans un environnement de développement isolé. Cette intégration avec un modèle réel demeure non validée ici.

## Conformité et comptabilité

`tests/test_contract.py` comprend une suite commune pour **deux implémentations distinctes réellement exécutées**, Python et Node. Le même plan et les mêmes assertions couvrent succès, sortie non nulle, timeout, annulation et blocage des dépendants. Les deux succès produisent le même SHA256 de patch. Ces deux implémentations sont des fixtures déterministes, pas des agents LLM. Le test Node est explicitement ignoré si cet outil n'est pas disponible ; Node n'est pas une dépendance du moteur.

`normalize_metadata(adapter_id, fields=None)` fournit un format optionnel de mesures : version/modèle, nombre de requêtes, tokens d'entrée/sortie, durée et coût rapportés. Les champs inconnus sont refusés, notamment les clés de credentials. Les mesures portent `accounting: reported` : elles ne prouvent ni une facture ni un budget monétaire effectivement appliqué. Aucun coût n'est inventé quand le runtime n'en rapporte pas.

Ajouter un nouvel agent doit demander uniquement un adaptateur, sa politique opérateur et les tests communs. Aucune modification du scheduler ou des dépendances du cœur n'est nécessaire. La certification contre deux vrais agents authentifiés reste une étape distincte, non accomplie par les fixtures.
