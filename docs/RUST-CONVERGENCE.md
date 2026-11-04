# Factory rejoint STH Code

Le 4 novembre 2026, la direction retenue est une application STH Code en Rust
pour Windows, macOS et Linux, qui réunit le travail avec les agents et
l'orchestration des tâches de Factory. Emdash, Orca et T3 Code sont les trois
références produit confirmées.

STH Code apporte les conversations, les comptes fournisseurs, les projets,
les worktrees, l'historique, Git et la revue. Factory apporte les tâches
dépendantes, leur exécution parallèle, la vérification indépendante, les limites
et les résultats à relire. Le produit commun doit permettre de suivre une
demande jusqu'à un changement validé, puis de reprendre le travail existant.

Le portage Rust est développé dans une branche séparée de STH Code. La version
Python et les fichiers d'origine restent conservés. Leur présence ne suffit
pas à déclarer une parité fonctionnelle : chaque contrat doit être implémenté
et testé dans la nouvelle application.

Premiers contrats portés : plan de tâches, dépendances, commandes autorisées,
copies Git indépendantes, patchs, limites, annulation et résultats. La reprise
durable, les réessais, les conteneurs et le bridge d'assets STH de cette version
Python restent à porter. Les options encore absentes sont refusées explicitement.

La livraison visée comprend `sth-code.exe` sous Windows, une application `.app`
sous macOS et des exécutables Linux. Les paquets et leurs tests doivent être
produits sur chaque système ; un build local Mac ne constitue pas une preuve
Windows ou Linux.

Le code public de Factory reste sous sa licence actuelle. Cette convergence
ne modifie pas automatiquement la visibilité des autres dépôts STH ni les
droits de la mascotte Buddy.
