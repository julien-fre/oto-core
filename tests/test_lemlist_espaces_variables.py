"""Un espace dans une variable de lead voyage en `%20`, jamais en `+` (backend#860).

Mesuré 4 fois sur 4 le 10/09/2026 sur une campagne réelle :
`{"posteRecrute": "un Traffic Manager"}` était relu `"un+Traffic+Manager"`, et
partait tel quel dans le message au prospect. Aucune erreur : la réponse valait
`{"ok": true}`.

⚠️ **La cause n'est pas lemlist, c'est notre encodage.** Les trois routes de
variables prennent leurs valeurs en paramètres d'URL (clés arbitraires, pas de
corps JSON) ; `requests` y encode l'espace en `+` par défaut, et lemlist ne
redécode pas ce `+`. Le signal portait sa propre preuve — *« le slash, lui,
survit »* : `/` voyage en `%2F` et revient intact, donc le pourcent est bien
décodé. C'est le `+` seul qui passe littéralement.

⚠️ **Deux bancs voisins gardaient déjà « en query, pas en corps » — et ils
figeaient le défaut** : ils comparaient le dict passé à `requests`, donc
l'encodage par défaut. Une garde qui compare ce qu'on donne à la bibliothèque ne
voit pas ce qui part sur le fil. Celui-ci lit l'URL PRÉPARÉE.

Éprouvé rouge le 2026-09-10 : `params=variables` rétabli ⟹ le premier test nomme
le `+` dans l'URL préparée.
"""
from __future__ import annotations

import pytest
import requests

from oto.tools.lemlist import client as lm


class _Resp:
    status_code = 200
    content = b"x"
    text = "{}"

    @staticmethod
    def json():
        return {"ok": True}


@pytest.fixture()
def url_preparee(monkeypatch):
    """Rend l'URL telle que le serveur la RECEVRA, pas les arguments qu'on a
    passés à la bibliothèque — c'est toute la différence ici."""
    vu = {}

    def faux(method, url, headers=None, **kwargs):
        vu["url"] = requests.Request(method, url,
                                     params=kwargs.get("params")).prepare().url
        return _Resp()

    monkeypatch.setattr(lm.requests, "request", faux)
    return vu


VALEURS = {"posteRecrute": "un Traffic Manager", "autre": "un Head of CRM"}


def test_aucun_PLUS_ne_part_sur_le_fil(url_preparee):
    """L'axe du lot : le signe qui était stocké littéralement ne doit plus
    apparaître dans la query, sur aucune des valeurs."""
    lm.LemlistClient(api_key="k").update_lead_variables("lea_1", VALEURS)
    query = url_preparee["url"].split("?", 1)[1]
    assert "+" not in query, f"un `+` part encore : {query}"


def test_l_espace_part_en_POURCENT_VINGT(url_preparee):
    lm.LemlistClient(api_key="k").update_lead_variables("lea_1", VALEURS)
    assert "posteRecrute=un%20Traffic%20Manager" in url_preparee["url"]


def test_le_SLASH_reste_encode_comme_avant(url_preparee):
    """Le slash marchait déjà et doit continuer : un lot qui corrige une
    divergence ne doit pas en ouvrir une autre à côté."""
    lm.LemlistClient(api_key="k").update_lead_variables(
        "lea_1", {"x": "un profil SEO / CRO"})
    assert "%2F" in url_preparee["url"] and "+" not in url_preparee["url"]


def test_les_TROIS_routes_de_variables_sont_couvertes(url_preparee):
    """Le signal n'en nommait qu'une. Les trois partagent le même transport, donc
    le même défaut — corriger la seule signalée laisserait deux portes ouvertes."""
    c = lm.LemlistClient(api_key="k")
    for appel in (lambda: c.add_lead_variables("lea_1", VALEURS),
                  lambda: c.update_lead_variables("lea_1", VALEURS),
                  lambda: c.delete_lead_variables("lea_1", ["un nom espace"])):
        appel()
        assert "+" not in url_preparee["url"].split("?", 1)[1]


def test_une_valeur_ACCENTUEE_survit(url_preparee):
    """Le cas que personne ne signale parce qu'il marche — on le garde pour que
    le passage au pourcent ne l'ait pas cassé en chemin."""
    lm.LemlistClient(api_key="k").update_lead_variables("lea_1", {"v": "Société Générale"})
    from urllib.parse import unquote
    assert unquote(url_preparee["url"].split("v=", 1)[1]) == "Société Générale"
