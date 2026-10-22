"""OneNoteClient — verrouille le contrat HTTP de OneNote : une racine par client (la
personne, un groupe, un site), une page créée depuis un document HTML, changée par
commandes, lue en HTML."""
import pytest

from oto.tools.common import UpstreamHTTPError
from oto.tools.microsoft import OneNoteClient
from microsoft_fake import G, _Resp, calls  # noqa: F401


@pytest.fixture
def client():
    return OneNoteClient("AT-personne")


@pytest.mark.parametrize("kw, racine", [
    ({}, "/me/onenote"),
    ({"group_id": "g-1"}, "/groups/g-1/onenote"),
    ({"site_id": "contoso.sharepoint.com,a,b"}, "/sites/contoso.sharepoint.com%2Ca%2Cb/onenote"),
])
def test_une_racine_par_client(calls, kw, racine):
    calls.responses.append(_Resp({"value": [{"id": "nb1"}]}))
    assert OneNoteClient("AT", **kw).list_notebooks() == [{"id": "nb1"}]
    assert calls[0]["url"] == f"{G}{racine}/notebooks"
    assert calls[0]["params"] == {"$orderby": "lastModifiedDateTime desc", "$top": 100}


def test_groupe_et_site_ensemble_refuses():
    with pytest.raises(ValueError, match="not both"):
        OneNoteClient("AT", group_id="g", site_id="s")


def test_sections_d_un_carnet_ou_de_toute_la_racine(calls, client):
    calls.responses.extend([_Resp({"value": []}), _Resp({"value": []})])
    client.list_sections(notebook_id="nb 1")
    client.list_sections(limit=5)
    assert [c["url"] for c in calls] == [f"{G}/me/onenote/notebooks/nb%201/sections",
                                         f"{G}/me/onenote/sections"]
    assert calls[1]["params"] == {"$expand": "parentNotebook($select=id,displayName)",
                                  "$top": 5}


def test_pages_d_une_section_filtrees_sur_le_titre(calls, client):
    calls.responses.extend([_Resp({"value": [{"id": "p1"}], "@odata.nextLink": f"{G}/n"}),
                            _Resp({"value": [{"id": "p2"}]})])
    assert client.list_pages(section_id="s1", title_contains="Réunion d'équipe") == [
        {"id": "p1"}, {"id": "p2"}]
    call = calls[0]
    assert call["url"] == f"{G}/me/onenote/sections/s1/pages"
    assert call["params"] == {
        "$orderby": "lastModifiedDateTime desc",
        "$expand": "parentSection($select=id,displayName)",
        "$filter": "contains(tolower(title),'réunion d''équipe')", "$top": 50}
    assert calls[1]["url"] == f"{G}/n"


def test_lecture_d_une_page_en_html_avec_ses_ids(calls, client):
    calls.responses.append(_Resp(raw=b"<html><body><p id='p:{1}'>Bonjour</p></body></html>"))
    assert "Bonjour" in client.get_page_content("1-abc!", include_ids=True)
    call = calls[0]
    assert call["url"] == f"{G}/me/onenote/pages/1-abc%21/content"
    assert call["params"] == {"includeIDs": "true"}
    assert call["headers"]["Accept"] == "text/html"


def test_creation_d_une_page_depuis_un_document_html(calls, client):
    calls.responses.append(_Resp({"id": "p9", "title": "Plan <du> jour"}, status_code=201))
    assert client.create_page("s1", title="Plan <du> jour", body_html="<p>Ordre</p>")["id"] == "p9"
    call = calls[0]
    assert (call["method"], call["url"]) == ("POST", f"{G}/me/onenote/sections/s1/pages")
    assert call["headers"]["Content-Type"] == "text/html; charset=utf-8"
    assert call["data"] == ("<!DOCTYPE html><html><head><title>Plan &lt;du&gt; jour</title>"
                            "</head><body><p>Ordre</p></body></html>").encode()


def test_creation_sans_titre_refusee_avant_l_appel(calls, client):
    with pytest.raises(Exception):
        client.create_page("s1", title="")
    assert calls == []


def test_ajout_a_une_page_par_commande(calls, client):
    calls.responses.append(_Resp(status_code=204))
    client.append_to_page("p1", "<p>Suite</p>")
    call = calls[0]
    assert (call["method"], call["url"]) == ("PATCH", f"{G}/me/onenote/pages/p1/content")
    assert call["json"] == [{"target": "body", "action": "append", "content": "<p>Suite</p>"}]


@pytest.mark.parametrize("commandes, motif", [
    ([], "empty"),
    ([{"target": "body", "action": "delete", "content": "x"}], "not one of"),
])
def test_commandes_invalides_refusees_avant_l_appel(calls, client, commandes, motif):
    with pytest.raises(ValueError, match=motif):
        client.update_page("p1", commandes)
    assert calls == []


def test_section_carnet_et_suppression(calls, client):
    calls.responses.extend([_Resp({"id": "s2"}, 201), _Resp({"id": "nb2"}, 201),
                            _Resp(status_code=204)])
    client.create_section("nb1", "Comptes rendus")
    client.create_notebook("Projets")
    assert client.delete_page("p1") == "p1"
    assert [(c["method"], c["url"]) for c in calls] == [
        ("POST", f"{G}/me/onenote/notebooks/nb1/sections"),
        ("POST", f"{G}/me/onenote/notebooks"),
        ("DELETE", f"{G}/me/onenote/pages/p1")]
    assert calls[0]["json"] == {"displayName": "Comptes rendus"}


def test_page_introuvable_refus_type(calls, client):
    calls.responses.append(_Resp({"error": {"code": "20102", "message": "not found"}}, 404))
    with pytest.raises(UpstreamHTTPError):
        client.get_page("p-absente")
