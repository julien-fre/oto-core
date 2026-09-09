"""Le client de DONNÉES — profil, médias, insights d'un compte professionnel.

Il ne connaît que deux choses : un jeton et l'identifiant du compte. Ni App ID,
ni secret : ils ne servent qu'à obtenir le jeton (`oauth.py`), pas à s'en servir.

**Synchrone**, comme le reste de la lib : cette API est en HTTPS simple, et rien
dans l'amont n'impose une boucle d'événements. L'appelant qui vit dans une boucle
(un serveur mono-loop, par exemple) fait tourner ces appels au fil d'exécution ;
c'est son affaire, et ça lui coûte moins qu'un paquet asynchrone de plus.

**Le brut est rendu tel quel.** Ces méthodes ne recomposent pas, ne renomment pas
et n'inventent pas de champ : ce que Meta rend est ce que l'appelant reçoit. La
seule mise en forme est l'aplatissement des insights, dont la structure imbriquée
(`data[].total_value.value` OU `data[].values[0].value`) n'est pas une
information mais un artefact du format.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

import requests

from . import _transport
from .config import GRAPH_API_BASE, HTTP_TIMEOUT

#: Métriques d'insights par `media_product_type`. **Pas de liste de secours** : si
#: un type n'est pas ici, on le DIT plutôt que de demander un jeu générique — une
#: métrique refusée fait échouer tout l'appel, et le message parlerait alors de la
#: métrique au lieu du type de média.
MEDIA_INSIGHT_METRICS: dict[str, tuple[str, ...]] = {
    "FEED": ("reach", "views", "likes", "comments", "saved", "shares",
             "total_interactions", "follows", "profile_visits"),
    "AD": ("reach", "views", "likes", "comments", "saved", "shares",
           "total_interactions", "follows", "profile_visits"),
    "REELS": ("reach", "views", "likes", "comments", "saved", "shares",
              "total_interactions", "ig_reels_avg_watch_time",
              "ig_reels_video_view_total_time"),
    "STORY": ("reach", "views", "replies", "shares", "total_interactions",
              "follows", "profile_visits"),
}

#: Métriques de COMPTE, toutes en `metric_type=total_value`, `period=day`.
#: ⚠️ `profile_views`, `website_clicks` et `impressions` n'existent PLUS dans cette
#: variante de l'API : demander l'une des trois fait échouer l'appel entier, pas
#: seulement la métrique. `profile_links_taps` remplace les deux premières.
ACCOUNT_INSIGHT_METRICS: tuple[str, ...] = (
    "reach", "views", "accounts_engaged", "total_interactions",
    "likes", "comments", "saves", "shares", "profile_links_taps",
)

#: Fenêtre maximale acceptée sur `since`/`until` pour les insights de compte.
ACCOUNT_INSIGHTS_MAX_DAYS = 30

PROFILE_FIELDS = ("user_id,username,name,biography,followers_count,follows_count,"
                  "media_count,profile_picture_url,website")

MEDIA_FIELDS = ("id,caption,timestamp,media_type,media_product_type,"
                "like_count,comments_count,permalink")


def flatten_insights(payload: dict) -> dict[str, Any]:
    """`{métrique: valeur}` depuis une réponse d'insights.

    Deux formes selon le `metric_type` demandé : `total_value.value` d'un côté,
    une liste `values` datée de l'autre, dont on prend la première entrée. Une
    métrique sans valeur vaut 0 — c'est ce que Meta veut dire par une liste vide,
    et rendre `None` obligerait chaque lecteur à le retraduire."""
    out: dict[str, Any] = {}
    for ins in payload.get("data", []) or []:
        nom = ins.get("name")
        if not nom:
            continue
        total = ins.get("total_value") or {}
        if "value" in total:
            out[nom] = total["value"]
            continue
        valeurs = ins.get("values") or []
        out[nom] = valeurs[0].get("value") if valeurs else 0
    return out


class InstagramClient:
    """Lecture seule sur un compte Instagram professionnel.

    `renew` — appelé UNE fois par client si Meta rejette le jeton en cours d'appel
    (révocation, rotation), et doit rendre un jeton neuf. C'est un rattrapage, pas
    la politique de renouvellement : celle-ci est préventive et vit chez l'appelant
    (`tokens.needs_refresh`), qui seul sait où le jeton est rangé. Sans `renew`, un
    rejet remonte tel quel — ce qui est le bon défaut pour un appelant qui n'a rien
    à réécrire.
    """

    def __init__(self, access_token: str, user_id: str, *,
                 renew: Optional[Callable[[], str]] = None,
                 session: Optional[requests.Session] = None):
        if not access_token or not user_id:
            raise ValueError(
                "InstagramClient : jeton et identifiant de compte requis — les deux "
                "viennent du consentement (`oauth.connect`).")
        self.access_token = access_token
        self.user_id = str(user_id)
        self._renew = renew
        self._renouvele = False
        self._http = session or requests

    def _get(self, chemin: str, geste: str, **params: Any) -> dict:
        """Un GET de données, avec un seul rattrapage de jeton.

        « Une seule fois » est le point : sans compteur, un jeton que Meta refuse
        pour une autre raison que sa mort ferait boucler l'appel entre le refus et
        le renouvellement."""
        url = f"{GRAPH_API_BASE}{chemin}"
        r = self._http.get(url, params={**params, "access_token": self.access_token},
                           timeout=HTTP_TIMEOUT)
        if (r.status_code != 200 and self._renew and not self._renouvele
                and _transport.jeton_mort(r.status_code, _corps(r))):
            self._renouvele = True
            self.access_token = self._renew()
            r = self._http.get(url, params={**params, "access_token": self.access_token},
                               timeout=HTTP_TIMEOUT)
        return _transport.lire(r, geste)

    def get_profile(self) -> dict:
        return self._get(f"/{self.user_id}", "la lecture du profil",
                         fields=PROFILE_FIELDS)

    def get_recent_media(self, limit: int = 10) -> list[dict]:
        res = self._get(f"/{self.user_id}/media", "la lecture des publications",
                        fields=MEDIA_FIELDS, limit=limit)
        return res.get("data", []) or []

    def get_media_insights(self, media_id: str) -> dict[str, Any]:
        """Insights d'une publication — les métriques dépendent de son type.

        Le type se LIT d'abord, il ne se devine pas : demander les métriques d'un
        post de fil sur un reel fait échouer l'appel entier."""
        meta = self._get(f"/{media_id}", "la lecture du type de publication",
                         fields="media_type,media_product_type")
        produit = str(meta.get("media_product_type") or "").upper()
        metriques = MEDIA_INSIGHT_METRICS.get(produit)
        if not metriques:
            raise ValueError(
                f"Insights non gérés pour cette publication : "
                f"media_product_type={produit or '?'}, "
                f"media_type={meta.get('media_type') or '?'} "
                f"(types gérés : {', '.join(sorted(MEDIA_INSIGHT_METRICS))}).")
        res = self._get(f"/{media_id}/insights", "la lecture des insights",
                        metric=",".join(metriques))
        return flatten_insights(res)

    def get_account_insights(self, days: int = 30) -> dict[str, Any]:
        if not 1 <= days <= ACCOUNT_INSIGHTS_MAX_DAYS:
            raise ValueError(
                f"days doit être entre 1 et {ACCOUNT_INSIGHTS_MAX_DAYS} — c'est la "
                f"fenêtre maximale de l'API sur les insights de compte.")
        until = int(time.time())
        res = self._get(f"/{self.user_id}/insights", "la lecture des statistiques du compte",
                        metric=",".join(ACCOUNT_INSIGHT_METRICS), period="day",
                        metric_type="total_value",
                        since=until - days * 86_400, until=until)
        return flatten_insights(res)


def _corps(reponse) -> Any:
    """Le JSON d'une réponse, ou `None` — pour interroger `jeton_mort` sans lever."""
    try:
        return reponse.json()
    except ValueError:
        return None
