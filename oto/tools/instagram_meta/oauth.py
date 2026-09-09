"""Acquisition de l'autorisation — du clic de l'utilisatrice au jeton de 60 jours.

Trois étapes, dans cet ordre, et aucune n'est facultative :

1. le dialogue d'autorisation (`authorize_url`), que l'appelant ouvre dans un
   navigateur ; Meta revient sur l'URL de retour avec un `code` ;
2. `connect(app, code, redirect_uri)` — le code devient un jeton COURT (une heure),
   que la même fonction échange aussitôt contre un jeton LONG (60 jours), puis
   elle lit l'identité du compte.

Ce module est le seul du paquet à connaître l'`InstagramApp` : l'App ID et le
secret ne servent qu'ici. Le client de données, lui, n'a besoin que du jeton.

⚠️ **L'état anti-rejeu (`state`) n'est PAS fabriqué ici.** Il est signé et vérifié
par l'appelant, qui est le seul à savoir POUR QUI le consentement est demandé (un
identifiant d'utilisateur, une organisation) et à disposer d'un secret de
signature. Une lib qui en inventerait un le rendrait vérifiable par elle seule,
donc inutile à celui qui en a besoin.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

import requests

from . import _transport
from .config import (
    AUTHORIZE_URL,
    GRAPH_API_BASE,
    GRAPH_ROOT,
    HTTP_TIMEOUT,
    LONG_LIVED_TTL_DAYS,
    SCOPES,
    TOKEN_URL,
    InstagramApp,
)
from .errors import InstagramAuthRefused


@dataclass(frozen=True)
class InstagramGrant:
    """Ce qu'un consentement réussi produit, et qu'il faut ranger quelque part.

    `expires_in` est en secondes, tel que Meta le rend — l'appelant en tire la
    date d'échéance qu'il stockera. C'est cette date qui décidera ensuite du
    renouvellement (`tokens.needs_refresh`) : sans elle, on ne peut que subir
    l'expiration."""

    access_token: str
    user_id: str
    username: str
    expires_in: int


def authorize_url(app: InstagramApp, redirect_uri: str, state: str) -> str:
    """L'URL du dialogue de consentement, pour CETTE application et CE retour.

    `redirect_uri` doit être déclarée au byte près dans l'application Meta : c'est
    la faute de configuration la plus fréquente de ce flux, et Meta la signale par
    un écran d'erreur générique qui ne la nomme pas.

    ⚠️ Les permissions partent séparées par des VIRGULES. Un OAuth2 ordinaire les
    sépare par des espaces, et une URL construite « comme d'habitude » obtient ici
    un consentement pour une seule permission — donc un jeton qui lit le profil et
    refuse les insights, beaucoup plus loin."""
    if not redirect_uri:
        raise ValueError("redirect_uri requise : Meta refuse un dialogue sans retour.")
    if not state:
        raise ValueError(
            "state requis : sans lui, un retour de consentement ne peut être rattaché "
            "ni à une personne ni à une demande, et rien n'empêche un rejeu.")
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": app.app_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": ",".join(SCOPES),
        "state": state,
    })


def parse_token_exchange(payload: Any) -> tuple[str, str]:
    """`(access_token, user_id)` depuis la réponse d'échange du code.

    Deux formes circulent selon la version de l'API — plate, ou enveloppée dans
    `data: [...]`. Les deux sont acceptées ; toute autre lève, plutôt que de
    rendre un jeton vide qui échouerait au premier appel de données comme un
    problème de droits."""
    entree = payload
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        if not payload["data"]:
            raise InstagramAuthRefused(
                "Réponse d'échange vide : Instagram n'a rendu aucun jeton.")
        entree = payload["data"][0]
    if not isinstance(entree, dict):
        raise InstagramAuthRefused(
            "Réponse d'échange inattendue : Instagram n'a pas rendu d'objet.")
    jeton, user_id = entree.get("access_token"), entree.get("user_id")
    if not jeton or not user_id:
        manquants = ", ".join(n for n, v in (("access_token", jeton), ("user_id", user_id))
                              if not v)
        raise InstagramAuthRefused(
            f"Réponse d'échange incomplète : {manquants} absent(s).")
    return str(jeton), str(user_id)


def connect(app: InstagramApp, code: str, redirect_uri: str,
            *, session: Optional[requests.Session] = None) -> InstagramGrant:
    """Le code de retour devient un jeton de 60 jours et l'identité du compte.

    Les trois appels sont enchaînés ici parce qu'ils ne valent que groupés : un
    jeton court seul dure une heure et ne sert à rien à stocker, et un jeton long
    sans `user_id` ne permet aucun appel de données (tous les chemins de la Graph
    API sont préfixés par l'identifiant du compte)."""
    if not code:
        raise ValueError("code requis : c'est ce que Meta renvoie sur l'URL de retour.")
    http = session or requests
    # Le code et le secret partent en CORPS form-encodé (RFC 6749 §2.3.1) : en
    # query string ils entreraient dans l'URL, donc dans les journaux des deux
    # côtés. Cette étape-ci le permet ; les deux suivantes non (cf. plus bas).
    r = http.post(TOKEN_URL, data={
        "client_id": app.app_id,
        "client_secret": app.app_secret,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code": code,
    }, timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        _transport.refus_de_consentement(r, "l'échange du code d'autorisation")
    jeton_court, _ = parse_token_exchange(r.json())

    # ⚠️ **Le secret part en query string ici, et ce n'est pas un oubli.** Meta ne
    # sert `ig_exchange_token` qu'en GET avec les paramètres dans l'URL — il n'y a
    # pas de forme en corps à lui préférer. Ce que la règle protège vraiment, on le
    # tient autrement : aucun `raise_for_status()` dans ce paquet (son message porte
    # l'URL), et `_transport` ne laisse jamais sortir ni l'URL ni le corps brut.
    r = http.get(f"{GRAPH_ROOT}/access_token", params={
        "grant_type": "ig_exchange_token",
        "client_secret": app.app_secret,
        "access_token": jeton_court,
    }, timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        _transport.refus_de_consentement(r, "le passage en autorisation longue durée")
    long = r.json()
    jeton_long = long.get("access_token")
    if not jeton_long:
        raise InstagramAuthRefused(
            "Instagram n'a pas rendu d'autorisation longue durée : sans elle, la "
            "connexion durerait une heure.")
    expires_in = int(long.get("expires_in") or LONG_LIVED_TTL_DAYS * 86_400)

    # L'identité du compte. Elle ne sert pas qu'à afficher un nom : `user_id` est
    # l'identifiant de compte professionnel Instagram, et c'est LUI qui préfixe
    # tous les chemins de données. Il n'est pas interchangeable avec l'identifiant
    # rendu à l'étape 1, qui est propre à l'application.
    r = http.get(f"{GRAPH_API_BASE}/me",
                 params={"fields": "user_id,username", "access_token": jeton_long},
                 timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        _transport.refus_de_consentement(
            r, "la lecture du compte autorisé — le compte Instagram est-il bien un "
               "compte professionnel (Business ou Créateur) ?")
    moi = r.json()
    user_id = str(moi.get("user_id") or moi.get("id") or "")
    if not user_id:
        raise InstagramAuthRefused(
            "Instagram a rendu une autorisation mais aucun identifiant de compte "
            "professionnel : rien ne pourrait être lu avec.")
    return InstagramGrant(access_token=jeton_long, user_id=user_id,
                          username=str(moi.get("username") or ""),
                          expires_in=expires_in)
