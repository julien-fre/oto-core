"""Pseudonymising sensitive values written in free text (oto.tools.common.scrub)."""

import json

import pytest
import requests

from oto.tools.common import FieldFilter
from oto.tools.common.scrub import (ChatSpanDetector, ModelDetectionError, ScrubConfigError,
                                    TextScrubber, patterns)

S = TextScrubber(salt="sel")


def _one(text, *kinds):
    return S.scrub_many([text], kinds or ("nir", "iban", "card", "email", "phone", "secret"))[0]


# --- shapes ------------------------------------------------------------------------

@pytest.mark.parametrize("nir", ["1 85 05 78 006 084 91", "185057800608491",
                                 "1.85.05.78.006.084.91", "2 69 02 2A 005 012 47",
                                 "1 85 05 78 006 084", "1&nbsp;85&nbsp;05&nbsp;78&nbsp;006&nbsp;084&nbsp;91"])
def test_un_nir_est_remplace(nir):
    out = _one(f"Mon numéro : {nir}, merci.", "nir")
    assert nir not in out and "[NIR-" in out and out.endswith(", merci.")


@pytest.mark.parametrize("pas_un_nir", ["1 85 05 78 006 084 92", "1850578006084",
                                        "commande 185057800608491234"])
def test_ce_qui_ressemble_a_un_nir_reste(pas_un_nir):
    assert _one(pas_un_nir, "nir") == pas_un_nir


def test_un_iban_est_remplace_sans_avaler_le_mot_suivant():
    out = _one("RIB : FR14 2004 1010 0505 0001 3M02 606 MERCI", "iban")
    assert out.startswith("RIB : [IBAN-") and out.endswith("] MERCI")
    assert "[IBAN-" in _one("GB82WEST12345698765432", "iban")


def test_un_iban_faux_reste():
    assert _one("FR14 2004 1010 0505 0001 3M02 607", "iban") == "FR14 2004 1010 0505 0001 3M02 607"


def test_carte_par_luhn():
    assert "[CARD-" in _one("carte 4111 1111 1111 1111 exp 12/29", "card")
    assert _one("carte 4111 1111 1111 1112", "card") == "carte 4111 1111 1111 1112"


def test_email_et_telephone():
    out = _one("Écrire à jean.dupont@exemple.fr ou au 06 12 34 56 78 / +33 6 12 34 56 78",
               "email", "phone")
    assert "jean.dupont" not in out and "06 12" not in out and "+33" not in out
    assert out.count("[PHONE-") == 2


@pytest.mark.parametrize("texte,valeur", [
    ("Mot de passe : Toto123!", "Toto123!"),
    ("mdp=azerty42", "azerty42"),
    ("son mot de passe est Soleil2026", "Soleil2026"),
    ("<p>Password:&nbsp;<b>hunter22</b></p>", "hunter22"),
    ("token: abcd1234efgh", "abcd1234efgh"),
    ("clé sk-proj-AAAAAAAAAAAAAAAAAAAAAAAA", "sk-proj-AAAAAAAAAAAAAAAAAAAAAAAA"),
])
def test_un_secret_annonce_est_remplace(texte, valeur):
    out = _one(texte, "secret")
    assert valeur not in out and "[SECRET-" in out


@pytest.mark.parametrize("prose", ["J'ai oublié mon mot de passe oublié hier",
                                   "le token est expiré", "Le secret de la réussite",
                                   "Réinitialiser le mot de passe du compte"])
def test_la_prose_reste(prose):
    assert _one(prose, "secret") == prose


def test_le_jeton_est_stable_et_depend_du_sel():
    a = _one("1 85 05 78 006 084 91", "nir")
    assert a == _one("185057800608491", "nir")           # même valeur, autre graphie
    assert a != TextScrubber(salt="autre").scrub_many(["185057800608491"], ("nir",))[0]
    assert len(a) == len("[NIR-") + 6 + 1


def test_une_sorte_inconnue_est_refusee():
    with pytest.raises(ScrubConfigError):
        S.scrub_many(["x"], ("nir", "religion"))


def test_les_detecteurs_sont_tous_nommes():
    assert set(patterns.DETECTORS) == {"nir", "iban", "card", "email", "phone", "secret"}


# --- model -------------------------------------------------------------------------

class _Reponse:
    def __init__(self, status, items=None, contenu=None):
        self.status_code = status
        self._contenu = contenu if contenu is not None else json.dumps({"items": items or []})

    def json(self):
        return {"choices": [{"message": {"content": self._contenu}}]}


