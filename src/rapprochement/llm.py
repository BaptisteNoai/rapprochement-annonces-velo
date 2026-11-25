"""Décision par LLM : parmi les candidats du catalogue, lequel est le même modèle que l'annonce (ou aucun).

Deux fournisseurs, même prompt et même schéma de sortie :
- Anthropic (API Claude) : sortie JSON contrainte par `output_config.format`, validée par Pydantic ;
- Ollama (modèle local) : sortie JSON contrainte par le champ `format`, validée par Pydantic.

Chaque réponse est mise en cache sur disque (eval/cache/), clé = hachage du fournisseur, du modèle et du prompt :
une évaluation relancée, ou lancée en intégration continue, ne refait aucun appel payant.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from .candidats import Candidat

RACINE = Path(__file__).resolve().parents[2]
CACHE = RACINE / "eval" / "cache"
VERSION_PROMPT = "v1"  # à changer quand le prompt change : invalide le cache

# Prix publics en dollars par million de tokens (entrée, sortie), relevés le 24/11/2026
PRIX = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}

SYSTEME = """Tu rapproches une annonce de vélo électrique d'occasion d'un catalogue de modèles.

On te donne l'annonce (nom, marque, année) et une liste numérotée de modèles candidats du catalogue, tous de la même marque.
Choisis le candidat qui est le même modèle que l'annonce, ou 0 si aucun ne l'est.

Même modèle = même gamme et même version ou finition. Exemples : « E-Spark 720 » et « E-Spark 730 » sont deux modèles différents ; « Rail 9.8 » et « Rail 5 » aussi ; « Turbo Vado 4.0 » et « Turbo Vado 5.0 » aussi.
Ignore l'année, la taille, la couleur, le type de cadre (« Step-Through », « trapèze ») et les mentions de vitesse (« 20mph »).
Si plusieurs candidats sont le même modèle avec des années différentes, choisis celui dont l'année est la plus proche de l'annonce.
Si tu n'es pas sûr qu'un candidat soit exactement la même version, réponds 0 : un faux rapprochement fausse les prix plus qu'un rapprochement manqué.

Réponds avec : choix (numéro du candidat, ou 0), confiance (haute, moyenne ou basse), raison (une phrase courte)."""


class Decision(BaseModel):
    choix: int = Field(description="numéro du candidat retenu, ou 0 si aucun")
    confiance: Literal["haute", "moyenne", "basse"]
    raison: str


SCHEMA = {
    "type": "object",
    "properties": {
        "choix": {"type": "integer", "description": "numéro du candidat retenu, ou 0 si aucun"},
        "confiance": {"type": "string", "enum": ["haute", "moyenne", "basse"]},
        "raison": {"type": "string"},
    },
    "required": ["choix", "confiance", "raison"],
    "additionalProperties": False,
}


SYSTEME_VERIF = """Tu vérifies si une annonce de vélo électrique d'occasion correspond exactement à un modèle d'un catalogue.

Même modèle = même gamme et même version ou finition : mêmes numéros (« E-Spark 720 » ≠ « E-Spark 730 », « Rail 9.8 » ≠ « Rail 9.7 ») et mêmes mots de finition (« TM » ≠ « Race », « XT » ≠ « GX AXS », « Comp » ≠ « Expert » ; « FS » change le modèle).
Ignore l'année, la taille, la couleur, le type de cadre, la capacité de batterie (625 Wh…) et la taille de roue (27.5, 29).
Si l'annonce contient un mot de version absent du modèle du catalogue, ou l'inverse, ce n'est pas le même modèle.
En cas de doute, réponds non : un faux rapprochement fausse les prix plus qu'un rapprochement manqué.

