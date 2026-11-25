"""Annotation au clavier de eval/a_annoter.csv, une annonce à la fois. Sauvegarde après chaque réponse.

Usage : python scripts/annoter.py

Réponses possibles :
  1 à 5          le candidat n°1 à 5 est le même modèle
  0              le modèle n'est pas dans le catalogue
  ? mots         chercher dans le catalogue (ex. « ? turbo vado »), puis choisir un résultat par son numéro
  o              ouvrir l'annonce dans le navigateur
  r texte        ajouter une remarque (cas douteux), puis répondre
  p              revenir à l'annonce précédente
  q              quitter (tout est déjà sauvegardé ; on reprend là où on s'est arrêté)
"""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
from rapprochement.candidats import normaliser  # noqa: E402

FICHIER = RACINE / "eval" / "a_annoter.csv"


def chercher(cat: pd.DataFrame, texte: str) -> list[str]:
    mots = [normaliser(m) for m in texte.split()]
    nom = (cat["marque"].fillna("") + " " + cat["modele"].fillna("")).map(normaliser)
    t = cat[nom.map(lambda s: all(m in s for m in mots))].drop_duplicates(["marque", "modele"])
    return [f"{r.marque} | {r.modele}" for r in t.itertuples()][:30]


def main() -> None:
    try:
        with FICHIER.open("a"):
            pass
    except PermissionError:
        sys.exit("eval/a_annoter.csv est ouvert dans un autre programme (Excel ?) : ferme-le puis relance.")
    df = pd.read_csv(FICHIER, sep=";", dtype=str, encoding="utf-8-sig").fillna("")
    cat = pd.read_parquet(RACINE / "data" / "catalogue.parquet")
    a_faire = [i for i in df.index if df.at[i, "choix"] == ""]
    if not a_faire:
        print("Tout est annoté. Renomme eval/a_annoter.csv en eval/annotations.csv.")
        return
    pos = 0
    while pos < len(a_faire):
        i = a_faire[pos]
        r = df.loc[i]
        fait = (df["choix"] != "").sum()
        print("\n" + "=" * 70)
        print(f"[{fait}/{len(df)} annotées]  {r['nom']}   (marque : {r['marque']}, année : {r['annee'] or '?'})")
        for k in range(1, 6):
            if r[f"cand{k}"]:
                print(f"  {k}. {r[f'cand{k}']}")
        if not any(r[f"cand{k}"] for k in range(1, 6)):
            print("  (aucun candidat de cette marque dans le catalogue)")
        if r["remarque"]:
            print(f"  remarque : {r['remarque']}")
        rep = input("> ").strip()
        if rep == "q":
            break
        if rep == "p":
            pos = max(0, pos - 1)
            df.at[a_faire[pos], "choix"] = ""
            continue
        if rep == "o":
            webbrowser.open(r["url"])
            continue
        if rep.startswith("r "):
            df.at[i, "remarque"] = rep[2:].strip()
            df.to_csv(FICHIER, sep=";", index=False, encoding="utf-8-sig")
            continue
        if rep.startswith("?"):
            res = chercher(cat, rep[1:])
            if not res:
                print("  rien trouvé")
                continue
            for k, s in enumerate(res, 1):
                print(f"  {k}. {s}")
            n = input("  numéro du bon modèle (Entrée pour annuler) > ").strip()
            if n.isdigit() and 1 <= int(n) <= len(res):
                df.at[i, "choix"] = res[int(n) - 1]
            else:
                continue
        elif rep in {"0", "1", "2", "3", "4", "5"}:
            if rep != "0" and not r[f"cand{rep}"]:
                print("  ce candidat n'existe pas")
                continue
            df.at[i, "choix"] = rep
        else:
            print(__doc__.split("Réponses possibles :")[1])
            continue
        df.to_csv(FICHIER, sep=";", index=False, encoding="utf-8-sig")
        pos += 1
    restantes = (df["choix"] == "").sum()
    print(f"\nSauvegardé. Reste {restantes} annonce(s)." + ("" if restantes else " Renomme le fichier en annotations.csv."))


if __name__ == "__main__":
    main()
