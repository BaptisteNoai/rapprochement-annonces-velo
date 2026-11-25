# Rapprochement d'annonces de vélos électriques avec un catalogue : règles contre LLM, mesurés

Une annonce d'occasion de particulier (buycycle.com) s'appelle « Trek Powerfly 5 2020 » ; le catalogue de l'[observatoire du vélo électrique](https://github.com/BaptisteNoai/observatoire-velo-electrique) connaît « Powerfly 5 » et « Powerfly FS 5 ». Relier chaque annonce au bon modèle, ou dire qu'il n'est pas au catalogue, permettrait de comparer les prix entre particuliers et revendeur à modèle égal.

Question du projet : **un LLM fait-il mieux qu'une règle simple pour ce rapprochement ?** Réponse sur ces données : **non, pas un petit LLM local**, et ce README explique pourquoi.

## Résultats

Jeu de test : 200 annonces tirées au hasard parmi 1 856, annotées à la main (bon modèle, ou « aucun »), découpées en deux moitiés fixes : 100 pour ajuster les méthodes, 100 mises de côté et mesurées une seule fois, réglages figés.

**Mesure finale sur les 100 annonces de test** (42 avec un modèle au catalogue, 58 sans) :

| Méthode | Exactitude | Précision | Rappel | « Aucun » juste | Temps par annonce |
|---|---|---|---|---|---|
| Baseline : similarité de chaînes, seuil 100 | 75 % | 59,0 % | 54,8 % | 89,7 % | instantané |
| **Règle de version : baseline + mêmes numéros de version** | **75 %** | **62,9 %** | 52,4 % | 91,4 % | instantané |
| LLM local (qwen2.5:3b) qui choisit parmi 10 candidats | 30 % | 23,3 % | 50,0 % | 15,5 % | 11 s |
| Hybride : règle de version, puis le LLM vérifie (oui / non) | 63 % | 60,0 % | 14,3 % | 98,3 % | 6 s |

- *Exactitude* : bonne réponse, « aucun » compris. *Précision* : part des rapprochements proposés qui sont justes. *Rappel* : part des annonces ayant un modèle au catalogue qui sont retrouvées.
- Tous les résultats, moitié d'ajustement comprise : [`eval/resultats.md`](eval/resultats.md).

## Ce qui s'est passé

1. **La baseline** prend le candidat le plus proche (similarité `token_set_ratio`, dans la même marque) s'il dépasse un seuil, choisi sur la moitié d'ajustement : 100. Son défaut : une similarité de 100 dès que les mots d'un nom sont inclus dans l'autre (« Levo Alloy » dans « Turbo Levo Comp Alloy »).
2. **Le LLM seul** (qwen2.5:3b via Ollama, gratuit, sortie JSON validée par Pydantic) devait choisir parmi 10 candidats ou répondre « aucun ». Il ne dit presque jamais « aucun » : sur ses 134 erreurs (200 annonces), 86 sont des rapprochements proposés alors que le modèle n'est pas au catalogue (« Rail 9.8 » rapproché de « Rail 9.7 »).
3. **La règle de version** exige les mêmes jetons numériques (9.8, 730, one44…), sans compter la batterie (625 Wh) ni la taille de roue (27.5, 29). Elle supprime des faux rapprochements, mais pas les différences de lettres (« 9.8 XT » contre « 9.8 GX AXS »).
4. **L'hybride** devait combler ce manque : la règle filtre, le LLM vérifie le candidat par oui ou non. Le modèle bascule alors dans l'excès inverse et répond presque toujours non (rappel de 14 %). Un modèle de 3 milliards de paramètres suit la consigne dans un sens ou dans l'autre sans juger la finition d'un vélo.

**Conclusion** : la règle de version est retenue (méthode par défaut de l'API). Un LLM n'aurait d'intérêt ici qu'avec un modèle plus capable ou entraîné sur la tâche ; c'est la suite prévue.

## Méthode d'évaluation

- Annotation à la main avec une consigne écrite ([`eval/README.md`](eval/README.md)) : même gamme **et** même version ; année, taille, couleur et batterie ignorées.
- Découpage fixe ajustement / test ([`eval/decoupage.csv`](eval/decoupage.csv)) : seuils et prompts choisis sur l'ajustement uniquement.
- Comparaison au niveau du modèle : deux entrées du catalogue qui ne diffèrent que par la batterie, la taille de roue ou la marque répétée comptent comme le même modèle (correction appliquée à toutes les méthodes, après lecture des premières erreurs sur la moitié d'ajustement).
- Réponses du LLM mises en cache ([`eval/cache/`](eval/cache/)) : les chiffres se reproduisent sans relancer le modèle.

**Limites** : 100 annonces de test, soit une marge d'environ ±9 points sur l'exactitude ; un seul annotateur (moi) ; un seul LLM, petit, testé ; la moitié de test contient plus d'annonces sans modèle (58) que la moitié d'ajustement (46).

## Utilisation

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt          # Windows (macOS/Linux : .venv/bin/pip)

python scripts/evaluer.py regle --partie test --seuil 100   # rejoue une mesure
python scripts/evaluer.py ollama --partie dev               # appelle Ollama (ollama pull qwen2.5:3b)
python -m pytest

uvicorn rapprochement.api:app --app-dir src --port 8000    # API : POST /rapprocher {"nom", "marque", "annee"}
docker build -t rapprochement . && docker run -p 8000:8000 rapprochement
```

L'intégration continue ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) lance les tests, rejoue l'évaluation sur la moitié de test à partir du cache, échoue si une méthode passe sous ses références ([`eval/reference.json`](eval/reference.json)), puis construit l'image Docker.

## Structure

```
src/rapprochement/   candidats.py (normalisation, candidats, baseline, règle de version), llm.py (Ollama, API Claude optionnelle, cache), api.py
scripts/             exporter_donnees.py, preparer_annotation.py, annoter.py, chercher_catalogue.py, evaluer.py, verifier_non_regression.py
data/                catalogue.parquet (3 422 modèles-années), annonces.parquet (les 200 annonces annotées, sur 1 856 collectées le 15/11/2026 ; le fichier complet reste local)
eval/                annotations.csv, decoupage.csv, cache/, resultats/, reference.json
```

## Méthode de travail

Développé avec l'aide de Claude Code. La question, l'annotation des 200 annonces, le découpage ajustement / test et l'interprétation des résultats sont les miens.
