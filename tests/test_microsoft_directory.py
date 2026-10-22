"""DirectoryClient — verrouille le contrat HTTP de la lecture de l'annuaire : champs
demandés, pagination à 999, connexions sur demande, nature d'un groupe, site d'équipe."""
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
