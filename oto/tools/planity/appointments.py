"""Les rendez-vous d'un agenda : où ils vivent, et comment se lisent leurs clés.

Trois choses décident ici, et chacune échoue en rendant « rien » plutôt qu'une
erreur — c'est pourquoi elles ont leur module :

1. **L'adresse.** Les rendez-vous sont sous `calendar_vevents/<enfant d'agenda>`,
   pas sous `calendars/<agenda>/vevents` : la clé est l'ENFANT (la collaboratrice),
   pas l'agenda. Et ils vivent sur le **shard métier** du salon quand il en a un —
   la base `calendars-N` ne les sert qu'à défaut.
2. **La borne.** L'index `s` porte `"YYYY-MM-DD HH:MM"`, comparé comme une CHAÎNE :
   une borne de fin à `"YYYY-MM-DD"` ne matche rien du tout (toute valeur du jour
   trie après elle) et rend un agenda vide qu'on lit comme une journée sans
   rendez-vous. La borne se calcule ici, une fois (`_fin_de_journee`).
3. **Les noms.** Le stockage est abrégé (`s`, `st`, `d`, `cu`…). Les mêmes champs
   portent leur nom ENTIER dans `calendar_recurring_vevents` : les deux nœuds
   décrivent le même objet, et c'est cette correspondance que traduit `_NOMS`.

⚠️ **Un rendez-vous porte les coordonnées de la cliente** : `cu` est un sous-objet
`{id, name, email, phone}`. Ce module est une bibliothèque et rend ce que Planity
donne ; c'est à la frontière d'un outil que la projection se décide, et elle s'y
réduit à l'IDENTIFIANT. Voir la note du connecteur côté backend.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .firebase_ws import FirebaseRTDB, range_on

#: Le nœud des rendez-vous ponctuels, et celui des récurrents. Tous deux sont
#: indexés par ENFANT d'agenda.
NOEUD_VEVENTS = "calendar_vevents"
NOEUD_RECURRENTS = "calendar_recurring_vevents"

#: L'index de tri des rendez-vous, et le format exact de ses valeurs.
INDEX_JOUR = "s"
_JOUR = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DEBUT = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

#: La correspondance abrégé → nom entier. Elle se lit dans le nœud des récurrents,
#: qui porte les mêmes champs sans les abréger.
_NOMS = {
    "s": "start",                     # "YYYY-MM-DD HH:MM", heure locale du salon
    "st": "start_minutes",            # minutes depuis minuit — redit l'heure de `s`
    "d": "duration_minutes",
    "ca": "calendar_child_id",
    "cu": "customer",                 # {id, name, email, phone} — cf. l'avertissement
    "cat": "created_at",
    "uat": "updated_at",
    "cby": "created_by",
    "se": "service_id",
    "sq": "sequence",
    "p": "price_cents",
    "seo": "service_origin_id",
    "seoi": "service_origin_index",
    "seop": "service_origin_price_cents",
    "ud": "user_duration_minutes",
    "c": "comment",
    "r": "receipt",                   # {id, periodId} — le ticket de caisse
    "dat": "cancelled_at",
    "dby": "cancelled_by",
    "t": "title",
    "ad": "all_day",
}

#: Les abréviations sans équivalent dans le nœud des récurrents : elles restent
#: sous `raw` et ne reçoivent PAS de nom. Les baptiser au jugé ferait passer une
#: hypothèse pour un fait, et c'est le genre de nom que plus personne ne rediscute.
ABREGES_NON_ELUCIDES = ("rf", "opdm", "bb", "nc", "sca")


def _fin_de_journee(jour: str) -> str:
    """La borne haute qui inclut TOUTE la journée sur l'index `s`.

    `"2026-09-08"` seul exclurait la journée entière : `"2026-09-08 09:30"` lui est
    postérieur en comparaison de chaînes. La fin de journée s'écrit donc dans le
    format de l'index."""
    return f"{jour} 23:59"


def _exiger_jour(nom: str, valeur: str) -> str:
    if not isinstance(valeur, str) or not _JOUR.match(valeur):
        raise ValueError(
            f"{nom} se donne en jour `AAAA-MM-JJ` (reçu {valeur!r}) : l'index des "
            f"rendez-vous se compare comme une chaîne, une autre forme ne lève pas "
            f"— elle rend un agenda vide.")
    return valeur


def _fin(debut: str, minutes: Any) -> Optional[str]:
    """`start` + durée, dans le même format et sans inventer de fuseau.

    Planity stocke l'heure MURALE du salon, sans décalage. Lui en coller un ici
    serait faux la moitié de l'année, et un rendez-vous décalé d'une heure ne se
    voit pas — il se lit comme un rendez-vous."""
    if not _DEBUT.match(debut or "") or not isinstance(minutes, (int, float)):
        return None
    from datetime import datetime, timedelta

    fin = datetime.strptime(debut, "%Y-%m-%d %H:%M") + timedelta(minutes=int(minutes))
    return fin.strftime("%Y-%m-%dT%H:%M")


