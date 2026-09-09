"""Ce qui décide d'une lecture Planity — la trame, la borne, et le nom des champs.

Trois familles de panne vivent ici, et elles ont en commun de ne jamais lever :

- **la trame** — une requête bornée sans son tag est refusée par Firebase avec
  `permission_denied`, qui envoie chercher un droit manquant là où il manque un
  champ de protocole ;
- **la borne** — l'index des rendez-vous se compare comme une CHAÎNE : une borne
  de fin à la journée nue n'attrape rien et rend un agenda vide, qu'on lit comme
  une journée sans rendez-vous ;
- **le nom des champs** — le stockage est abrégé, et lire le mauvais nom rend
  `None`, `0`, ou un rendez-vous sans cliente. C'est ainsi que tout un catalogue
  de prestations a valu zéro euro pendant des semaines ;
- **la mort d'une connexion inactive** — l'amont raccroche sans le dire sur un
  socket qui ne porte pas de trafic. Un socket gardé en réserve est donc mort plus
  souvent que vivant, et le servir tel quel change une coupure silencieuse en
  panne durable de tout ce qui passe par ce shard.

Aucun réseau : ce qu'on vérifie, c'est ce qui PART sur le fil et ce qu'on fait de
ce qui revient. Le dépôt est public et ce fichier ne porte aucune valeur réelle.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from oto.tools.planity import appointments as rdv
from oto.tools.planity import firebase_ws as fws
from oto.tools.planity import pos, services, stock


# ── Doublure de socket ───────────────────────────────────────────────────────

def _coupure():
    """Un `ConnectionClosed` de la lib, construit sans dépendre de sa signature.

    Elle a changé entre versions ; ce qui compte ici est le TYPE que `get` attrape,
    pas les arguments. Un test qui se casse sur un bump de la lib n'aurait rien
    mesuré de ce dépôt."""
    from websockets.exceptions import ConnectionClosedError

    try:
        return ConnectionClosedError(None, None)
    except TypeError:                                    # signature plus ancienne
        return ConnectionClosedError(1006, "")


class _FauxWS:
    """Un WebSocket réduit à ce que le client en fait : il note, et il répond `ok`.

    `close_code` non nul = socket MORT, comme la lib le rend après une coupure sans
    trame de fermeture (`1006`, mesuré). `coupures` fait échouer les N prochains
    envois avec l'exception de la lib — le pair qui part PENDANT la lecture."""

    def __init__(self, valeur=None, close_code=None, budget=None):
        self.envoyes: list[dict] = []
        self.valeur = valeur
        self.close_code = close_code
        # Budget de coupures PARTAGÉ avec les sockets suivants : une reconnexion ne
        # doit pas le remettre à zéro, sinon « le pair coupe encore » ne se teste pas.
        self.budget = budget if budget is not None else [0]
        self.ferme = False

    async def send(self, texte):
        if self.budget[0] > 0:
            self.budget[0] -= 1
            self.close_code = 1006
            raise _coupure()
        self.envoyes.append(json.loads(texte))

    async def recv(self):
        envoi = self.envoyes[-1]["d"]
        return json.dumps({"t": "d", "d": {"r": envoi["r"],
                                           "b": {"s": "ok", "d": self.valeur}}})

    async def close(self):
        self.ferme = True


def _db(valeur=None, close_code=None, coupures=0):
    """Un RTDB dont `connect()` pose un socket NEUF au lieu d'ouvrir le réseau."""
    db = fws.FirebaseRTDB("hote.invalid", "ns", "jeton", "app-id-fictif")
    budget = [coupures]
    db.ws = _FauxWS(valeur, close_code=close_code, budget=budget)
    db.connexions = 0

    async def _connect():
        db.connexions += 1
        db.ws = _FauxWS(valeur, budget=budget)

    db.connect = _connect
    return db


def _trame(db) -> dict:
    return db.ws.envoyes[-1]["d"]["b"]


# ── La trame ─────────────────────────────────────────────────────────────────

