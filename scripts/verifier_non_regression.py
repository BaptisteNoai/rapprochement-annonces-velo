"""Échoue (code 1) si une méthode évaluée fait moins bien que sa référence (eval/reference.json).

Utilisé par l'intégration continue après `evaluer.py` : un changement de code ou de prompt qui dégrade la précision
ou l'exactitude au-delà de la tolérance bloque la fusion.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
TOLERANCE = 0.01  # 1 point


def main() -> None:
    references = json.loads((RACINE / "eval" / "reference.json").read_text(encoding="utf-8"))
    echec = False
    for methode, ref in references.items():
        chemin = RACINE / "eval" / "resultats" / f"{methode}.json"
        if not chemin.exists():
            print(f"ÉCHEC {methode} : résultat absent ({chemin.name})")
            echec = True
            continue
        res = json.loads(chemin.read_text(encoding="utf-8"))
        for metrique, valeur_ref in ref.items():
            valeur = res[metrique]
            ok = valeur >= valeur_ref - TOLERANCE
            echec |= not ok
            print(f"{'ok   ' if ok else 'ÉCHEC'} {methode} {metrique} : {valeur:.3f} (référence {valeur_ref:.3f})")
    sys.exit(1 if echec else 0)


if __name__ == "__main__":
    main()