def traduire(vevent_id: str, child_id: str, brut: dict) -> dict:
    """Un rendez-vous stocké → ses champs nommés, `raw` compris.

    `raw` est conservé DÉLIBÉRÉMENT : c'est la perte du brut qui a fait rendre
    `price_eur: 0.00` au catalogue de prestations pendant des semaines — le champ
    avait changé de nom, et plus personne ne pouvait le voir depuis le dessus.
    Ce que `raw` ne doit pas faire, c'est traverser la frontière d'un outil : il
    porte la cliente en clair."""
    if not isinstance(brut, dict):
        raise TypeError(f"un rendez-vous est un objet, pas {type(brut).__name__}")
    sortie: dict = {"id": vevent_id, "child_id": child_id}
    for abrege, nom in _NOMS.items():
        if abrege in brut:
            sortie[nom] = brut[abrege]
    debut = sortie.get("start")
    sortie["date"] = debut[:10] if isinstance(debut, str) and _DEBUT.match(debut) else None
    sortie["start"] = debut.replace(" ", "T") if isinstance(debut, str) and _DEBUT.match(debut) else debut
    sortie["end"] = _fin(debut if isinstance(debut, str) else "", sortie.get("duration_minutes"))
    client = sortie.get("customer")
    sortie["customer_id"] = client.get("id") if isinstance(client, dict) else None
    ticket = sortie.get("receipt")
    if isinstance(ticket, dict):
        sortie["receipt"] = {"id": ticket.get("id"), "period_id": ticket.get("periodId")}
    # Un rendez-vous annulé n'a PAS de champ « statut » : il a une date de
    # suppression. Sans cette ligne, un agenda annulé se compte comme un agenda plein.
    sortie["cancelled"] = sortie.get("cancelled_at") is not None
    sortie["booked_via"] = "website" if brut.get("cby") == "website" else "pro"
    sortie["raw"] = brut
    return sortie


async def lire_jours(db: FirebaseRTDB, child_id: str, jour_debut: str,
                     jour_fin: str) -> list[dict]:
    """Les rendez-vous d'UN enfant d'agenda entre deux jours, bornes comprises."""
    _exiger_jour("jour_debut", jour_debut)
    _exiger_jour("jour_fin", jour_fin)
    if jour_fin < jour_debut:
        raise ValueError(f"fenêtre à l'envers : {jour_debut} → {jour_fin}")
    brut = await db.get(
        f"{NOEUD_VEVENTS}/{child_id}",
        range_on(INDEX_JOUR, jour_debut, _fin_de_journee(jour_fin)))
    if not isinstance(brut, dict):
        return []
    return [traduire(vid, child_id, v) for vid, v in brut.items() if isinstance(v, dict)]


async def lire_un(db: FirebaseRTDB, child_id: str, vevent_id: str) -> Optional[dict]:
    """Un rendez-vous précis, ou `None` s'il n'est pas dans cet agenda."""
    brut = await db.get(f"{NOEUD_VEVENTS}/{child_id}/{vevent_id}")
    # Un identifiant inconnu rend `{}`, pas `None` : sans ce test, il ressortirait
    # traduit en rendez-vous SANS date ni cliente — un objet qu'on prend pour un
    # rendez-vous mal rempli, alors qu'il n'existe pas.
    if not isinstance(brut, dict) or not brut:
        return None
    return traduire(vevent_id, child_id, brut)


async def lire_recurrents(db: FirebaseRTDB, child_id: str,
                          limite: int = 100) -> list[dict]:
    """Les rendez-vous RÉCURRENTS d'un enfant d'agenda.

    Ils ne sont pas dans `calendar_vevents` et n'apparaissent donc dans aucune
    lecture par jour : un agenda qui n'a que des récurrences se lit comme un agenda
    vide. Leurs champs portent déjà leur nom entier — c'est ce nœud qui a servi de
    dictionnaire aux abréviations de l'autre."""
    from .firebase_ws import limit_last

    brut = await db.get(f"{NOEUD_RECURRENTS}/{child_id}", limit_last(limite))
    if not isinstance(brut, dict):
        return []
    sortie = []
    for rid, r in brut.items():
        if not isinstance(r, dict):
            continue
        client = r.get("customer")
        sortie.append({
            "id": rid,
            "child_id": child_id,
            "rrule": r.get("rrule"),
            "duration_minutes": r.get("duration"),
            "user_duration_minutes": r.get("userDuration"),
            "service_id": r.get("service"),
            "sequence": r.get("sequence"),
            "price_cents": r.get("price"),
            "customer_id": client.get("id") if isinstance(client, dict) else None,
            "customer": client,
            "created_at": r.get("createdAt"),
            "created_by": r.get("createdBy"),
            "updated_at": r.get("updatedAt"),
            "all_day": r.get("allDay"),
            "title": r.get("title"),
            "comment": r.get("comment"),
            "raw": r,
        })
    return sortie