def test_une_lecture_bornee_porte_son_tag():
    """Sans `t`, Firebase répond `internal_error` / `permission_denied` — un refus
    qui se lit comme un droit manquant alors que c'est un champ de protocole."""
    db = _db({})
    asyncio.run(db.get("noeud/x", fws.limit_last(3)))
    trame = _trame(db)
    assert trame["q"] == {"i": ".key", "l": 3, "vf": "r"}
    assert trame["t"] == 1, "la requête bornée est partie SANS tag"


def test_une_lecture_entiere_ne_porte_ni_query_ni_tag():
    db = _db({})
    asyncio.run(db.get("noeud/x"))
    trame = _trame(db)
    assert "q" not in trame and "t" not in trame


def test_deux_lectures_bornees_ne_partagent_pas_leur_tag():
    """Le tag identifie le LISTEN sur la connexion : deux bornes différentes qui le
    partagent se marchent dessus, et la seconde rend les données de la première."""
    db = _db({})
    asyncio.run(db.get("noeud/x", fws.limit_last(1)))
    asyncio.run(db.get("noeud/x", fws.limit_first(1)))
    tags = [e["d"]["b"]["t"] for e in db.ws.envoyes]
    assert tags == [1, 2]


def test_le_tag_est_par_connexion_pas_par_requete():
    """Il ne se confond pas avec le numéro de requête, qui compte AUSSI les trames
    non bornées : les faire coïncider ne se verrait qu'à la première lecture mixte."""
    db = _db({})
    asyncio.run(db.get("noeud/x"))
    asyncio.run(db.get("noeud/x", fws.limit_last(1)))
    assert _trame(db)["t"] == 1
    assert db.ws.envoyes[-1]["d"]["r"] == 2


def test_les_bornes_disent_de_quel_bout_elles_lisent():
    assert fws.limit_last(5)["vf"] == "r"
    assert fws.limit_first(5)["vf"] == "l"
    assert fws.limit_last(5, index="createdAt")["i"] == "createdAt"


@pytest.mark.parametrize("n", [0, -1, 2.5, None])
def test_une_borne_qui_n_en_est_pas_une_leve(n):
    """`0` rendrait un nœud vide, qui se lit comme « ce salon n'a rien »."""
    with pytest.raises(ValueError):
        fws.limit_last(n)


def test_une_plage_porte_ses_deux_bouts():
    q = fws.range_on("createdAt", 10, 20)
    assert q == {"i": "createdAt", "sp": 10, "ep": 20}


def test_une_plage_limitee_lit_par_le_debut():
    q = fws.range_on("createdAt", 10, 20, limit=7)
    assert (q["l"], q["vf"]) == (7, "l")


def test_une_plage_sans_index_leve():
    with pytest.raises(ValueError):
        fws.range_on("", 1, 2)


# ── La borne de journée ──────────────────────────────────────────────────────

def test_la_borne_de_fin_couvre_toute_la_journee():
    """LE bug qui rendait des agendas vides : `"2026-09-08"` en borne haute exclut
    `"2026-09-08 09:30"`, qui lui est POSTÉRIEUR en comparaison de chaînes."""
    db = _db({})
    asyncio.run(rdv.lire_jours(db, "enfant-1", "2026-09-08", "2026-09-08"))
    q = _trame(db)["q"]
    assert q["i"] == "s"
    assert q["sp"] == "2026-09-08"
    assert q["ep"] == "2026-09-08 23:59"
    assert q["ep"] > "2026-09-08 23:58", "la borne haute manque la fin de journée"


def test_les_rendez_vous_se_lisent_sous_l_enfant_d_agenda():
    """La clé est la COLLABORATRICE, pas l'agenda : `calendars/<cid>/vevents` rend
    un nœud vide, jamais une erreur."""
    db = _db({})
    asyncio.run(rdv.lire_jours(db, "enfant-1", "2026-09-08", "2026-09-08"))
    assert _trame(db)["p"] == "calendar_vevents/enfant-1"


