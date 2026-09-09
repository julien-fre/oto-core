"""Le renouvellement de l'autorisation — quand, et comment.

**La propriété qui gouverne tout ce module : ce jeton ne se renouvelle que tant
qu'il vit.** Il n'y a pas de `refresh_token` chez Meta sur ce produit ; on
échange le jeton courant contre un jeton neuf de 60 jours, et si le courant est
mort, il n'y a rien à échanger. Une connexion qui n'est pas renouvelée à temps
n'est pas dégradée : elle est perdue, et seule l'utilisatrice peut la refaire.

Deux conséquences, portées par le code plutôt que par un commentaire :

- **`is_expired` se demande AVANT `needs_refresh`**. Sur un jeton mort,
  `needs_refresh` rend `False` — non pas parce qu'il va bien, mais parce que le
  renouvellement ne peut plus rien : c'est un nouveau consentement qu'il faut, et
  appeler Meta pour se l'entendre dire ne fait qu'ajouter un aller-retour à
  chaque appel d'une connexion cassée ;
- **le seuil est large** (`RENEW_WHEN_REMAINING_DAYS`, 53 jours sur 60). Un seuil
  serré économiserait des appels et ferait dépendre la survie de la connexion du
  hasard d'un usage dans la dernière ligne droite. Le calcul se fait dans l'autre
  sens : ce qu'on veut, c'est qu'un usage — même très espacé — suffise à tenir.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from . import _transport
from .config import (
    GRAPH_ROOT,
    HTTP_TIMEOUT,
    LONG_LIVED_TTL_DAYS,
    MIN_TOKEN_AGE_HOURS,
    RENEW_WHEN_REMAINING_DAYS,
)
from .errors import InstagramAuthExpired


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """Horodatage UTC, seconde entière, suffixe `Z` — la forme qu'on stocke."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: Optional[str]) -> Optional[datetime]:
    """Un horodatage ISO 8601 en datetime AWARE, ou `None` s'il est absent/illisible.

    Une valeur naïve est lue en UTC : c'est ce que ce paquet écrit, et supposer
    l'heure locale ferait dériver l'échéance de plusieurs heures selon la machine
    qui relit — assez pour renouveler trop tard un jour de bascule."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def expiry(expires_at: Optional[str] = None,
           issued_at: Optional[str] = None) -> Optional[datetime]:
    """L'échéance connue : `expires_at`, sinon `issued_at` + 60 jours, sinon `None`.

    `None` veut dire « on ne sait pas », pas « c'est bon » : sans repère, on ne
    renouvelle pas à l'aveugle — c'est le refus de Meta qui tranchera. Ce cas ne
    devrait pas exister chez un appelant qui stocke ce que `connect` lui a rendu."""
    exp = parse_ts(expires_at)
    if exp:
        return exp
    emis = parse_ts(issued_at)
    return emis + timedelta(days=LONG_LIVED_TTL_DAYS) if emis else None


def is_expired(expires_at: Optional[str] = None, issued_at: Optional[str] = None,
               now: Optional[datetime] = None) -> bool:
    """L'autorisation est-elle déjà morte ? Échéance inconnue ⟹ `False`."""
    exp = expiry(expires_at, issued_at)
    return bool(exp and exp <= (now or utcnow()))


def needs_refresh(expires_at: Optional[str] = None, issued_at: Optional[str] = None,
                  now: Optional[datetime] = None) -> bool:
    """Faut-il renouveler MAINTENANT ? Cf. le contrat en tête de module.

    Trois `False` qui ne veulent pas dire la même chose, et qu'il vaut mieux lire
    ici que déduire : échéance inconnue (rien à calculer), jeton trop JEUNE (Meta
    refuse de renouveler avant 24 h — renouveler tout de suite ferait un refus en
    boucle), et jeton déjà mort (`is_expired` est la question à poser)."""
    maintenant = now or utcnow()
    exp = expiry(expires_at, issued_at)
    if exp is None or exp <= maintenant:
        return False
    emis = parse_ts(issued_at)
    if emis and maintenant - emis < timedelta(hours=MIN_TOKEN_AGE_HOURS):
        return False
    return exp - maintenant < timedelta(days=RENEW_WHEN_REMAINING_DAYS)


def refresh_long_lived(access_token: str, *,
                       expires_at: Optional[str] = None,
                       session: Optional[requests.Session] = None) -> dict:
    """Échange le jeton courant contre un jeton neuf de 60 jours.

    Rend `{"access_token": …, "expires_in": …}` — l'appelant en tire la nouvelle
    échéance et la range là où il range le jeton. Lève `InstagramAuthExpired` si
    Meta refuse : à ce stade, le seul geste possible est un nouveau consentement,
    et `expires_at` (quand l'appelant le connaît) voyage avec l'erreur pour qu'il
    puisse dire la DATE plutôt qu'un « ça ne marche plus ».

    ⚠️ Ce renouvellement ne prend PAS le secret de l'application — le jeton se
    renouvelle tout seul. C'est aussi ce qui rend ce chemin jouable depuis un
    travail périodique qui n'a pas besoin des coordonnées de l'application."""
    if not access_token:
        raise InstagramAuthExpired(
            "Aucune autorisation Instagram à renouveler : le compte n'est pas connecté.",
            expires_at)
    http = session or requests
    # Même remarque que dans `oauth.connect` : Meta ne sert cet endpoint qu'en GET,
    # paramètres dans l'URL. Ce que la règle protège est tenu autrement — pas de
    # `raise_for_status()`, et `_transport` ne rend ni l'URL ni le corps brut.
    r = http.get(f"{GRAPH_ROOT}/refresh_access_token", params={
        "grant_type": "ig_refresh_token",
        "access_token": access_token,
    }, timeout=HTTP_TIMEOUT)
    charge = _transport.lire(r, "le renouvellement de l'autorisation",
                             expires_at=expires_at)
    jeton = charge.get("access_token")
    if not jeton:
        raise InstagramAuthExpired(
            "Instagram a répondu au renouvellement sans rendre d'autorisation neuve.",
            expires_at)
    return {"access_token": str(jeton),
            "expires_in": int(charge.get("expires_in") or LONG_LIVED_TTL_DAYS * 86_400)}
