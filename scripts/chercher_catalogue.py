"""Cherche un modèle dans le catalogue, pour l'annotation.

Usage : python scripts/chercher_catalogue.py turbo vado 4.0
Affiche les modèles dont le nom contient tous les mots donnés (sans tenir compte des accents ni de la casse).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
from rapprochement.candidats import normaliser  # noqa: E402


def main() -> None:
    mots = [normaliser(m) for m in sys.argv[1:]]
    if not mots:
        sys.exit(__doc__)
    cat = pd.read_parquet(RACINE / "data" / "catalogue.parquet")
    texte = (cat["marque"].fillna("") + " " + cat["modele"].fillna("")).map(normaliser)
    trouves = cat[texte.map(lambda t: all(m in t for m in mots))]
    vus = trouves.drop_duplicates(["marque", "modele"])
    for r in vus.itertuples():
        print(f"{r.marque} | {r.modele}")
    print(f"({len(vus)} modèles)")


if __name__ == "__main__":
    main()
