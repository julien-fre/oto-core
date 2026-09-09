"""Contrat du client Planity — la chaîne d'auth, le sharding, et les fenêtres de dates.

Aucun réseau, et aucun bac à sable pour ce fournisseur. Ce qu'on peut vérifier hors
ligne, ce sont les trois pièces qui décident du reste et qui échouent silencieusement
quand elles se trompent :

- la **chaîne d'auth en trois étapes** — et surtout la liste des salons atteignables,
  qu'on ne lit nulle part ailleurs que dans les claims du jeton enrichi ;
- le **sharding**, qui n'est pas une consultation mais un CALCUL (index de calendrier)
  et une lecture (shard métier) : viser le mauvais shard rend un refus qui se lit
  comme un problème de droits alors que c'est une adresse ;
- les **fenêtres de dates**, où une borne fausse ne lève rien du tout — elle rend un
  chiffre d'affaires.

Rien ici ne parle au fournisseur : aucun identifiant, et le dépôt est public.
"""
from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timedelta

import pytest

from oto.tools.planity import auth as pauth
from oto.tools.planity import date_range as dr
from oto.tools.planity import firebase_ws as fws
from oto.tools.planity.client import Employee, PlanityClient, SalonInfo
from oto.tools.planity.config import PlanityEndpoints
from oto.tools.planity.rest_api import PlanityREST


#: Coordonnées MANIFESTEMENT fictives : ce fichier ne porte aucune valeur de
#: Planity, pas plus que le code (cf. `config.py`). Ce qu'on vérifie ici, c'est
#: qu'elles voyagent jusqu'aux bons endroits — pas leur contenu.
COORDONNEES = PlanityEndpoints(
    firebase_api_key="cle-firebase-fictive",
    firebase_app_id="app-id-fictif",
    rest_api="https://lambdas.exemple.invalid",
)