Réponds avec : meme_modele (true ou false), raison (une phrase courte)."""


class Verification(BaseModel):
    meme_modele: bool
    raison: str


SCHEMA_VERIF = {
    "type": "object",
    "properties": {"meme_modele": {"type": "boolean"}, "raison": {"type": "string"}},
    "required": ["meme_modele", "raison"],
    "additionalProperties": False,
}


def construire_message(nom: str, marque: str, annee: int | None, candidats: list[Candidat]) -> str:
    lignes = [f"Annonce : {nom}", f"Marque : {marque}", f"Année : {annee if annee is not None else 'inconnue'}", "", "Candidats :"]
    for i, c in enumerate(candidats, 1):
        lignes.append(f"{i}. {c.cle_modele}")
    return "\n".join(lignes)


@dataclass
class Resultat:
    cle_modele: str | None       # None = aucun
    decision: Decision | None    # None si la réponse était inexploitable
    tokens_entree: int = 0
    tokens_sortie: int = 0
    cout_usd: float = 0.0
    latence_s: float = 0.0
    depuis_cache: bool = False
    erreur: str | None = None
    brut: dict = field(default_factory=dict)


def _cle_cache(fournisseur: str, modele: str, message: str, systeme: str = SYSTEME) -> Path:
    h = hashlib.sha256(f"{VERSION_PROMPT}\n{fournisseur}\n{modele}\n{systeme}\n{message}".encode()).hexdigest()[:24]
    return CACHE / f"{fournisseur}_{modele.replace(':', '-').replace('/', '-')}" / f"{h}.json"


class Fournisseur:
    nom = "abstrait"

    def __init__(self, modele: str, hors_ligne: bool = False):
        self.modele = modele
        self.hors_ligne = hors_ligne  # True : cache seulement (intégration continue), aucun appel réseau

    def _appeler(self, message: str, systeme: str, schema: dict) -> dict:  # {"texte", "tokens_entree", "tokens_sortie", "arret"}
        raise NotImplementedError

    def _obtenir(self, message: str, systeme: str, schema: dict) -> tuple[dict | None, bool]:
        """Réponse brute depuis le cache, ou par un appel (mise en cache). None en mode hors ligne sans cache."""
        chemin = _cle_cache(self.nom, self.modele, message, systeme)
        if chemin.exists():
            return json.loads(chemin.read_text(encoding="utf-8")), True
        if self.hors_ligne:
            return None, False
        t0 = time.perf_counter()
        brut = self._appeler(message, systeme, schema)
        brut["latence_s"] = round(time.perf_counter() - t0, 3)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(brut, ensure_ascii=False, indent=1), encoding="utf-8")
        return brut, False

    def decider(self, nom: str, marque: str, annee: int | None, candidats: list[Candidat]) -> Resultat:
        if not candidats:
            return Resultat(None, Decision(choix=0, confiance="haute", raison="aucun modèle de cette marque"))
        brut, depuis_cache = self._obtenir(construire_message(nom, marque, annee, candidats), SYSTEME, SCHEMA)
        if brut is None:
            return Resultat(None, None, erreur="absent du cache (mode hors ligne)")
        return self._interpreter(brut, candidats, depuis_cache)

    def verifier(self, nom: str, marque: str, annee: int | None, candidat: Candidat) -> Resultat:
        """Vérification binaire : l'annonce est-elle le même modèle que ce candidat ? cle_modele = candidat si oui."""
        message = (f"Annonce : {nom}\nMarque : {marque}\nAnnée : {annee if annee is not None else 'inconnue'}\n\n"
                   f"Modèle du catalogue : {candidat.cle_modele}")
        brut, depuis_cache = self._obtenir(message, SYSTEME_VERIF, SCHEMA_VERIF)
        if brut is None:
            return Resultat(None, None, erreur="absent du cache (mode hors ligne)")
        entree, sortie = brut.get("tokens_entree", 0), brut.get("tokens_sortie", 0)
        pe, ps = PRIX.get(self.modele, (0.0, 0.0))
        res = Resultat(None, None, entree, sortie, (entree * pe + sortie * ps) / 1e6,
                       brut.get("latence_s", 0.0), depuis_cache, brut=brut)
        try:
            v = Verification.model_validate_json(brut.get("texte") or "")
        except ValidationError as e:
            res.erreur = f"réponse invalide : {e.errors()[0]['msg']}"
            return res
        res.decision = Decision(choix=1 if v.meme_modele else 0, confiance="haute", raison=v.raison)
        res.cle_modele = candidat.cle_modele if v.meme_modele else None
        return res

    def _interpreter(self, brut: dict, candidats: list[Candidat], depuis_cache: bool) -> Resultat:
        entree, sortie = brut.get("tokens_entree", 0), brut.get("tokens_sortie", 0)
        pe, ps = PRIX.get(self.modele, (0.0, 0.0))
        res = Resultat(None, None, entree, sortie, (entree * pe + sortie * ps) / 1e6,
                       brut.get("latence_s", 0.0), depuis_cache, brut=brut)
        if brut.get("arret") == "refusal":
            res.erreur = "refus du modèle"
            return res
        try:
            d = Decision.model_validate_json(brut.get("texte") or "")
        except ValidationError as e:
            res.erreur = f"réponse invalide : {e.errors()[0]['msg']}"
            return res
        if not 0 <= d.choix <= len(candidats):
            res.erreur = f"choix hors limites : {d.choix}"
            return res
        res.decision = d
        res.cle_modele = candidats[d.choix - 1].cle_modele if d.choix else None
        return res


class Anthropic(Fournisseur):
    """API Claude. Clé lue par le SDK (variable ANTHROPIC_API_KEY, ou profil `ant auth login`)."""

    nom = "anthropic"

    def __init__(self, modele: str = "claude-opus-5-5", effort: str = "low", hors_ligne: bool = False):
        super().__init__(modele, hors_ligne)
        self.effort = effort
        self._client = None

    def _appeler(self, message: str, systeme: str, schema: dict) -> dict:
        import anthropic

        if self._client is None:
            self._client = anthropic.Anthropic()
        r = self._client.messages.create(
            model=self.modele,
            max_tokens=4000,  # la réflexion (toujours active sur ce modèle) compte dans ce plafond
            system=systeme,
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": message}],
        )
        texte = next((b.text for b in r.content if b.type == "text"), "")
        return {"texte": texte, "tokens_entree": r.usage.input_tokens, "tokens_sortie": r.usage.output_tokens,
                "arret": r.stop_reason, "id_requete": r._request_id}


class Ollama(Fournisseur):
    """Modèle local servi par Ollama (http://localhost:11434). Gratuit : coût compté à 0."""

    nom = "ollama"

    def __init__(self, modele: str = "qwen2.5:3b", url: str | None = None, hors_ligne: bool = False):
        super().__init__(modele, hors_ligne)
        self.url = url or os.environ.get("OLLAMA_URL", "http://localhost:11434")

    def _appeler(self, message: str, systeme: str, schema: dict) -> dict:
        import requests

        r = requests.post(f"{self.url}/api/chat", timeout=300, json={
            "model": self.modele,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": systeme}, {"role": "user", "content": message}],
        })
        r.raise_for_status()
        d = r.json()
        return {"texte": d.get("message", {}).get("content", ""), "tokens_entree": d.get("prompt_eval_count", 0),
                "tokens_sortie": d.get("eval_count", 0), "arret": d.get("done_reason")}
