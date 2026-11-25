"""API de rapprochement : une annonce en entrée, le modèle du catalogue en sortie (ou aucun).

Lancement local :  uvicorn rapprochement.api:app --app-dir src --port 8000
Méthode choisie par la variable METHODE : « regle » (par défaut, sans LLM), « baseline » ou « ollama » (OLLAMA_URL, OLLAMA_MODELE).
"""
from __future__ import annotations

import os
from functools import lru_cache

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .candidats import Catalogue, baseline, regle
from .llm import Ollama

app = FastAPI(title="Rapprochement d'annonces de vélos électriques", version="0.1.0")


class Annonce(BaseModel):
    nom: str = Field(examples=["Trek Powerfly 5 2020"])
    marque: str = Field(examples=["Trek"])
    annee: int | None = Field(default=None, examples=[2020])


class CandidatSortie(BaseModel):
    cle_modele: str
    score: float


class Reponse(BaseModel):
    cle_modele: str | None
    methode: str
    confiance: str | None = None
    raison: str | None = None
    candidats: list[CandidatSortie]


@lru_cache
def catalogue() -> Catalogue:
    return Catalogue.charger()


@lru_cache
def fournisseur() -> Ollama:
    return Ollama(os.environ.get("OLLAMA_MODELE", "qwen2.5:3b"))


@app.get("/sante")
def sante() -> dict:
    return {"statut": "ok", "methode": os.environ.get("METHODE", "regle")}


@app.post("/rapprocher", response_model=Reponse)
def rapprocher(a: Annonce) -> Reponse:
    methode = os.environ.get("METHODE", "regle")
    cands = catalogue().candidats(a.nom, a.marque, a.annee, k=10)
    sortie = [CandidatSortie(cle_modele=c.cle_modele, score=round(c.score, 1)) for c in cands[:5]]
    if methode == "ollama":
        r = fournisseur().decider(a.nom, a.marque, a.annee, cands)
        return Reponse(cle_modele=r.cle_modele, methode=f"ollama:{fournisseur().modele}",
                       confiance=r.decision.confiance if r.decision else None,
                       raison=r.decision.raison if r.decision else r.erreur, candidats=sortie)
    seuil = float(os.environ.get("SEUIL", "100"))
    fonction = baseline if methode == "baseline" else regle  # règle de version par défaut : la meilleure au test
    nom = "baseline" if methode == "baseline" else "regle"
    return Reponse(cle_modele=fonction(catalogue(), a.nom, a.marque, a.annee, seuil=seuil),
                   methode=f"{nom}:{seuil:g}", candidats=sortie)
