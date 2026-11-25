import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rapprochement.api import app  # noqa: E402

client = TestClient(app)


def test_sante():
    assert client.get("/sante").json()["statut"] == "ok"


def test_rapprocher_baseline(monkeypatch):
    monkeypatch.setenv("METHODE", "baseline")
    r = client.post("/rapprocher", json={"nom": "Trek Powerfly 7 2020", "marque": "Trek", "annee": 2020})
    assert r.status_code == 200
    corps = r.json()
    assert corps["methode"].startswith("baseline")
    assert corps["candidats"] and "Powerfly 7" in corps["candidats"][0]["cle_modele"]


def test_marque_inconnue():
    r = client.post("/rapprocher", json={"nom": "Fuji E-Jari 2021", "marque": "Fuji", "annee": 2021})
    assert r.json()["cle_modele"] is None and r.json()["candidats"] == []
