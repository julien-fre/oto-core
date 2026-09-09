"""Statistiques d'un compte Instagram professionnel — LECTURE SEULE.

Variante « Instagram API with Instagram Login » : la personne se connecte avec son
compte **Instagram**, pas avec Facebook, et aucune Page Facebook n'est requise. Le
jeton obtenu est celui du compte lui-même.

Trois surfaces, séparées par ce dont elles ont besoin :

- `oauth` — obtenir l'autorisation. Seul module qui connaît l'`InstagramApp`
  (App ID + secret) ;
- `tokens` — la maintenir en vie. ⚠️ Ce jeton **ne se renouvelle que tant qu'il
  vit** : pas de `refresh_token` qui survivrait à son expiration, donc une
  connexion laissée dormir 60 jours est perdue, pas dégradée ;
- `client` + `best_hours` — s'en servir. Le client de données n'a besoin QUE du
  jeton et de l'identifiant du compte.

⚠️ **Les coordonnées de l'application ne sont pas ici, et n'y seront pas.** Ce
dépôt est public : une application Meta appartient à celui qui l'a créée, qui
répond de ce qu'elle demande et de qui elle invite comme testeur. Les adresses de
Meta, elles, restent nommées — nommer ce qu'on appelle est le métier d'un client.

Ce paquet est **synchrone** et n'ajoute aucune dépendance : `requests`, le socle
de la lib, suffit à cette API.
"""
from __future__ import annotations

from .best_hours import compute_best_hours
from .client import (
    ACCOUNT_INSIGHT_METRICS,
    ACCOUNT_INSIGHTS_MAX_DAYS,
    MEDIA_INSIGHT_METRICS,
    InstagramClient,
    flatten_insights,
)
from .config import (
    LONG_LIVED_TTL_DAYS,
    MIN_TOKEN_AGE_HOURS,
    RENEW_WHEN_REMAINING_DAYS,
    SCOPES,
    InstagramApp,
)
from .errors import (
    InstagramApiError,
    InstagramAuthExpired,
    InstagramAuthRefused,
    InstagramError,
)
from .oauth import InstagramGrant, authorize_url, connect, parse_token_exchange
from .tokens import (
    expiry,
    is_expired,
    iso,
    needs_refresh,
    parse_ts,
    refresh_long_lived,
    utcnow,
)

__all__ = [
    "ACCOUNT_INSIGHTS_MAX_DAYS",
    "ACCOUNT_INSIGHT_METRICS",
    "InstagramApiError",
    "InstagramApp",
    "InstagramAuthExpired",
    "InstagramAuthRefused",
    "InstagramClient",
    "InstagramError",
    "InstagramGrant",
    "LONG_LIVED_TTL_DAYS",
    "MEDIA_INSIGHT_METRICS",
    "MIN_TOKEN_AGE_HOURS",
    "RENEW_WHEN_REMAINING_DAYS",
    "SCOPES",
    "authorize_url",
    "compute_best_hours",
    "connect",
    "expiry",
    "flatten_insights",
    "is_expired",
    "iso",
    "needs_refresh",
    "parse_token_exchange",
    "parse_ts",
    "refresh_long_lived",
    "utcnow",
]
