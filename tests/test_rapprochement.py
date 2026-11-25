import json
import sys
from pathlib import Path

import pandas as pd
import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "scripts"))

from rapprochement import llm  # noqa: E402
from rapprochement.candidats import Candidat, Catalogue, baseline, nom_modele, normaliser  # noqa: E402
from evaluer import calculer_scores, cle_modele_seul, verite  # noqa: E402


@pytest.fixture
def catalogue():
    return Catalogue(pd.DataFrame([
        {"cle_modele": "Scott | E-Spark 720 | 2018", "marque": "Scott", "modele": "E-Spark 720", "annee_modele": 2018, "type_velo": "VTT"},
        {"cle_modele": "Mondraker | Crafty R | 2024", "marque": "Mondraker", "modele": "Crafty R", "annee_modele": 2024, "type_velo": "VTT"},
        {"cle_modele": "Mondraker | CRAFTY XR | 2024", "marque": "Mondraker", "modele": "CRAFTY XR", "annee_modele": 2024, "type_velo": "VTT"},
    ]))


def test_normaliser_et_nom_modele():
    assert normaliser("Riese & Müller") == "riese muller"
    assert nom_modele("Mondraker CRAFTY R 2023 2023", "Mondraker") == "crafty r"


def test_candidats_meme_marque_seulement(catalogue):
    assert catalogue.candidats("Trek Rail 5", "Trek", 2022) == []
    c = catalogue.candidats("Mondraker CRAFTY R 2023", "Mondraker", 2023)
    assert c[0].cle_modele == "Mondraker | Crafty R | 2024"


def test_baseline_seuil(catalogue):
    assert baseline(catalogue, "Mondraker CRAFTY R 2023", "Mondraker", 2023, seuil=90) == "Mondraker | Crafty R | 2024"
    assert baseline(catalogue, "Mondraker Dune R 2024", "Mondraker", 2024, seuil=90) is None


def test_verite_et_cles():
    ligne = pd.Series({"choix": "1", "cand1": "Mondraker | Crafty R | 2024 (100)"})
    assert verite(ligne) == "mondraker|crafty r"
    assert verite(pd.Series({"choix": "0"})) is None
    assert verite(pd.Series({"choix": "Scott | E-Spark 720"})) == "scott|e spark 720"
    assert cle_modele_seul("Cube | Cube Reaction Hybrid One 750 | 2023") == cle_modele_seul("Cube | Reaction Hybrid One")
    assert cle_modele_seul("Scott | E-Spark 720 | 2018") == cle_modele_seul("Scott | E-Spark 720")


def test_scores():
    s = calculer_scores(["a", "b", None, None], ["a", None, None, "c"])
    assert s.exactitude == 0.5 and s.precision == 0.5 and s.rappel == 0.5 and s.aucun_juste == 0.5


def test_llm_interpretation_et_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "CACHE", tmp_path)
    cands = [Candidat("Scott | E-Spark 720 | 2018", "E-Spark 720", 2018, 96.0)]

    class Faux(llm.Fournisseur):
        nom = "faux"
        appels = 0

        def _appeler(self, message, systeme, schema):
            Faux.appels += 1
            return {"texte": json.dumps({"choix": 0, "confiance": "haute", "raison": "730 ≠ 720"}),
                    "tokens_entree": 100, "tokens_sortie": 20, "arret": "end_turn"}

    f = Faux("modele-test")
    r1 = f.decider("Scott E-Spark 730 2018", "Scott", 2018, cands)
    r2 = f.decider("Scott E-Spark 730 2018", "Scott", 2018, cands)
    assert r1.cle_modele is None and r1.decision.choix == 0
    assert r2.depuis_cache and Faux.appels == 1
    assert Faux("modele-test", hors_ligne=True).decider("autre", "Scott", 2018, cands).erreur


def test_llm_reponse_invalide():
    f = llm.Fournisseur("x")
    cands = [Candidat("A | B | 2020", "B", 2020, 90.0)]
    assert f._interpreter({"texte": "pas du json"}, cands, False).erreur
    assert f._interpreter({"texte": json.dumps({"choix": 5, "confiance": "haute", "raison": ""})}, cands, False).erreur
    assert f._interpreter({"arret": "refusal"}, cands, False).erreur == "refus du modèle"