# ── Doublures ────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class _FakeHTTP:
    """`httpx.AsyncClient` réduit à ce que le client Planity en utilise."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls: list[tuple[str, dict]] = []
        self.delais: list = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json or {}))
        self.delais.append(timeout)
        return _Resp(self._replies.pop(0))

    async def aclose(self):
        return None


def _jwt(claims: dict) -> str:
    """Un JWT dont seul le payload compte (c'est tout ce que `auth` lit)."""
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


_ENRICHI = _jwt({
    "iss": "planity", "sub": "uid-exemple", "email": "demo@example.com",
    "plPro": True, "isBusinessSharded": True, "isUserSharded": True, "source": "web",
    "biz-un": 1, "biz-deux": 1,
    # Un claim non réservé qui ne vaut PAS 1 : ce n'est pas un salon accessible.
    "biz-revoque": 0,
})


def _auth_replies():
    return [
        {"idToken": "jeton-basique", "localId": "uid-exemple"},   # signInWithPassword
        {"token": "jeton-custom"},                                 # getProAuthToken
        {"idToken": _ENRICHI, "refreshToken": "refresh", "expiresIn": "3600"},
    ]


# ── Les coordonnées, fournies et jamais devinées ─────────────────────────────

def test_les_coordonnees_sont_obligatoires_et_sans_defaut():
    """⚠️ Le cœur du correctif : PAS de valeur par défaut. Un défaut aurait remis
    la constante de Planity dans ce dépôt public sous un autre nom, et personne
    n'aurait vu la différence."""
    import inspect

    for fabrique in (PlanityClient.__init__, pauth.PlanityAuth.__init__):
        param = inspect.signature(fabrique).parameters["endpoints"]
        assert param.default is inspect.Parameter.empty, (
            f"{fabrique.__qualname__} a un défaut pour `endpoints` — c'est la "
            "constante de Planity qui revient par la fenêtre.")


def test_un_champ_de_coordonnees_vide_leve_a_la_construction():
    """Une chaîne vide construit un objet valide et produit, plus tard et ailleurs,
    un 400 de Firebase — qu'on lit alors comme « mauvais mot de passe ». C'est le
    mode de panne le plus cher : il accuse l'utilisatrice d'une erreur de
    configuration de l'opérateur."""
    for manquant in ("firebase_api_key", "firebase_app_id", "rest_api"):
        champs = {"firebase_api_key": "k", "firebase_app_id": "a",
                  "rest_api": "https://x.invalid", manquant: "   "}
        with pytest.raises(ValueError, match=manquant):
            PlanityEndpoints(**champs)


def test_les_coordonnees_fournies_sont_celles_qui_partent_sur_le_fil():
    """Elles voyagent jusqu'à TROIS endroits différents — l'URL d'auth Firebase, la
    racine des lambdas, et la poignée de main WebSocket. En oublier un laisserait
    une constante en dur qu'aucune relecture ne verrait."""
    http = _FakeHTTP(_auth_replies())
    asyncio.run(pauth.PlanityAuth(
        "demo@example.com", "s3cret", COORDONNEES, client=http).get_tokens())

    urls = [u for u, _ in http.calls]
    assert "key=cle-firebase-fictive" in urls[0]
    assert urls[1].startswith("https://lambdas.exemple.invalid/")
    assert "key=cle-firebase-fictive" in urls[2]
    assert fws.FirebaseRTDB.master("jeton", "app-id-fictif").app_id == "app-id-fictif"


def test_aucune_valeur_de_planity_ne_subsiste_dans_le_paquet():
    """Le cliquet. Ce dépôt est PUBLIC : une constante d'un tiers qui reviendrait —
    par un copier-coller, par un « juste pour tester », par un défaut ajouté de
    bonne foi — doit tomber ici et pas se découvrir par une alerte GitHub."""
    import pathlib as _p

    racine = _p.Path(__file__).resolve().parent.parent / "oto" / "tools" / "planity"
    empreintes = ("AIza", "planityapp", "1025269755978")
    fautes = [f"{f.name}:{empreinte}"
              for f in sorted(racine.glob("*"))
              if f.suffix in (".py", ".md")
              for empreinte in empreintes
              if empreinte in f.read_text(encoding="utf-8")]
    assert not fautes, (
        f"{fautes} : coordonnée de Planity en dur dans un dépôt public. Elle se "
        "passe par `PlanityEndpoints`, jamais en constante.")


# ── L'extra manquant ─────────────────────────────────────────────────────────

def test_un_module_de_l_extra_absent_dit_d_installer_l_extra():
    """« No module named 'httpx' » est vrai et parfaitement inutile : il n'a jamais
    fait installer un extra à personne, et chez oto-backend il devient une ligne de
    journal (« planity tools disabled: … ») sur laquelle on cherche un bug d'import
    pendant vingt minutes. La retraduction vit à l'ORIGINE parce que les
    consommateurs sont plusieurs."""
    import oto.tools.planity as pkg

    for module in ("httpx", "websockets"):
        refus = pkg._refus_d_extra(ImportError("boom", name=module))
        assert refus is not None
        assert "oto-core[planity]" in str(refus) and module in str(refus)


def test_un_import_interne_casse_remonte_tel_quel():
    """⚠️ Le contre-cas, et c'est lui qui compte : déguiser un module du paquet
    renommé en « installe l'extra » enverrait chercher la panne à l'opposé d'où elle
    est. Sans cette assertion, la retraduction s'élargirait sans qu'on le voie."""
    import oto.tools.planity as pkg

    assert pkg._refus_d_extra(ImportError("boom", name="oto.tools.planity.auth")) is None
    assert pkg._refus_d_extra(ImportError("sans nom")) is None


# ── La chaîne d'auth ─────────────────────────────────────────────────────────

def test_les_trois_etapes_sont_jouees_dans_l_ordre():
    http = _FakeHTTP(_auth_replies())
    tokens = asyncio.run(pauth.PlanityAuth(
        "demo@example.com", "s3cret", COORDONNEES, client=http).get_tokens())

    urls = [u for u, _ in http.calls]
    assert "accounts:signInWithPassword" in urls[0]
    assert urls[1].endswith("/getProAuthToken")
    assert "accounts:signInWithCustomToken" in urls[2]
    assert tokens.id_token == _ENRICHI and tokens.uid == "uid-exemple"


def test_chaque_appel_de_la_chaine_porte_sa_propre_borne_de_temps():
    """Une borne posée à la construction du client ne suit pas un client PASSÉ par
    l'appelant — et `PlanityAuth` accepte qu'on lui en passe un. La borne se pose
    donc à l'appel. Cliquet transverse : `tests/test_http_timeouts.py`."""
    http = _FakeHTTP(_auth_replies())
    asyncio.run(pauth.PlanityAuth(
        "demo@example.com", "s3cret", COORDONNEES, client=http).get_tokens())
    assert http.delais and all(d for d in http.delais)


def test_l_echange_custom_renvoie_l_uid_et_le_jeton_de_l_etape_1():
    """L'étape 2 n'est pas un simple relais : elle re-présente l'uid ET le jeton
    basique, et c'est ce qui fait enrichir le jeton par les claims métier."""
    http = _FakeHTTP(_auth_replies())
    asyncio.run(pauth.PlanityAuth(
        "demo@example.com", "s3cret", COORDONNEES, client=http).get_tokens())

    _, corps = http.calls[1]
    assert corps["uid"] == "uid-exemple"
    assert corps["token"] == "jeton-basique"
    assert corps["isBusinessSharded"] is True and corps["isUserSharded"] is True


def test_les_salons_atteignables_sortent_des_claims_du_jeton():
    """Il n'existe AUCUNE autre source : pas d'endpoint « mes salons ». Un claim
    réservé (email, exp…) n'est pas un salon, et un claim à 0 non plus."""
    http = _FakeHTTP(_auth_replies())
    tokens = asyncio.run(pauth.PlanityAuth(
        "demo@example.com", "s3cret", COORDONNEES, client=http).get_tokens())

    assert sorted(tokens.business_ids) == ["biz-deux", "biz-un"]


def test_un_jeton_encore_valide_ne_relance_pas_la_chaine():
    http = _FakeHTTP(_auth_replies())
    a = pauth.PlanityAuth("demo@example.com", "s3cret", COORDONNEES, client=http)
    asyncio.run(a.get_tokens())
    asyncio.run(a.get_tokens())
    assert len(http.calls) == 3, "le second appel a rejoué la chaîne d'auth"


def test_un_jeton_qui_expire_rejoue_la_chaine_entiere():
    """Pas de refresh_token : Planity re-logue. La borne est à 60 s de l'expiration —
    un jeton qui expire dans 30 s est déjà périmé pour nous."""
    http = _FakeHTTP(_auth_replies() + _auth_replies())
    a = pauth.PlanityAuth("demo@example.com", "s3cret", COORDONNEES, client=http)
    asyncio.run(a.get_tokens())
    a._tokens.expires_at = __import__("time").time() + 30
    asyncio.run(a.get_tokens())
    assert len(http.calls) == 6


# ── Le sharding ──────────────────────────────────────────────────────────────

def test_l_index_de_shard_de_calendrier_est_un_calcul_pas_une_lecture():
    attendu = sum(ord(c) for c in "cal-exemple") % 4 + 1
    assert fws.calendar_shard_index("cal-exemple") == attendu
    assert 1 <= attendu <= 4


def test_l_index_de_shard_reste_dans_les_quatre_bases():
    for cid in ("a", "cal-1", "CAL-9999", "x" * 64, ""):
        assert fws.calendar_shard_index(cid) in (1, 2, 3, 4)


def test_les_trois_familles_de_base_ont_des_hotes_distincts():
    """Maître, shard métier et shard de calendrier ne vivent NI sur le même hôte NI
    dans le même namespace : confondre les deux derniers rend un refus qui se lit
    comme un droit manquant alors que c'est une adresse."""
    maitre = fws.FirebaseRTDB.master("jeton", "app-id-fictif")
    metier = fws.FirebaseRTDB.business_shard("fr-00", "jeton", "app-id-fictif")
    calendrier = fws.FirebaseRTDB.calendars_shard("cal-exemple", "jeton", "app-id-fictif")

    assert maitre.host == "planity-production.firebaseio.com"
    assert maitre.namespace == "planity-production"
    assert metier.host == "planity-production-fr-00.europe-west1.firebasedatabase.app"
    assert metier.namespace == "planity-production-fr-00"
    idx = fws.calendar_shard_index("cal-exemple")
    assert calendrier.host == f"planity-production-calendars-{idx}.firebaseio.com"
    assert calendrier.namespace == f"planity-production-calendars-{idx}"
    assert len({maitre.host, metier.host, calendrier.host}) == 3


# ── Le référentiel ───────────────────────────────────────────────────────────

class _FakeRTDB:
    """Un RTDB en mémoire : `get(path)` lit un dict de chemins."""

    def __init__(self, data):
        self.data = data
        self.lus: list[str] = []

    async def get(self, path, query=None):
        self.lus.append(path)
        return self.data.get(path)

    async def close(self):
        return None


def _client_avec(rtdb, business_ids=("biz-un",)):
    c = PlanityClient.__new__(PlanityClient)          # pas de socket HTTP réel
    c._endpoints = COORDONNEES
    c._salons = {}
    c._master = rtdb
    c._shards = {}
    c._current_token = "jeton"
    c._lock = asyncio.Lock()

    class _Auth:
        async def get_tokens(self):
            return pauth.PlanityTokens(id_token="jeton", refresh_token="r",
                                       uid="uid-exemple", business_ids=list(business_ids),
                                       expires_at=9e12)

    c.auth = _Auth()

    async def _master():
        return rtdb

    c._ensure_master = _master
    return c


_SALON = {
    "businesses/biz-un/name": "Salon Exemple",
    "businesses/biz-un/slug": "salon-exemple",
    "businesses/biz-un/phoneNumber": "0100000000",
    "businesses/biz-un/db": "fr-00",
    "businesses/biz-un/openingHours": "10:00-19:00",
    "businesses/biz-un/calendars": {
        "cal-1": {"children": {
            "emp-1": {"name": " Alex ", "color": "#111"},
            "emp-2": {"name": "Camille", "color": "#222"},
        }},
    },
}


def test_un_salon_expose_ses_collaborateurs_a_plat_avec_leur_calendrier():
    """Chez Planity un collaborateur est un ENFANT de calendrier : sans le
    `calendar_id` remonté, on ne sait plus à quel agenda rattacher un rendez-vous."""
    rtdb = _FakeRTDB(_SALON)
    salons = asyncio.run(_client_avec(rtdb).list_salons())

    assert len(salons) == 1
    s = salons[0]
    assert isinstance(s, SalonInfo) and s.name == "Salon Exemple" and s.db_shard == "fr-00"
    assert s.calendars == ["cal-1"]
    assert [(e.id, e.name, e.calendar_id) for e in s.employees] == [
        ("emp-1", "Alex", "cal-1"), ("emp-2", "Camille", "cal-1")]
    assert all(isinstance(e, Employee) for e in s.employees)


def test_un_salon_deja_lu_ne_se_relit_pas():
    rtdb = _FakeRTDB(_SALON)
    c = _client_avec(rtdb)
    asyncio.run(c.list_salons())
    lus = len(rtdb.lus)
    asyncio.run(c.list_salons())
    assert len(rtdb.lus) == lus, "le référentiel a été relu alors qu'il est en cache"


def test_un_salon_hors_des_claims_est_refuse_nommement():
    """Demander un salon qu'on n'atteint pas doit dire « pas accessible », pas rendre
    un salon vide qu'on prendrait pour un salon sans rendez-vous."""
    c = _client_avec(_FakeRTDB(_SALON))
    with pytest.raises(ValueError, match="biz-inconnu"):
        asyncio.run(c.get_salon("biz-inconnu"))


def test_un_champ_absent_ne_fait_pas_tomber_le_referentiel():
    """Le RTDB rend `None` pour un chemin vide — un salon sans horaires ni téléphone
    reste un salon."""
    rtdb = _FakeRTDB({"businesses/biz-un/name": "Salon Exemple"})
    s = asyncio.run(_client_avec(rtdb).list_salons())[0]
    assert s.phone is None and s.opening_hours is None
    assert s.employees == [] and s.calendars == []
    assert s.db_shard == "master"


# ── Les payloads de statistiques ─────────────────────────────────────────────

def test_les_endpoints_de_stats_recoivent_les_DEUX_jeux_de_cles():
    """Les lambdas de statistiques exigent `userToken` ET `token`, `gte`/`lte` ET
    `start`/`end`. En oublier un rend `MISSING_TOKEN_ERROR`, qui se lit comme un
    credential invalide alors que le credential est bon."""
    p = PlanityREST(COORDONNEES, client=_FakeHTTP([]))._stats_payload(
        "biz-un", "jeton", 1000, 2000, ["emp-1"], ["cal-1"])

    assert p["userToken"] == p["token"] == "jeton"
    assert (p["gte"], p["lte"]) == (1000, 2000)
    assert (p["start"], p["end"]) == (1000, 2000)
    assert p["sellers"] == ["emp-1"] and p["calendars"] == ["cal-1"]


# ── Les fenêtres de dates ────────────────────────────────────────────────────

def _jours(gte, lte):
    return (lte - gte) / 86_400_000


def test_sans_rien_la_fenetre_par_defaut_est_de_sept_jours():
    assert round(_jours(*dr.resolve_range())) == 7


def test_un_preset_prime_sur_les_bornes_explicites():
    """La précédence est écrite dans `resolve_range` : un preset l'emporte. Sans ce
    test, l'inverser ne casse rien de visible — ça rend juste un autre chiffre."""
    gte, lte = dr.resolve_range(date_from="2020-01-01", date_to="2020-01-02", preset="today")
    assert dr.ms_to_iso(gte).startswith(datetime.now(dr.FR_TZ).date().isoformat())


def test_hier_est_une_journee_pleine_et_close():
    gte, lte = dr.resolve_range(preset="yesterday")
    hier = (datetime.now(dr.FR_TZ) - timedelta(days=1)).date().isoformat()
    assert dr.ms_to_iso(gte).startswith(f"{hier}T00:00:00")
    assert dr.ms_to_iso(lte).startswith(f"{hier}T23:59:59")


def test_une_borne_de_fin_en_date_seule_couvre_toute_la_journee():
    """`date_to="2026-04-16"` veut dire « jusqu'au bout du 16 », pas « jusqu'à
    minuit » — sinon la journée entière manque au total."""
    _, lte = dr.resolve_range(date_from="2026-04-01", date_to="2026-04-16")
    assert dr.ms_to_iso(lte).startswith("2026-04-16T23:59:59")


def test_un_preset_en_nombre_de_jours_se_lit_tel_quel():
    assert round(_jours(*dr.resolve_range(preset="30d"))) == 30
    assert round(_jours(*dr.resolve_range(preset="90d"))) == 90


def test_le_mois_dernier_est_borne_aux_deux_bouts():
    gte, lte = dr.resolve_range(preset="last_month")
    debut, fin = dr.ms_to_iso(gte), dr.ms_to_iso(lte)
    assert debut[8:10] == "01" and debut[11:19] == "00:00:00"
    assert fin[11:19] == "23:59:59"
    assert debut[:7] == fin[:7], "début et fin doivent tomber dans le même mois"


def test_un_preset_inconnu_leve_au_lieu_de_rendre_une_fenetre_au_hasard():
    with pytest.raises(ValueError, match="inconnu|Unknown"):
        dr.resolve_range(preset="depuis_toujours")


def test_les_horodatages_sont_rendus_en_heure_de_paris():
    """Planity compte en millisecondes UTC ; l'exploitante compte en heure locale.
    Un décalage d'une heure déplace un rendez-vous de créneau."""
    iso = dr.ms_to_iso(1_760_000_000_000)
    assert iso.endswith("+02:00") or iso.endswith("+01:00")


def test_zero_et_none_ne_sont_pas_une_date():
    assert dr.ms_to_iso(0) is None and dr.ms_to_iso(None) is None
