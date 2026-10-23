"""WorkbookClient — verrouille le contrat HTTP des cellules d'un classeur Excel : l'adresse
du classeur (id ou chemin), la feuille par son nom encodé, la plage citée en OData, la
plage utilisée par défaut, et l'écriture d'une plage rectangulaire seulement."""
import pytest

from oto.tools.microsoft import WorkbookClient
from microsoft_fake import G, _Resp, calls  # noqa: F401


@pytest.fixture
def client():
    return WorkbookClient("AT-1")


def test_feuilles_d_un_classeur_par_son_chemin(calls, client):
    calls.responses.append(_Resp({"value": [{"id": "s1", "name": "Janvier"}]}))
    assert client.list_worksheets("d1", path="RH/Centre 1.xlsx")[0]["name"] == "Janvier"
    assert calls[0]["url"] == f"{G}/drives/d1/root:/RH/Centre%201.xlsx:/workbook/worksheets"


def test_une_plage_par_son_adresse(calls, client):
    calls.responses.append(_Resp({"address": "'Oct 2026'!B2:C3", "values": [[1, 2], [3, 4]]}))
    out = client.get_range("d1", "Oct 2026", "B2:C3", item_id="i1")
    assert out["values"] == [[1, 2], [3, 4]]
    assert calls[0]["url"] == (f"{G}/drives/d1/items/i1/workbook/worksheets/Oct%202026/"
                               "range(address='B2%3AC3')")
    assert "values" in calls[0]["params"]["$select"].split(",")


def test_sans_adresse_la_plage_utilisee(calls, client):
    calls.responses.append(_Resp({"address": "Feuil1!A1:F40"}))
    client.get_range("d1", "Feuil1", item_id="i1")
    assert calls[0]["url"].endswith("/worksheets/Feuil1/usedRange(valuesOnly=true)")


def test_l_apostrophe_d_une_adresse_est_doublee(calls, client):
    calls.responses.append(_Resp({}))
    client.get_range("d1", "S", "'L''été'!A1", item_id="i1")
    assert "range(address='%27%27L%27%27%27%27%C3%A9t%C3%A9%27%27%21A1')" in calls[0]["url"]


def test_ecrire_une_plage(calls, client):
    calls.responses.append(_Resp({"address": "Feuil1!H2:I3", "values": [[1.5, 0], [2, None]]}))
    client.update_range("d1", "Feuil1", "H2:I3", [[1.5, 0], [2, None]], item_id="i1")
    assert calls[0]["method"] == "PATCH"
    assert calls[0]["url"].endswith("/worksheets/Feuil1/range(address='H2%3AI3')")
    assert calls[0]["json"] == {"values": [[1.5, 0], [2, None]]}


@pytest.mark.parametrize("values", [[], [[]], [[1, 2], [3]], ["ab"], None])
def test_une_plage_non_rectangulaire_refusee_avant_l_appel(calls, client, values):
    with pytest.raises(ValueError):
        client.update_range("d1", "Feuil1", "A1:B2", values, item_id="i1")
    assert not calls


def test_id_et_chemin_exclusifs(calls, client):
    with pytest.raises(ValueError, match="mutually exclusive"):
        client.list_worksheets("d1", item_id="i1", path="a.xlsx")