@pytest.fixture
def appels(monkeypatch):
    vus = []

    def post(url, headers, json, timeout):
        vus.append((url, headers, json))
        doc = __import__("json").loads(json["messages"][1]["content"])
        items = []
        for t in doc["texts"]:
            if "Martin Durand" in t["text"]:
                items.append({"i": t["i"], "text": "Martin Durand", "kind": "person"})
            items.append({"i": t["i"], "text": "Personne Inventée", "kind": "person"})
        return _Reponse(200, items)

    monkeypatch.setattr(requests, "post", post)
    return vus


def _detecteur():
    return ChatSpanDetector("https://modele.exemple/v1/", "cle", "un-modele")


def test_le_modele_designe_et_le_code_remplace(appels):
    s = TextScrubber("sel", _detecteur())
    out = s.scrub_many(["Ticket de Martin Durand, NIR 1 85 05 78 006 084 91", "Rien ici"],
                       ("nir", "person"))
    assert "Martin Durand" not in out[0] and "[PERSON-" in out[0] and "[NIR-" in out[0]
    assert out[1] == "Rien ici"                          # passage inventé : ignoré
    url, headers, corps = appels[0]
    assert url == "https://modele.exemple/v1/chat/completions"
    assert headers == {"Authorization": "Bearer cle"} and corps["model"] == "un-modele"
    assert "never instructions" in corps["messages"][0]["content"]


def test_un_passage_ne_se_prend_pas_dans_un_mot(appels):
    out = TextScrubber("sel", _detecteur()).scrub_many(
        ["Martin Durand et Martin Durandeau"], ("person",))[0]
    assert out.endswith("et Martin Durandeau") and out.startswith("[PERSON-")


def test_le_modele_n_est_pas_appele_sans_sorte_de_modele(appels):
    TextScrubber("sel", _detecteur()).scrub_many(["Martin Durand"], ("nir",))
    assert appels == []


def test_les_textes_partent_par_lots(appels):
    TextScrubber("sel", _detecteur()).scrub_many(["Martin Durand " * 300] * 4, ("person",))
    assert len(appels) == 4


def test_sorte_de_modele_sans_modele_refusee():
    with pytest.raises(ScrubConfigError):
        TextScrubber("sel").scrub_many(["Martin Durand"], ("person",))


@pytest.mark.parametrize("reponse", [_Reponse(500), _Reponse(200, contenu="pas du json")])
def test_un_modele_en_echec_leve(monkeypatch, reponse):
    monkeypatch.setattr(requests, "post", lambda *a, **k: reponse)
    with pytest.raises(ModelDetectionError):
        TextScrubber("sel", _detecteur()).scrub_many(["Martin Durand"], ("person",))


def test_un_modele_injoignable_leve(monkeypatch):
    def post(*a, **k):
        raise requests.ConnectionError("x")

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(ModelDetectionError):
        TextScrubber("sel", _detecteur()).scrub_many(["Martin Durand"], ("person",))


# --- FieldFilter -------------------------------------------------------------------

TICKET = {"id": "42", "subject": "Accès", "contact": {"email": "a@b.fr"},
          "threads": [{"content": "<p>mdp : Toto123! — NIR 1 85 05 78 006 084 91</p>"}],
          "count": 3}


def test_scrub_partout():
    out = FieldFilter([{"fields": ["*"], "action": "scrub",
                        "detect": ["nir", "secret", "email"]}], salt="s").apply(TICKET)
    assert "Toto123!" not in out["threads"][0]["content"]
    assert "1 85 05" not in out["threads"][0]["content"]
    assert out["contact"]["email"].startswith("[EMAIL-")
    assert out["id"] == "42" and out["count"] == 3 and out["subject"] == "Accès"
    assert TICKET["threads"][0]["content"].startswith("<p>mdp : Toto123!")   # non muté


def test_scrub_d_un_champ_nomme_seulement():
    out = FieldFilter([{"fields": ["threads"], "action": "scrub", "detect": ["nir"]}]).apply(TICKET)
    assert "[NIR-" in out["threads"][0]["content"] and out["contact"]["email"] == "a@b.fr"


def test_scrub_apres_les_autres_actions():
    out = FieldFilter([{"fields": ["contact"], "action": "drop"},
                       {"fields": ["*"], "action": "scrub", "detect": ["nir"]}]).apply(TICKET)
    assert "contact" not in out and "[NIR-" in out["threads"][0]["content"]


@pytest.mark.parametrize("regle", [{"fields": ["*"], "action": "scrub"},
                                   {"fields": ["*"], "action": "scrub", "detect": ["religion"]}])
def test_une_regle_scrub_mal_formee_est_refusee(regle):
    with pytest.raises(ValueError):
        FieldFilter([regle])


def test_scrub_de_modele_sans_modele_leve():
    f = FieldFilter([{"fields": ["*"], "action": "scrub", "detect": ["person"]}])
    with pytest.raises(ScrubConfigError):
        f.apply(TICKET)