@pytest.mark.parametrize("jour", ["08/09/2026", "2026-9-8", "2026-09-08T10:00", "", None])
def test_un_jour_mal_forme_leve_au_lieu_de_rendre_un_agenda_vide(jour):
    with pytest.raises(ValueError):
        asyncio.run(rdv.lire_jours(_db({}), "enfant-1", jour, "2026-09-08"))


def test_une_fenetre_a_l_envers_leve():
    with pytest.raises(ValueError):
        asyncio.run(rdv.lire_jours(_db({}), "enfant-1", "2026-09-09", "2026-09-08"))


def test_un_identifiant_inconnu_n_est_pas_un_rendez_vous_vide():
    """Le nœud absent rend `{}` : traduit, il ressortirait en rendez-vous sans date
    ni cliente — un objet qu'on prend pour un rendez-vous mal rempli."""
    assert asyncio.run(rdv.lire_un(_db({}), "enfant-1", "inconnu")) is None


# ── Les noms des champs ──────────────────────────────────────────────────────

_STOCKE = {
    "s": "2026-09-08 14:30", "st": 870, "d": 45, "ca": "enfant-1",
    "cu": {"id": "cli-1", "name": "NE DOIT PAS SORTIR", "phone": "0000"},
    "cat": 1_757_000_000_000, "uat": 1_757_000_100_000, "cby": "website",
    "se": "presta-1", "sq": "seq-1", "p": 4500, "c": "texte libre",
    "r": {"id": "tick-1", "periodId": "per-1"},
    "opdm": 1, "bb": True,
}


def test_les_abreviations_stockees_ressortent_nommees():
    v = rdv.traduire("vev-1", "enfant-1", _STOCKE)
    assert v["id"] == "vev-1" and v["child_id"] == "enfant-1"
    assert v["start"] == "2026-09-08T14:30" and v["date"] == "2026-09-08"
    assert v["duration_minutes"] == 45 and v["start_minutes"] == 870
    assert v["service_id"] == "presta-1" and v["price_cents"] == 4500
    assert v["customer_id"] == "cli-1"
    assert v["receipt"] == {"id": "tick-1", "period_id": "per-1"}


def test_la_fin_se_calcule_et_n_invente_pas_de_fuseau():
    """Planity stocke l'heure murale du salon. Lui coller un décalage serait faux la
    moitié de l'année, et une heure de décalage ne se voit pas."""
    v = rdv.traduire("vev-1", "enfant-1", _STOCKE)
    assert v["end"] == "2026-09-08T15:15"
    assert "+" not in v["end"] and "Z" not in v["end"]


def test_un_rendez_vous_annule_se_reconnait_a_sa_date_de_suppression():
    """Il n'y a PAS de champ « statut » : sans cette lecture, un agenda d'annulations
    se compte comme un agenda plein."""
    vivant = rdv.traduire("v", "e", _STOCKE)
    annule = rdv.traduire("v", "e", dict(_STOCKE, dat=1_757_000_200_000, dby="pro-1"))
    assert vivant["cancelled"] is False and vivant.get("cancelled_at") is None
    assert annule["cancelled"] is True
    assert annule["cancelled_at"] == 1_757_000_200_000 and annule["cancelled_by"] == "pro-1"


def test_le_canal_de_reservation_distingue_le_site_du_salon():
    assert rdv.traduire("v", "e", _STOCKE)["booked_via"] == "website"
    assert rdv.traduire("v", "e", dict(_STOCKE, cby="n"))["booked_via"] == "pro"


def test_le_brut_est_conserve_sous_raw():
    """C'est la perte du brut qui a rendu tout un catalogue à zéro euro : le champ
    avait changé de nom et plus personne ne pouvait le voir depuis le dessus."""
    v = rdv.traduire("v", "e", _STOCKE)
    assert v["raw"] == _STOCKE


def test_les_abreviations_non_elucidees_ne_recoivent_pas_de_nom_invente():
    """Les baptiser au jugé ferait passer une hypothèse pour une mesure — et un nom
    pareil, plus personne ne le rediscute."""
    v = rdv.traduire("v", "e", _STOCKE)
    for abrege in rdv.ABREGES_NON_ELUCIDES:
        assert abrege not in v
    assert set(rdv.ABREGES_NON_ELUCIDES) & set(_STOCKE) <= set(v["raw"])


