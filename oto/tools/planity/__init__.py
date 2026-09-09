"""Client Planity (agenda + caisse d'un salon) — LECTURE SEULE.

Planity n'a pas d'API publique : tout ce package rejoue ce que fait la webapp
`pro.planity.com`, sur trois transports distincts qu'il faut tous les trois pour
répondre à une question métier (`README.md` porte le détail du protocole) :

- **Firebase Realtime Database en WebSocket** (`firebase_ws`) — le référentiel et
  l'agenda. Le REST de Firebase répond `permission_denied` sur presque tous les
  chemins, même avec un jeton valide : le WebSocket n'est pas une optimisation,
  c'est le seul chemin qui marche. La base est **shardée** (maître, shard métier
  du salon, shard de calendrier).
- **Les lambdas REST de Planity** (`rest_api`) — chiffre d'affaires, tickets,
  statistiques.
- **Algolia** (`algolia`) — la recherche de clientes, sur un index global dont la
  clé rendue par Planity porte déjà le filtre du salon.

`PlanityClient` orchestre les trois derrière une seule chaîne d'authentification
(`auth`, trois étapes, jeton d'une heure). Tout est **asynchrone** : le protocole
Firebase est un WebSocket, il n'a pas d'équivalent synchrone.

Aucune écriture n'est exposée : pas de création ni de modification de rendez-vous.
"""
from __future__ import annotations

from .auth import PlanityAuth, PlanityTokens
from .client import Employee, PlanityClient, SalonInfo
from .date_range import ms_to_iso, resolve_range

__all__ = [
    "Employee",
    "PlanityAuth",
    "PlanityClient",
    "PlanityTokens",
    "SalonInfo",
    "ms_to_iso",
    "resolve_range",
]
