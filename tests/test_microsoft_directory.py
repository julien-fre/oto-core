"""DirectoryClient — verrouille le contrat HTTP de l'annuaire : champs demandés,
pagination à 999, connexions sur demande, nature d'un groupe, site d'équipe ; et ses trois
seules écritures (licences, compte activé, membres d'un groupe)."""
import pytest

from oto.tools.common import UpstreamHTTPError
from oto.tools.microsoft import DirectoryClient
from oto.tools.microsoft.directory import SKU_NAMES, group_kind
from microsoft_fake import G, _Resp, calls  # noqa: F401


@pytest.fixture
def client():
    return DirectoryClient("AT-admin")


def test_utilisateurs_avec_leurs_licences_pagines(calls, client):
    calls.responses.extend([_Resp({"value": [{"id": "u1"}], "@odata.nextLink": f"{G}/n"}),
                            _Resp({"value": [{"id": "u2"}]})])
    assert [u["id"] for u in client.list_users()] == ["u1", "u2"]
    call = calls[0]
    assert call["url"] == f"{G}/users" and call["params"]["$top"] == 999
    champs = call["params"]["$select"].split(",")
    assert "assignedLicenses" in champs and "accountEnabled" in champs
    assert "signInActivity" not in champs
    assert calls[1]["url"] == f"{G}/n"


def test_derniere_connexion_sur_demande(calls, client):
    calls.responses.append(_Resp({"value": []}))
    client.list_users(sign_in=True, limit=10)
    assert "signInActivity" in calls[0]["params"]["$select"].split(",")
    assert calls[0]["params"]["$top"] == 10


def test_sans_licence_p1_le_refus_remonte(calls, client):
    calls.responses.append(_Resp({"error": {"code": "Authentication_RequestFromNonPremiumTenantOrB2CTenant"}}, 403))
    with pytest.raises(UpstreamHTTPError):
        client.list_users(sign_in=True)


def test_un_utilisateur_son_manager_et_ses_groupes(calls, client):
    calls.responses.extend([_Resp({"id": "u1"}), _Resp({"value": [{"id": "g1"}]})])
    client.get_user("jane@contoso.com")
    client.list_user_groups("jane@contoso.com")
    assert calls[0]["url"] == f"{G}/users/jane%40contoso.com"
    assert calls[0]["params"]["$expand"] == "manager($select=id,displayName,mail)"
    assert calls[1]["url"] == f"{G}/users/jane%40contoso.com/memberOf/microsoft.graph.group"


def test_abonnements(calls, client):
    calls.responses.append(_Resp({"value": [{"skuPartNumber": "O365_BUSINESS_ESSENTIALS"}]}))
    assert client.list_subscriptions()[0]["skuPartNumber"] == "O365_BUSINESS_ESSENTIALS"
    assert calls[0]["url"] == f"{G}/subscribedSkus"
    assert SKU_NAMES["O365_BUSINESS_PREMIUM"] == "Microsoft 365 Business Standard"


def test_membres_et_proprietaires_d_un_groupe(calls, client):
    calls.responses.extend([_Resp({"value": []}), _Resp({"value": []})])
    client.list_group_members("g1")
    client.list_group_members("g1", owners=True)
    assert [c["url"] for c in calls] == [f"{G}/groups/g1/members", f"{G}/groups/g1/owners"]


def test_site_d_equipe_absent_vaut_none(calls, client):
    calls.responses.extend([_Resp({"webUrl": "https://x/sites/rh"}),
                            _Resp({"error": {"code": "itemNotFound"}}, 404)])
    assert client.get_group_site("g1")["webUrl"] == "https://x/sites/rh"
    assert client.get_group_site("g2") is None
    assert calls[0]["url"] == f"{G}/groups/g1/sites/root"


def test_sites_par_recherche_sans_top(calls, client):
    calls.responses.append(_Resp({"value": [{"id": "s1"}]}))
    client.list_sites()
    assert calls[0]["url"] == f"{G}/sites" and calls[0]["params"] == {"search": "*"}


@pytest.mark.parametrize("groupe, nature", [
    ({"groupTypes": ["Unified"], "mailEnabled": True, "securityEnabled": False}, "microsoft365"),
    ({"groupTypes": [], "mailEnabled": False, "securityEnabled": True}, "security"),
    ({"groupTypes": [], "mailEnabled": True, "securityEnabled": False}, "distribution"),
    ({"groupTypes": [], "mailEnabled": True, "securityEnabled": True}, "mail_security"),
])
def test_nature_d_un_groupe(groupe, nature):
    assert group_kind(groupe) == nature


def test_licences_ajoutees_et_retirees_en_un_appel(calls, client):
    client.assign_licenses("jane@contoso.com", add=["sku-a"], remove=["sku-b"])
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == f"{G}/users/jane%40contoso.com/assignLicense"
    assert calls[0]["json"] == {"addLicenses": [{"skuId": "sku-a", "disabledPlans": []}],
                                "removeLicenses": ["sku-b"]}


@pytest.mark.parametrize("add,remove,motif", [
    ((), (), "at least one"), (["a"], ["a"], "both added and removed")])
def test_licences_refusees_avant_l_appel(calls, client, add, remove, motif):
    with pytest.raises(ValueError, match=motif):
        client.assign_licenses("u1", add=add, remove=remove)
    assert not calls


def test_compte_desactive(calls, client):
    calls.responses.append(_Resp(None, 204))
    assert client.set_account_enabled("u1", False) == "u1"
    assert (calls[0]["method"], calls[0]["url"]) == ("PATCH", f"{G}/users/u1")
    assert calls[0]["json"] == {"accountEnabled": False}


def test_membre_ajoute_par_son_id_puis_retire(calls, client):
    calls.responses.extend([_Resp(None, 204), _Resp(None, 204)])
    client.add_group_member("g1", "u1")
    client.remove_group_member("g1", "u1")
    assert (calls[0]["method"], calls[0]["url"]) == ("POST", f"{G}/groups/g1/members/$ref")
    assert calls[0]["json"] == {"@odata.id": f"{G}/directoryObjects/u1"}
    assert (calls[1]["method"], calls[1]["url"]) == ("DELETE",
                                                     f"{G}/groups/g1/members/u1/$ref")


def test_le_lieu_d_usage_est_lu():
    from oto.tools.microsoft.directory import _USER_FIELDS

    assert "usageLocation" in _USER_FIELDS
