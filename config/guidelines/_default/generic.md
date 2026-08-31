# Guidelines génériques (pack par défaut)

Utilisé quand aucun pack spécifique n'est configuré (`GUIDELINES_PACK`). Règles
transverses, indépendantes du langage.

## Priorités
1. **Correction** : le code fait-il ce qu'il prétend ? Cas limites, valeurs nulles, erreurs.
2. **Sécurité** : entrées non fiables validées ? secrets hors du code ? injections évitées ?
3. **Clarté** : un mainteneur comprend-il en 6 mois ? nommage explicite, pas de magie inutile.
4. **Tests** : la logique risquée est-elle couverte ? les tests sont-ils déterministes ?
5. **Cohérence** : le changement suit-il les patterns déjà présents dans le module touché ?

## Signaux à remonter
- Duplication significative introduite (extraire un helper).
- Complexité algorithmique évitable sur un chemin chaud.
- Ressource acquise non libérée (fichier, connexion, lock).
- Gestion d'erreur absente ou avalée silencieusement (`except: pass`).
- Valeur codée en dur qui devrait être une constante/config.
- Changement d'API public sans mise à jour des appelants/doc.

## À NE PAS remonter
- Préférences de style non documentées dans le projet.
- Ce que le linter/formatter/typechecker gère déjà.
- Problèmes préexistants hors du diff.
