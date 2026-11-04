# Projection des tâches pour le cockpit

`web/factory-view.js` expose `FactoryView.project(snapshot, options)` dans le navigateur et `require('./web/factory-view.js').project` dans Node. Ce module pur n'utilise aucun DOM, runtime d'agent, réseau ou fournisseur. Il ne modifie pas le snapshot et crée de nouvelles listes de dépendances.

```javascript
const projection = FactoryView.project(snapshot, {
  query: '', filter: 'all', page: 0, pageSize: 24
});
```

Le résultat fournit `tasks` (toutes les tâches normalisées), `visible` (la page après recherche et filtre), `counts`, `page`, `pageCount`, `filteredCount`, `pageSize`. Chaque tâche contient `{id, status, state, caption, depends_on, index}`. `index` est sa position à partir de zéro dans l'ensemble ordonné, avant filtrage.

Les tâches réelles de `snapshot.plan.tasks` apparaissent dans leur ordre, puis les identifiants supplémentaires réellement présents dans `snapshot.tasks`, dans l'ordre du snapshot. Une tâche planifiée sans observation est `not_started`. Aucune carte de remplissage n'est créée. Le premier doublon du plan est conservé et l'observation propre à la tâche fait autorité pour son statut. Les identifiants suivent la même expression régulière que la factory : `[A-Za-z0-9][A-Za-z0-9_-]{0,63}` ; les identifiants invalides sont ignorés. Les dépendances sont des identifiants valides uniques, copiés sans inventer de tâches associées.

| Statut propre à la tâche | État visuel |
|---|---|
| `pending`, `not_started` | `waiting` |
| `succeeded` | `success` |
| `failed`, `timed_out`, `cancelled`, `interrupted`, `blocked` | `error` |
| `running`, si `snapshot.status === 'running'` et `snapshot.supervisor_active === true` | `working` |
| `running` sans ces deux preuves | `unknown`, activité non vérifiée |
| absent, inconnu ou invalide dans un enregistrement observé | `unknown` |

Un succès individuel reste un succès lorsque le run global échoue. Un statut `running` non vérifié est conservé comme statut rapporté, mais sa projection reste `unknown`. Un statut explicitement `interrupted` devient `error`. Les légendes sont des textes fixes ; aucun contenu fourni par un agent n'est exécuté ou utilisé comme légende HTML. Le consommateur doit afficher les données avec `textContent`.

`counts` porte toujours sur toutes les tâches : `{total, waiting, working, success, error, unknown}`. Le filtre accepte ces cinq états visuels, ou `all` ; un filtre invalide revient à `all`. La recherche insensible à la casse porte sur l'identifiant, le statut normalisé, la légende et les dépendances. Elle est limitée à 512 caractères après retrait des espaces périphériques. Recherche et filtre sont appliqués avant pagination. `filteredCount` indique leur nombre de résultats.

La page commence à zéro. La taille entière est bornée entre 1 et 24, avec 24 par défaut. La page demandée est ramenée dans l'intervalle disponible. Un résultat vide donne `page: 0`, `pageCount: 0`, `visible: []`. La limite de 24 borne les cartes actives dans la vue ; `tasks` conserve les enregistrements complets et le module ne prétend pas borner la taille du snapshot reçu.

## Validation

```sh
python3 -m unittest discover -s tests -p test_factory_view.py -v
```

Les huit tests Python exécutent réellement le module JavaScript dans Node : export navigateur/CommonJS, zéro tâche, 1 000 tâches et pagination bornée, états parallèles, succès individuel dans un run échoué, garde de superviseur actif, recherche/filtres, doublons, identifiants/dépendances/statuts non fiables, absence de mutation des entrées gelées. Ils ont d'abord échoué en l'absence du module, puis tous passé après implémentation. Ils vérifient la projection ; ils ne constituent pas une preuve de rendu visuel du cockpit ni d'exécution d'un modèle d'IA.
