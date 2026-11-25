"""Tire un échantillon d'annonces et prépare la feuille d'annotation (eval/a_annoter.csv).

Pour chaque annonce : ses informations et les 5 meilleurs candidats du catalogue. L'annotateur remplit la
colonne `choix` : 1 à 5 pour le bon candidat, 0 si aucun ne correspond, ou une `cle_modele` exacte du
catalogue si le bon modèle n'est pas dans les 5 (voir eval/README.md).

Usage : python scripts/preparer_annotation.py --n 200 --graine 0
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
from rapprochement.candidats import Catalogue  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=200)
    p.add_argument("--graine", type=int, default=0)
    args = p.parse_args()

    cat = Catalogue.charger()
    annonces = pd.read_parquet(RACINE / "data" / "annonces.parquet")
    echantillon = annonces.sample(n=args.n, random_state=args.graine).reset_index(drop=True)

    lignes = []
    for a in echantillon.itertuples():
        annee = None if pd.isna(a.annee) else int(a.annee)
        cands = cat.candidats(a.nom, a.marque, annee, k=5)
        ligne = {"annonce_id": a.annonce_id, "nom": a.nom, "marque": a.marque, "annee": annee, "url": a.url}
        for i in range(5):
            c = cands[i] if i < len(cands) else None
            ligne[f"cand{i + 1}"] = f"{c.cle_modele} ({c.score:.0f})" if c else ""
        ligne["choix"] = ""
        ligne["remarque"] = ""
        lignes.append(ligne)

    sortie = RACINE / "eval" / "a_annoter.csv"
    if sortie.exists():
        sys.exit(f"{sortie} existe déjà : on ne l'écrase pas (annotations en cours ?)")
    pd.DataFrame(lignes).to_csv(sortie, index=False, encoding="utf-8-sig", sep=";")
    sans = sum(1 for l in lignes if not l["cand1"])
    print(f"{len(lignes)} annonces dans {sortie} ({sans} sans aucun candidat de la même marque)")


if __name__ == "__main__":
    main()
