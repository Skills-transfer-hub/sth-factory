# Buddy 3D — validation du 4 novembre 2026

Code intégré : `8dad9296ef6743b5b3416efb26f2ad3a6170eab0`, branche locale `factory/buddy-3d`.

L'autorisation explicite reçue couvre la copie des modèles et animations Buddy dans cette factory et leur distribution avec elle, en conservant leurs droits réservés. Aucun droit n'a été étendu par la licence MIT du code.

Le vrai personnage 3D provient de `Skills-transfer-hub/sth-claude`, commit `161b12789f1d8c74f5305f727917c5cb1fca8a13`. Les 196 frames WebP et le modèle Blender ont été importés sans réencodage ni transformation. Les empreintes sont dans `web/buddy-3d/161b1278/provenance.json`. La lecture reprend les rendus 3D officiels, pas un nouveau personnage ou une scène WebGL inventée.

## Tests exécutés

La suite complète a réussi : **95 tests, aucun ignoré**, avec STH Alpha 0.2.44 et les tests Docker activés. [Journal exact](tests.txt).

Le scénario [examples/validate_buddy_3d.py](../../examples/validate_buddy_3d.py) a ensuite tourné dans Chromium réel, avec deux véritables runs de processus Python déterministes, sans modèle IA. Il vérifie les empreintes des 196 frames et du modèle avant la capture.

[Résultats du navigateur](browser-checks.json) : attente sans sélection, animation de travail sur run actif, succès puis échec réellement observés ; pause sans perdre les mises à jour d'état ; démarrage figé avec réduction des mouvements ; bascule dynamique de préférence ; absence de débordement à 390 et 320 px ; anciennes réponses de statut et de revue incapables d'écraser la sélection courante ; dépôt source inchangé.

La revue indépendante a aussi fait corriger la détection d'activité : une ancienne trace `running` ne suffit plus. Le monitoring consulte le verrou du superviseur ; sans activité vérifiée, il expose `interrupted` ou `unknown`, sans prétendre que les processus enfants sont tous arrêtés. Deux tests dédiés couvrent cette limite. Le lecteur attend le décodage d'une frame avant affichage pour éviter l'annulation en boucle des images sur une machine occupée.

## Captures et vidéo

Les fichiers originaux se trouvent dans `/workspace/sth-factory-buddy-3d-verified` : cinq captures (attente, travail, succès, erreur, mobile) et `buddy-3d-reactions.mp4`, 10,56 s, H.264, 1600 × 1000, sans audio ni changement de vitesse. Les captures proviennent de l'interface réelle. Les gates des processus sont pilotées par le harness ; aucun statut ni pourcentage n'est injecté dans le cockpit.

Les animations restent facultatives, locales et indépendantes de l'agent choisi. Le code demeure MIT ; les visuels restent à droits réservés. Aucun modèle IA, publication, PR distante, merge ou déploiement n'a été effectué. Aucun refus réseau n'a été contourné. La création de fichiers natifs est vérifiée séparément ; leur transmission RCS n'est pas supposée.
