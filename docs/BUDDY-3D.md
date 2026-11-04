# Buddy 3D dans la factory

Les animations officielles Buddy ont été copiées, sans réencodage, depuis
[`Skills-transfer-hub/sth-claude`, commit `161b12789f1d8c74f5305f727917c5cb1fca8a13`](https://github.com/Skills-transfer-hub/sth-claude/tree/161b12789f1d8c74f5305f727917c5cb1fca8a13/mods/sth-usage).
Il s'agit d'images pré-rendues du modèle 3D officiel, et non d'un modèle WebGL animé dans le navigateur.

L'autorisation écrite reçue pour cette factory couvre la copie des modèles et animations Buddy et leur distribution avec elle, en conservant leurs droits réservés. **Ces visuels ne sont pas sous MIT.** Cette autorisation ne constitue pas une licence générale de réutilisation des visuels dans d'autres produits. Le code de la factory reste distinct des droits sur les visuels ; Buddy n'introduit aucune dépendance à un fournisseur d'agents.

## Fichiers et provenance

Le répertoire `web/buddy-3d/161b1278/` contient :

| Séquence | Source au commit indiqué | Images | Taille totale |
|---|---|---:|---:|
| `ok` | `mods/sth-usage/ui/frames/ok.ts` | 80 | 652 176 octets |
| `work` | `mods/sth-usage/ui/frames/work.ts` | 48 | 384 108 octets |
| `done` | `mods/sth-usage/ui/frames/done.ts` | 38 | 303 066 octets |
| `error` | `mods/sth-usage/ui/frames/error.ts` | 30 | 241 616 octets |

Les 196 images sont des WebP de 384 × 384 pixels, nommées `sequence/0000.webp` à partir de zéro. Elles occupent 1 580 966 octets. Les tableaux JSON littéraux qui suivent `export default` ont été analysés comme données puis décodés en base64 strict. Aucun fichier TypeScript du dépôt source n'a été exécuté. Les octets des images correspondent exactement aux payloads source : aucune image n'a été réencodée ni inventée.

`manifest.json` fournit `source_commit`, `fps: 20`, les dimensions et, pour chaque séquence, `count`, `files` et `bytes`. Le lecteur officiel `ui/buddy.ts` utilise une période de 50 ms ; sa copie de référence est `source-player.txt`. `source-plugin.json` conserve les métadonnées officielles de Buddy by STH 0.3.5. `SOURCE-LICENSE.txt` conserve la licence officielle complète.

`provenance.json` contient les empreintes SHA-256 de chaque image, son index source et sa taille ; il conserve également les SHA-1 Git des blobs source et leurs SHA-256. Les blobs ont été récupérés par Git au commit fixe et vérifiés selon le calcul Git `SHA1("blob " + taille + NUL + contenu)`.

`model.blend` est une copie inchangée de `mods/sth-usage/assets/model/buddy-v6.blend` :

- taille : 492 506 octets ;
- blob Git : `e4b5d5427afe8988f96b09c58f5490c36a42a4d8` ;
- SHA-256 : `9107338bd3677f393456724f751d0f2cc26333f43f739349c117fdc07a029518`.

Le fichier Blender officiel est compressé en Zstandard. Une décompression en mémoire a confirmé l'en-tête `BLENDER17-01` et une taille décompressée de 3 733 694 octets. Le modèle conservé reste compressé et inchangé ; Blender n'a pas été exécuté. Le cockpit ne sert pas ce modèle et utilise uniquement les frames et leur manifeste.

## Droits

La [licence officielle](https://github.com/Skills-transfer-hub/sth-claude/blob/161b12789f1d8c74f5305f727917c5cb1fca8a13/mods/sth-usage/LICENSE), section 2, exclut explicitement les modèles, images, poses, vidéos, données d'animation et marques Buddy/STH de MIT, y compris les payloads encodés dans des fichiers source.

Copyright (c) 2026 Skills Transfer Hub. All rights reserved.

La notice de droits réservés est reproduite dans `THIRD_PARTY_NOTICES.md`. La permission reçue concerne leur distribution avec cette factory et ne transfère aucun droit de marque. La notice du logo statique précédent est conservée séparément.

## Vérifications reproductibles

Depuis la racine du projet, ce contrôle sans dépendance vérifie chaque taille, chaque SHA-256 et les signatures des WebP :

```python
from pathlib import Path
import hashlib, json
base = Path("web/buddy-3d/161b1278")
p = json.loads((base / "provenance.json").read_text())
assert len(p["frames"]) == 196
for name, expected in p["frames"].items():
    data = (base / name).read_bytes()
    assert len(data) == expected["bytes"]
    assert hashlib.sha256(data).hexdigest() == expected["sha256"]
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
model = (base / "model.blend").read_bytes()
assert hashlib.sha256(model).hexdigest() == p["model.blend"]["sha256"]
```

Lors de l'importation, les 196 images ont également été décodées entièrement avec Pillow et leurs dimensions 384 × 384 vérifiées. Cela vérifie les fichiers ; les tests du lecteur et les captures du cockpit constituent des preuves distinctes de leur affichage et de leurs transitions d'état.

## Lecteur et états réellement observés

Le cockpit adapte le lecteur officiel à son navigateur local : mêmes frames WebP, cadence 20 images/s, aucune dépendance à Claude Code ni à un fournisseur. Il affiche les rendus 3D d'origine ; il ne charge pas de scène WebGL ou de nouveau personnage. Les séquences `ok`, `work`, `done` et `error` correspondent à attente, exécution en cours, succès terminal cohérent et échec/arrêt, avec une légende précisant le statut exact.

Chaque **tâche réelle** du run possède un poste et son Buddy. La projection [FACTORY-VIEW.md](FACTORY-VIEW.md) utilise le statut propre à la tâche : une tâche réussie conserve sa pose de succès lorsque le run global échoue. Une tâche running n'anime sa séquence de travail que si le superviseur est actif et le run toujours en cours. Sans preuve d'activité, elle passe en état à vérifier. Aucun pourcentage n'est inventé.

Seuls les Buddies au travail s'animent à 20 images/s. Attente, succès et erreur utilisent une pose officielle fixe. Le bouton global de pause affecte la présentation et laisse les états s'actualiser. La préférence de réduction des mouvements, les onglets masqués et les cartes hors écran suspendent l'animation. Les joueurs détruits lors d'un changement de page retirent leurs listeners et boucles ; la vue affiche au maximum 24 postes et permet recherche, filtre, pagination et inspection des preuves. Les compteurs portent sur le lot complet. Sans tâche, il n'y a aucun Buddy de remplissage.

Les images sont chargées depuis le même serveur local, avec chemins bornés et cache privé sur une URL épinglée au commit. Le modèle Blender, la licence et les fichiers de provenance ne sont pas exposés par la route des animations. Aucune requête vers un CDN ou fournisseur n'est nécessaire à la lecture.

Reproduction des transitions avec de vrais processus locaux déterministes, sans modèle IA (Playwright et Chromium sont des outils de validation facultatifs) :

```sh
python3 examples/validate_factory_floor.py --output /tmp/new-buddy-proof
```

Le script lance 31 tâches réellement planifiées dans un dépôt de démonstration indépendant : 3 processus simultanés, 29 succès, 1 échec volontaire et 1 tâche bloquée par sa dépendance. Il teste zéro Buddy avant sélection, chargement des poses, pause, réduction des mouvements, filtres, pagination, sélection des logs, focus conservé et rendu mobile. Les gates appartiennent au harness ; aucun statut n'est injecté dans le cockpit. Les 196 assets inchangés sont également couverts par les tests de provenance. L'ancien point d'entrée `validate_buddy_3d.py` redirige vers ce scénario.