# ── Le prix d'une prestation ─────────────────────────────────────────────────

def test_un_prix_ferme_se_lit_dans_prices_pas_dans_price():
    """`price` n'existe sur AUCUNE prestation. Le lire rendait `0.00` partout, et un
    zéro ne lève pas — il se lit comme une prestation offerte."""
    p = services.prix({"prices": {"default": 4500}})
    assert p["kind"] == services.FIXE and p["default_cents"] == 4500


def test_une_fourchette_reste_une_fourchette():
    p = services.prix({"prices": {"min": 3000, "max": 6000}})
    assert p["kind"] == services.FOURCHETTE
    assert (p["min_cents"], p["max_cents"]) == (3000, 6000)
    assert p["default_cents"] is None, "une fourchette n'a pas de prix ferme"


def test_sur_devis_n_est_pas_gratuit():
    p = services.prix({"prices": {"onQuotation": True}})
    assert p["kind"] == services.SUR_DEVIS and p["default_cents"] is None


def test_une_prestation_sans_prix_le_dit():
    """Une prestation sur deux n'a pas de `prices` du tout. `0` la ferait compter
    dans un chiffre d'affaires prévisionnel."""
    for sans in ({}, {"prices": {}}, {"prices": None}):
        assert services.prix(sans)["kind"] == services.ABSENT
        assert services.prix(sans)["default_cents"] is None


def test_le_catalogue_s_aplatit_avec_ses_groupes():
    plat = services.aplatir({"grp-1": {"name": "Coiffure", "children": {
        "presta-1": {"name": " Coupe ", "duration": 30, "prices": {"default": 3000}}}}})
    assert plat == [{
        "id": "presta-1", "category_id": "grp-1", "category_name": "Coiffure",
        "name": "Coupe", "duration_minutes": 30, "bookable": True,
        "description": "", "sequence": None,
        "deleted_at": None, "category_deleted_at": None, "deleted": False,
        "prices": {"kind": services.FIXE, "default_cents": 3000,
                   "min_cents": 3000, "max_cents": 3000}}]


def test_une_prestation_vivante_dans_un_groupe_supprime_est_supprimee():
    """Elle ne se propose plus. Sans ça, un catalogue périmé se présente comme une
    offre — et c'est le groupe, pas la prestation, qui porte la date."""
    plat = services.aplatir({"grp-1": {"deletedAt": 7, "children": {
        "presta-1": {"name": "Coupe"}}}})
    assert plat[0]["deleted"] is True
    assert plat[0]["deleted_at"] is None and plat[0]["category_deleted_at"] == 7


def test_un_enfant_d_agenda_supprime_le_dit():
    """Quatre enfants supprimés sur sept : sans `deleted`, le salon annonce sept
    collaboratrices quand il en a trois."""
    from oto.tools.planity.client import Employee

    assert Employee(id="e", name="X").deleted is False
    assert Employee(id="e", name="X", deleted_at=7).deleted is True


# ── Le stock ─────────────────────────────────────────────────────────────────

_PRODUIT = {
    "name": "Shampooing", "eanCode": "000", "price": 1500,
    "stocks": {"lot-1": {"quantity": 4, "purchasePrice": 700, "createdAt": 2},
               "lot-2": {"quantity": 3, "purchasePrice": 800, "createdAt": 1}},
}


def test_le_stock_est_la_somme_des_lots_et_les_lots_restent():
    """Le prix d'achat vit dans le LOT : l'écraser en un total fait disparaître la
    marge, qui est tout l'intérêt d'une prévision de commande."""
    p = stock.produit("prod-1", "cat-1", _PRODUIT)
    assert p["stock_total"] == 7
    assert [l["quantity"] for l in p["stock_lots"]] == [3, 4], "lots non triés par date"
    assert [l["purchase_price_cents"] for l in p["stock_lots"]] == [800, 700]


