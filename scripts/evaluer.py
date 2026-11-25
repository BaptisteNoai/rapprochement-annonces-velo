"""Évalue une méthode de rapprochement sur le jeu annoté (eval/annotations.csv).

Méthodes :
    baseline   similarité de chaînes, meilleur candidat au-dessus d'un seuil (balayage des seuils)
    regle      baseline + numéros de version identiques (balayage des seuils)
    ollama     le LLM local choisit parmi 10 candidats (ou aucun)
    anthropic  idem avec l'API Claude (optionnel, payant)
    verif      le LLM vérifie le meilleur candidat (oui / non), sans règle
    hybride    règle de version, puis le LLM vérifie jusqu'à 2 candidats compatibles

Exemples :
    python scripts/evaluer.py regle --partie dev
    python scripts/evaluer.py hybride --partie test
Options : --partie dev|test|tout (découpage fixe d'eval/decoupage.csv ; on ajuste sur dev, on mesure une fois sur test),
          --seuil, --modele, --limite N, --hors-ligne (réponses LLM du cache seulement, aucun appel).

La comparaison se fait au niveau du modèle (marque + modèle), sans l'année : c'est ce qu'annote l'humain.
Sorties : eval/resultats/<méthode>_<partie>.json, eval/resultats/erreurs_<méthode>_<partie>.csv, ligne dans eval/resultats.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
from rapprochement.candidats import Catalogue, baseline, normaliser_marque, regle, signature, versions_compatibles  # noqa: E402

SORTIES = RACINE / "eval" / "resultats"
SEUILS = [60, 65, 70, 75, 80, 85, 90, 95, 100]


def cle_modele_seul(cle: str | None) -> str | None:
    """« Marque | Modèle | Année » ou « Marque | Modèle » -> clé de comparaison sans l'année.

    Deux entrées du catalogue qui ne diffèrent que par la capacité de batterie, la taille de roue ou la marque
    répétée dans le nom (« Cube | Cube Reaction Hybrid Race ») comptent comme le même modèle, comme le demande
    la consigne d'annotation (eval/README.md). Correction appliquée à toutes les méthodes le 24/11/2026.
    """
    if not cle or str(cle).strip() in {"", "0", "nan"}:
        return None
    morceaux = [m.strip() for m in str(cle).split("|")]
    if len(morceaux) < 2:
        return None
    return f"{normaliser_marque(morceaux[0])}|{signature(morceaux[1], morceaux[0])}"


def verite(ligne: pd.Series) -> str | None:
    """Réponse de l'annotateur : 1-5 -> candidat correspondant, 0 -> aucun, sinon « Marque | Modèle » saisi."""
    choix = str(ligne["choix"]).strip()
    if choix in {"1", "2", "3", "4", "5"}:
        cand = str(ligne[f"cand{choix}"])
        return cle_modele_seul(cand.rsplit(" (", 1)[0])  # retire le score « (95) »
    return cle_modele_seul(choix)


@dataclass
class Scores:
    n: int
    exactitude: float          # bonne réponse, « aucun » compris
    precision: float           # parmi les rapprochements proposés, part de justes
    rappel: float              # parmi les annonces qui ont un modèle au catalogue, part retrouvée
    aucun_juste: float         # parmi les annonces sans modèle au catalogue, part où la méthode dit « aucun »
    n_avec_modele: int
    n_sans_modele: int


def calculer_scores(verites: list[str | None], predictions: list[str | None]) -> Scores:
    paires = list(zip(verites, predictions))
    proposes = [(v, p) for v, p in paires if p is not None]
    avec = [(v, p) for v, p in paires if v is not None]
    sans = [(v, p) for v, p in paires if v is None]
    juste = lambda v, p: v == p  # noqa: E731
    div = lambda a, b: round(a / b, 4) if b else float("nan")  # noqa: E731
    return Scores(
        n=len(paires),
        exactitude=div(sum(juste(v, p) for v, p in paires), len(paires)),
        precision=div(sum(juste(v, p) for v, p in proposes), len(proposes)),
        rappel=div(sum(juste(v, p) for v, p in avec), len(avec)),
        aucun_juste=div(sum(p is None for _, p in sans), len(sans)),
        n_avec_modele=len(avec),
        n_sans_modele=len(sans),
    )


