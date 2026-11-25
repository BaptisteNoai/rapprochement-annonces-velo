# Annotation du jeu de test

Fichier : `a_annoter.csv` (séparateur `;`, s'ouvre dans Excel). 200 annonces tirées au hasard (graine 0) parmi les 1 856 vélos électriques de buycycle. Pour chacune : son nom, sa marque, son année, son lien, et les 5 meilleurs candidats du catalogue avec leur score de similarité (0 à 100).

## Ce qu'on annote

Pour chaque annonce, la colonne **`choix`** :

| Valeur | Sens |
|---|---|
| `1` à `5` | le candidat n°1 à 5 est **le même modèle** que l'annonce |
| `0` | le modèle de l'annonce **n'est pas dans le catalogue** |
| `Marque \| Modèle` | le bon modèle est dans le catalogue mais pas dans les 5 candidats (le chercher avec `python scripts/chercher_catalogue.py <mots>`) |

**Même modèle** = même gamme **et** même version ou finition : « E-Spark 720 » ≠ « E-Spark 730 », « Rail 9.8 » ≠ « Rail 5 », « Turbo Vado 4.0 » ≠ « Turbo Vado 5.0 ». On **ignore l'année, la taille, la couleur et le cadre** (« Step-Through »…) : l'année est comparée à part.

Si plusieurs candidats sont le même modèle avec des années différentes, mettre le premier. En cas de doute réel, mettre `0` et expliquer dans **`remarque`** (ces cas serviront à l'analyse des erreurs). Ouvrir le lien de l'annonce si le nom ne suffit pas.

Compter 2 à 3 heures. Ne pas regarder les réponses du LLM avant d'avoir fini : l'annotation doit rester indépendante.

## Après l'annotation

Renommer le fichier en `annotations.csv`. Il devient la vérité de terrain de `scripts/evaluer.py`.