def test_un_seuil_non_renseigne_n_est_pas_zero():
    """`0` en seuil ferait commander tout, tout le temps."""
    p = stock.produit("prod-1", "cat-1", _PRODUIT)
    assert p["stock_threshold"] is None and p["stock_ceiling"] is None
    assert p["supplier_id"] is None


def test_un_produit_supprime_le_dit():
    p = stock.produit("prod-1", "cat-1", dict(_PRODUIT, deletedAt=1_757_000_000_000))
    assert p["deleted"] is True and p["deleted_at"] == 1_757_000_000_000


def test_un_prix_d_achat_qui_n_est_pas_un_nombre_ne_devient_pas_un_montant():
    """`purchasePrice` vaut aussi la chaîne `"any"`. Le convertir sans regarder lève
    au premier mouvement de ce genre, au milieu d'une lecture par ailleurs bonne —
    et le forcer à `0` en ferait un achat gratuit."""
    nombre = stock.mouvement("p", "m", {"purchasePrice": 700})
    autre = stock.mouvement("p", "m", {"purchasePrice": "any"})
    assert (nombre["purchase_price_cents"], nombre["purchase_price_raw"]) == (700, 700)
    assert autre["purchase_price_cents"] is None
    assert autre["purchase_price_raw"] == "any"


def test_les_mouvements_se_lisent_par_produit_sur_une_plage():
    db = _db({})
    asyncio.run(stock.lire_mouvements(db, "biz-1", ["prod-1"], 10, 20))
    trame = _trame(db)
    assert trame["p"] == "business_stock_movements/biz-1/prod-1"
    assert trame["q"] == {"i": "createdAt", "sp": 10, "ep": 20}
    assert trame["t"], "la lecture des mouvements est partie sans tag"


# ── La caisse ────────────────────────────────────────────────────────────────

_TICKET = {
    "number": 12, "createdAt": 1_757_000_000_000, "operationType": "SALE",
    "linesCount": 1, "userId": "pro-1", "userName": "Vendeuse",
    "lines": {"l1": {"title": "Coupe", "price": 4500, "quantity": 1,
                     "serviceId": "presta-1", "vatRate": 20}},
    "paymentMethods": {"p1": {"method": "CB", "amount": 4500, "tpeTip": 0}},
    "vatIncludedTotal": 4500, "vatTotal": 750,
    "customer": {"id": "cli-1", "name": "NE DOIT PAS SORTIR", "phone": "0000"},
    "appointment": {"vev-1": {"start": "x"}},
}


def test_un_ticket_porte_ses_lignes_ses_paiements_et_son_lien_agenda():
    t = pos.ticket("tick-1", _TICKET)
    assert t["lines"][0]["price_cents"] == 4500 and t["lines"][0]["title"] == "Coupe"
    assert t["payments"][0] == {"method": "CB", "amount_cents": 4500, "tip_cents": 0}
    assert t["appointment_ids"] == ["vev-1"], "le lien RDV est la CLÉ, pas une valeur"
    assert t["customer_id"] == "cli-1"


def test_un_ticket_annule_se_reconnait_a_son_statut():
    """L'absence de `status` VAUT « normal » : le rendre `None` sans le dire ferait
    lire un ticket ordinaire comme un statut inconnu."""
    assert pos.ticket("t", _TICKET)["cancelled"] is False
    annule = pos.ticket("t", dict(_TICKET, status="CANCELLED", cancelledAt=1, cancelledBy="pro-1"))
    assert annule["cancelled"] is True and annule["cancelled_by"] == "pro-1"


def test_une_liste_de_periodes_ne_charge_pas_les_tickets():
    """Une période porte des dizaines de tickets, chacun avec un instantané de
    cliente : les embarquer pour compter des sessions ferait transiter des milliers
    de fiches."""
    valeur = {"per-1": {"createdAt": 11, "closedAt": 12, "receipts": {"t1": _TICKET}}}
    periodes = asyncio.run(pos.lire_periodes(_db(valeur), "biz-1", 10, 20))
    assert periodes[0]["receipts_count"] == 1
    assert "receipts" not in periodes[0]


