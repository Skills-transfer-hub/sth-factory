# DeepSeek Harness comme runtime facultatif

[DeepSeek Harness](https://www.deepseek.com/en/harness/) est le harness officiel : il fournit au modèle une boucle de travail et des outils. La Factory le lance sur une tâche, garde les logs et les patchs, puis exécute la validation indépendante définie par le plan. STH et un compte DeepSeek ne sont pas nécessaires pour les autres runtimes.

L'adaptateur cible le CLI `@deepseek-ai/dsh@0.2.2-rc.1`, avec Node **24.9.0 minimum**. Référence inspectée le 4 novembre 2026 : commit upstream [`fcc0ad4`](https://github.com/deepseek-ai/deepseek-harness/tree/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159), notamment le [contrat headless](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/bundle/headless/README.md). DSH est en preview ; revérifier le contrat avant une montée de version.

## Installation et diagnostic

Installer le harness séparément du dépôt à modifier, avec la version choisie explicitement. Par exemple, dans un dossier neuf où l'on peut écrire :

```sh
npm install --prefix /chemin/installation-dsh --ignore-scripts --no-audit --no-fund @deepseek-ai/dsh@0.2.2-rc.1
```

Le cœur de la Factory ne dépend pas de npm. Pour inspecter le CLI installé sans appeler de modèle :

```sh
python3 runtimes/deepseek.py \
  --binary /chemin/installation-dsh/node_modules/@deepseek-ai/dsh/lib/bin.js \
  --node /chemin/absolu/node --probe
```

Les chemins ci-dessus sont à remplacer par ceux de l'installation. `--node` fournit explicitement l'interpréteur : l'environnement minimal de la Factory ne retrouve pas nécessairement Node installé via Homebrew ou un gestionnaire de versions. Sans cette option, `--binary` doit être un exécutable autonome capable de fonctionner dans cet environnement.

## Politique opérateur

Dans la politique relue par l'opérateur, l'argv de la commande `agent` peut être :

```json
{
  "commands": {
    "agent": [
      "/chemin/absolu/python3.12",
      "/chemin/factory/runtimes/deepseek.py",
      "--binary", "/chemin/installation-dsh/node_modules/@deepseek-ai/dsh/lib/bin.js",
      "--node", "/chemin/absolu/node",
      "--config", "/chemin/configuration-operateur/deepseek.patch.yml"
    ]
  }
}
```

Cet extrait définit uniquement la commande. Conserver les limites du run et ajouter la commande de tests adaptée au projet dans la même politique. Le plan enchaîne une tâche `implement` (`runtime: command`, `command: agent`) puis une tâche `verify` dépendant de `implement`, dont la commande de tests est choisie par l'opérateur. Une réponse `completed` ne remplace jamais ce contrôle.

`--config` est un patch YAML DSH explicite, facultatif, situé hors du worktree. Il peut choisir le modèle et son fournisseur. L'adaptateur le passe avant son propre patch, qui désactive l'upload de sessions et la télémétrie. Un patch DSH est du code de configuration de confiance : ses plugins peuvent exécuter du code. Ne pas le générer à partir des sorties d'une tâche.

L'authentification doit être provisionnée explicitement dans cet environnement de développement. La Factory ne reprend ni le login de l'application DSH, ni le HOME, ni les clés exportées du shell de l'utilisateur. Ne placer aucune clé dans le plan, la politique archivée ou le dépôt. Les détails du provisioning fournisseur sont ceux de la version DSH installée ; un `--probe` réussi ne les valide pas.

## Comportement vérifié par les tests de contrat

- Profil `headless`, permissions `workspace-write`, approbations `never`, prompt via stdin et sortie `--json`.
- `DSH_HOME` temporaire hors du worktree ; pas de session réutilisée. Suppression de ce dossier à la fin normale de l'adaptateur.
- Refus de `.env` dans le worktree, y compris symlink ou dossier : le lanceur DSH le charge automatiquement, sans option de désactivation dans la version inspectée.
- Upload `session-log-deepseek` désactivé ; `session-telemetry-otel` désactivé ; `DSH_TELEMETRY_DISABLED=1`.
- Inventaire `plugin-package-inventory-deepseek` et génération de titre `session-title-llm` désactivés : pas d'inventaire de plugins transmis ni d'appel modèle supplémentaire pour nommer la session.
- Traces NDJSON conservées ; maximum de 1 MiB par événement. Une ligne invalide, une fin absente, une raison autre que `completed`, un événement après la fin ou un code de sortie non nul fait échouer la tâche.

La Factory conserve ses limites de temps et de sortie ainsi que la supervision du groupe de processus. L'adaptateur n'applique pas de budget monétaire fournisseur. Une requête distante déjà acceptée peut continuer après un arrêt local.

`workspace-write` n'interdit pas toutes les lectures ni le réseau. Un fichier de credentials hors du dépôt reste lisible par un processus du même utilisateur en mode local. Le backend Docker existant impose `network=none` et ne permet donc pas de joindre un modèle distant. Le choix d'une isolation et d'un accès fournisseur adaptés reste nécessaire avant de confier du code non fiable à un modèle réel.

## Validation réelle du CLI, sans modèle

Le 4 novembre 2026, le paquet npm épinglé a été installé dans un dossier temporaire avec ses scripts d'installation désactivés. La Factory a lancé le vrai CLI DSH avec son environnement minimal et un `--node` explicite. Un fournisseur Messages SSE simulé sur localhost a demandé à l'outil d'écriture natif de remplacer `return 1` par `return 42` dans un dépôt jetable. La tâche de validation dépendante a exécuté un test unittest indépendant avec succès ; le dépôt source est resté inchangé.

Le scénario final a reçu deux requêtes locales (appel d'outil puis réponse finale), sans champs d'upload de session ni d'inventaire de plugins. Les sorties réseau externes étaient interdites par `sandbox-exec` pendant ce test sur macOS. Il s'agit d'une protection propre au scénario de validation, pas d'un nouveau backend de la Factory. Aucune clé réelle, aucun compte et aucun modèle distant n'ont été utilisés.

Cette preuve valide le transport, l'outil, le patch et la validation en chaîne. Elle ne mesure ni la qualité du modèle DeepSeek, ni son coût réel, ni les performances de STH. L'empreinte SHA256 du patch d'implémentation était `68383d79bd28599ac38ed07f7e0cac1cfa755c125167d10839e7a732a80f1bad`.
