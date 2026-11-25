"""Normalisation des noms et recherche des modèles candidats du catalogue pour une annonce.

Sert à deux choses :
- la baseline : on retient le meilleur candidat si son score dépasse un seuil, sinon « aucun » ;
- l'étape LLM : on lui soumet les meilleurs candidats, il choisit (ou répond « aucun »).

Le catalogue est indexé par marque normalisée : un candidat est toujours de la même marque que l'annonce.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

RACINE = Path(__file__).resolve().parents[2]

# Mots qui n'aident pas à identifier un modèle (tailles, unités, mentions de vente)
MOTS_VIDES = {
    "velo", "electrique", "e-bike", "ebike", "bike", "electric", "pedelec", "vae",
    "homme", "femme", "unisexe", "step", "through", "trapeze", "mixte",
    "20mph", "25km/h", "45km/h", "km", "gesch", "tzt", "geschatzt",
}
ALIAS_MARQUES = {"cube": "cube", "specialized": "specialized", "riese und muller": "riese muller",
                 "riese & muller": "riese muller", "riese & müller": "riese muller"}


def normaliser(texte: str | None) -> str:
    """Minuscules, sans accents ni ponctuation, espaces simples."""
    if not texte:
        return ""
    t = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode()
    t = t.lower().replace("&", " ")
    t = re.sub(r"[^a-z0-9.+ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def normaliser_marque(marque: str | None) -> str:
    m = normaliser(marque)
    return ALIAS_MARQUES.get(m, m)


def nom_modele(nom: str | None, marque: str | None) -> str:
    """Nom d'annonce réduit au modèle : sans la marque, sans les années, sans les mots vides."""
    t = normaliser(nom)
    for mot in normaliser_marque(marque).split():
        t = re.sub(rf"\b{re.escape(mot)}\b", " ", t)
    t = re.sub(r"\b(19|20)\d{2}\b", " ", t)
    mots = [m for m in t.split() if m not in MOTS_VIDES]
    return " ".join(mots)


@dataclass(frozen=True)
class Candidat:
    cle_modele: str
    modele: str
    annee_modele: int | None
    score: float  # similarité de 0 à 100, bonus d'année compris


class Catalogue:
    def __init__(self, df: pd.DataFrame):
        df = df.copy()
        df["marque_n"] = df["marque"].map(normaliser_marque)
        df["modele_n"] = [nom_modele(m, ma) for m, ma in zip(df["modele"], df["marque"])]
        self._par_marque = {m: g.reset_index(drop=True) for m, g in df.groupby("marque_n")}

    @classmethod
    def charger(cls, chemin: Path | None = None) -> "Catalogue":
        return cls(pd.read_parquet(chemin or RACINE / "data" / "catalogue.parquet"))

    def candidats(self, nom: str, marque: str, annee: int | None, k: int = 10) -> list[Candidat]:
        g = self._par_marque.get(normaliser_marque(marque))
        if g is None or g.empty:
            return []
        requete = nom_modele(nom, marque)
        if not requete:
            return []
        scores = process.extract(requete, g["modele_n"].tolist(), scorer=fuzz.token_set_ratio, limit=None)
        resultats = []
        for _, score, i in scores:
            ligne = g.iloc[i]
            a = None if pd.isna(ligne["annee_modele"]) else int(ligne["annee_modele"])
            bonus = 0.0
            if annee is not None and a is not None:
                bonus = 5.0 if a == annee else (-5.0 if abs(a - annee) > 1 else 0.0)
            resultats.append(Candidat(ligne["cle_modele"], ligne["modele"], a, float(score) + bonus))
        resultats.sort(key=lambda c: c.score, reverse=True)
        return resultats[:k]


def baseline(cat: Catalogue, nom: str, marque: str, annee: int | None, seuil: float = 85.0) -> str | None:
    """Meilleur candidat si son score atteint le seuil, sinon None (« aucun »)."""
    c = cat.candidats(nom, marque, annee, k=1)
    return c[0].cle_modele if c and c[0].score >= seuil else None


# ---------------------------------------------------------------------------
# Règle de version : deux noms qui n'ont pas les mêmes numéros ne sont pas le même modèle
# ---------------------------------------------------------------------------
# Nombres qui ne désignent pas la version : tailles de roue, capacités de batterie, vitesses
BRUIT_NUMERIQUE = {"26", "27.5", "28", "29", "700", "700c", "20mph", "28mph"}
CAPACITE_BATTERIE = re.compile(r"^\d{3}(wh)?$")  # 400 à 1000 Wh, testé plus bas


def est_bruit(j: str) -> bool:
    """Taille de roue, vitesse ou capacité de batterie : ne désigne pas la version du modèle."""
    if j in BRUIT_NUMERIQUE:
        return True
    # 500, 625, 750 Wh… ; 720 ou 730 (multiples de 10 non multiples de 25) restent des numéros de modèle
    return bool(CAPACITE_BATTERIE.match(j)) and 400 <= int(j[:3]) <= 1000 and int(j[:3]) % 25 == 0


def signature(nom: str, marque: str) -> str:
    """Nom de modèle sans la marque, les années, les mots vides et le bruit (batterie, roue) : sert à comparer deux noms."""
    return " ".join(j for j in nom_modele(nom, marque).split() if not est_bruit(j))


def jetons_version(nom: str, marque: str) -> set[str]:
    """Jetons du nom de modèle qui contiennent un chiffre (9.8, 730, one44, gen4…), sans le bruit."""
    return {j for j in signature(nom, marque).replace("gen ", "gen").split() if any(ch.isdigit() for ch in j)}


def versions_compatibles(nom_annonce: str, modele_catalogue: str, marque: str) -> bool:
    return jetons_version(nom_annonce, marque) == jetons_version(modele_catalogue, marque)


def regle(cat: "Catalogue", nom: str, marque: str, annee: int | None, seuil: float = 80.0) -> str | None:
    """Meilleur candidat aux numéros de version identiques, si son score atteint le seuil."""
    for c in cat.candidats(nom, marque, annee, k=10):
        if c.score >= seuil and versions_compatibles(nom, c.modele, marque):
            return c.cle_modele
    return None