def test_les_periodes_se_lisent_sur_une_plage_de_dates():
    db = _db({})
    asyncio.run(pos.lire_periodes(db, "biz-1", 10, 20, limite=5))
    trame = _trame(db)
    assert trame["p"] == "pos_periods/biz-1"
    assert trame["q"] == {"i": "createdAt", "sp": 10, "ep": 20, "l": 5, "vf": "l"}


def test_un_ticket_vit_sous_sa_periode():
    db = _db({})
    asyncio.run(pos.lire_ticket(db, "biz-1", "per-1", "tick-1"))
    assert _trame(db)["p"] == "pos_periods/biz-1/per-1/receipts/tick-1"


# ── La connexion qui meurt sans le dire ─────────────────────────────────────

def test_un_socket_mort_est_rouvert_avant_la_lecture():
    """L'amont raccroche sur une connexion inactive, sans trame de fermeture. La
    servir telle quelle fait échouer TOUT ce qui passe par ce shard."""
    db = _db({"a": 1}, close_code=1006)
    assert db.est_ouverte() is False
    assert asyncio.run(db.get("noeud/x")) == {"a": 1}
    assert (db.reconnexions, db.connexions) == (1, 1)


def test_un_socket_vivant_n_est_pas_rouvert():
    """La vérification ne coûte AUCUNE I/O : sur un socket vivant, elle ne fait
    rien. Sans cette moitié-là, on paierait une poignée de main par lecture."""
    db = _db({"a": 1})
    asyncio.run(db.get("noeud/x"))
    asyncio.run(db.get("noeud/x"))
    assert (db.reconnexions, db.connexions) == (0, 0)


def test_mort_puis_vivant_puis_mort_puis_vivant():
    """Le pool doit SAVOIR à chaque fois qu'un socket est mort, pas se réparer une
    seule fois : une connexion rouverte redevient inactive, donc remeurt."""
    db = _db({"a": 1}, close_code=1006)
    assert asyncio.run(db.get("noeud/x")) == {"a": 1}
    db.ws.close_code = 1006                       # elle remeurt, comme en vrai
    assert asyncio.run(db.get("noeud/x")) == {"a": 1}
    assert db.reconnexions == 2, "la seconde mort n'a pas été vue"


def test_un_pair_qui_part_pendant_la_lecture_donne_une_seule_reprise():
    """La pré-vérification ne peut pas voir un pair qui s'en va entre le test et
    l'envoi. Une reprise, sur un socket neuf — et une seule."""
    db = _db({"a": 1}, coupures=1)
    assert asyncio.run(db.get("noeud/x")) == {"a": 1}
    assert db.reconnexions == 1


def test_une_coupure_qui_se_repete_remonte_au_lieu_de_boucler():
    """Une reprise, pas une boucle : si le pair coupe encore, l'appelant doit le
    savoir. Réessayer sans fin transformerait une panne en attente."""
    from websockets.exceptions import ConnectionClosed

    db = _db({"a": 1}, coupures=5)
    with pytest.raises(ConnectionClosed):
        asyncio.run(db.get("noeud/x"))
    assert db.reconnexions == 1, "plus d'une reprise"


def test_deux_lectures_concurrentes_n_ouvrent_qu_une_connexion():
    """Deux ouvertures laisseraient un socket orphelin — ouvert chez le tiers, hors
    du pool, jamais fermé."""
    db = _db({"a": 1}, close_code=1006)

    async def deux():
        return await asyncio.gather(db.get("noeud/x"), db.get("noeud/y"))

    assert asyncio.run(deux()) == [{"a": 1}, {"a": 1}]
    assert db.reconnexions == 1


def test_un_refus_de_l_amont_n_est_PAS_repris():
    """Une reprise ne couvre qu'un pair parti. Rejouer un refus le masquerait, et
    doublerait le temps d'attente de tout appel condamné."""
    db = _db()

    async def _refus(rid, timeout=10.0, data_collector=None):
        return {"s": "permission_denied", "d": None}

    db._recv_until_reply = _refus
    with pytest.raises(RuntimeError, match="permission_denied"):
        asyncio.run(db.get("noeud/x"))
    assert db.reconnexions == 0