def charger(annotations: Path, partie: str, limite: int | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    ann = pd.read_csv(annotations, sep=";", dtype=str, encoding="utf-8-sig").fillna("")
    ann = ann[ann["choix"] != ""]
    if partie != "tout":
        dec = pd.read_csv(RACINE / "eval" / "decoupage.csv", sep=";", dtype=str)
        ann = ann[ann["annonce_id"].isin(dec.loc[dec["partie"] == partie, "annonce_id"])]
    if limite:
        ann = ann.head(limite)
    annonces = pd.read_parquet(RACINE / "data" / "annonces.parquet").set_index("annonce_id")
    return ann.reset_index(drop=True), annonces


def ecrire(methode: str, scores: Scores, extra: dict, erreurs: list[dict]) -> None:
    SORTIES.mkdir(parents=True, exist_ok=True)
    (SORTIES / f"{methode}.json").write_text(
        json.dumps({"date": str(date.today()), "methode": methode, **scores.__dict__, **extra}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    pd.DataFrame(erreurs).to_csv(SORTIES / f"erreurs_{methode}.csv", index=False, sep=";", encoding="utf-8-sig")
    tableau = RACINE / "eval" / "resultats.md"
    if not tableau.exists():
        tableau.write_text("| Date | Méthode | n | Exactitude | Précision | Rappel | « Aucun » juste | Coût / 1 000 annonces | Latence moyenne |\n"
                           "|---|---|---|---|---|---|---|---|---|\n", encoding="utf-8")
    cout = f"{extra['cout_pour_1000_usd']:.2f} $" if "cout_pour_1000_usd" in extra else "0"
    lat = f"{extra['latence_moyenne_s']:.2f} s" if "latence_moyenne_s" in extra else "-"
    with tableau.open("a", encoding="utf-8") as f:
        f.write(f"| {date.today()} | {methode} | {scores.n} | {scores.exactitude:.1%} | {scores.precision:.1%} | "
                f"{scores.rappel:.1%} | {scores.aucun_juste:.1%} | {cout} | {lat} |\n")


def resume_llm(fourn, resultats: list) -> dict:
    ok = [r for r in resultats if r is not None]
    n = max(len(ok), 1)
    return {
        "modele": fourn.modele,
        "appels_llm": len(ok),
        "cout_total_usd": round(sum(r.cout_usd for r in ok), 4),
        "cout_pour_1000_usd": round(1000 * sum(r.cout_usd for r in ok) / n, 3),
        "latence_moyenne_s": round(sum(r.latence_s for r in ok) / n, 3),
        "reponses_invalides": sum(r.erreur is not None for r in ok),
        "nouveaux_appels": sum(bool(r.brut) and not r.depuis_cache and r.erreur is None for r in ok),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("methode", choices=["baseline", "regle", "ollama", "anthropic", "verif", "hybride"])
    p.add_argument("--partie", choices=["dev", "test", "tout"], default="tout")
    p.add_argument("--modele")
    p.add_argument("--effort", default="low", help="effort de l'API Claude (low, medium, high…)")
    p.add_argument("--seuil", type=float, help="baseline / regle / hybride : seuil de similarité")
    p.add_argument("--limite", type=int)
    p.add_argument("--hors-ligne", action="store_true")
    p.add_argument("--annotations", type=Path, default=RACINE / "eval" / "annotations.csv")
    args = p.parse_args()

    if not args.annotations.exists():
        sys.exit(f"{args.annotations} introuvable : terminer l'annotation (voir eval/README.md).")
    ann, annonces = charger(args.annotations, args.partie, args.limite)
    cat = Catalogue.charger()
    verites = [verite(l) for _, l in ann.iterrows()]
    infos = [annonces.loc[i] if i in annonces.index else None for i in ann["annonce_id"]]
    annee = lambda a: None if pd.isna(a["annee"]) else int(a["annee"])  # noqa: E731
    extra: dict = {"partie": args.partie}

    if args.methode in {"baseline", "regle"}:
        fonction = baseline if args.methode == "baseline" else regle
        predire = lambda s: [cle_modele_seul(fonction(cat, a["nom"], a["marque"], annee(a), seuil=s))  # noqa: E731
                             if a is not None else None for a in infos]
        seuils = [args.seuil] if args.seuil is not None else SEUILS
        par_seuil = {s: calculer_scores(verites, predire(s)) for s in seuils}
        for s, sc in par_seuil.items():
            print(f"seuil {s:>5}: exactitude {sc.exactitude:.1%}  précision {sc.precision:.1%}  "
                  f"rappel {sc.rappel:.1%}  aucun juste {sc.aucun_juste:.1%}")
        meilleur = max(seuils, key=lambda s: par_seuil[s].exactitude)
        preds = predire(meilleur)
        extra["seuil"] = meilleur
        nom_methode = f"{args.methode}_seuil{meilleur:g}"
    else:
        from rapprochement.llm import Anthropic, Ollama

        fourn = (Anthropic(args.modele or "claude-opus-5-5", effort=args.effort, hors_ligne=args.hors_ligne)
                 if args.methode == "anthropic" else Ollama(args.modele or "qwen2.5:3b", hors_ligne=args.hors_ligne))
        seuil = args.seuil if args.seuil is not None else 80.0
        preds, resultats = [], []
        for k, a in enumerate(infos, 1):
            if a is None:
                preds.append(None)
                continue
            cands = cat.candidats(a["nom"], a["marque"], annee(a), k=10)
            if args.methode in {"ollama", "anthropic"}:
                r = fourn.decider(a["nom"], a["marque"], annee(a), cands)
                resultats.append(r)
                preds.append(cle_modele_seul(r.cle_modele))
            else:
                if args.methode == "verif":
                    a_verifier = cands[:1]
                else:  # hybride : seulement les candidats aux numéros de version identiques, au-dessus du seuil
                    a_verifier = [c for c in cands if c.score >= seuil and versions_compatibles(a["nom"], c.modele, a["marque"])][:2]
                trouve = None
                for c in a_verifier:
                    r = fourn.verifier(a["nom"], a["marque"], annee(a), c)
                    resultats.append(r)
                    if r.cle_modele:
                        trouve = r.cle_modele
                        break
                preds.append(cle_modele_seul(trouve))
            if k % 20 == 0:
                print(f"  {k}/{len(infos)}")
        extra.update(resume_llm(fourn, resultats))
        if args.methode == "hybride":
            extra["seuil"] = seuil
        nom_methode = f"{args.methode}_{fourn.modele.replace(':', '-')}"
        if args.methode == "anthropic":
            extra["effort"] = args.effort

    nom_methode += f"_{args.partie}"
    sc = calculer_scores(verites, preds)
    erreurs = [{"annonce_id": l["annonce_id"], "nom": l["nom"], "verite": v, "prediction": pr}
               for (_, l), v, pr in zip(ann.iterrows(), verites, preds) if v != pr]
    ecrire(nom_methode, sc, extra, erreurs)
    print(f"\n{nom_methode} : exactitude {sc.exactitude:.1%}, précision {sc.precision:.1%}, rappel {sc.rappel:.1%}, "
          f"« aucun » juste {sc.aucun_juste:.1%} (n = {sc.n} ; {sc.n_avec_modele} avec modèle, {sc.n_sans_modele} sans)")
    if "cout_total_usd" in extra:
        print(f"{extra['appels_llm']} appels au LLM ({extra['nouveaux_appels']} nouveaux), coût {extra['cout_total_usd']} $, "
              f"{extra['reponses_invalides']} réponses invalides")


if __name__ == "__main__":
    main()
