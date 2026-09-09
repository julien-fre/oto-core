"""Lire une réponse de Meta, et traduire un refus dans le vocabulaire d'`errors`.

Trois modules appellent Meta (l'échange du code, le renouvellement, les données)
et les trois reçoivent des corps d'erreur de DEUX formes différentes selon
l'hôte :

    {"error": {"message": …, "type": "OAuthException", "code": 190}}   graph.instagram.com
    {"error_type": "OAuthException", "code": 400, "error_message": …}  api.instagram.com

Recopier la lecture trois fois, c'est se donner deux occasions de ne reconnaître
un jeton mort que sur l'un des trois chemins — et un jeton mort non reconnu se
présente à l'utilisatrice comme une panne passagère qu'elle réessaiera.

⚠️ **Le corps de la réponse ne traverse jamais cette frontière.** Sur cette API
le jeton voyage en paramètre d'URL (c'est le protocole de Meta, pas notre choix),
donc l'URL et parfois l'écho de la requête se retrouvent dans les corps d'erreur.
On rend le STATUT et, quand il est présent, le message rédigé par Meta pour
l'humain (`error.message` / `error_message`) — jamais le corps brut, jamais
l'URL. C'est aussi pourquoi aucun appel de ce paquet n'utilise
`raise_for_status()` : son message porte l'URL appelée.
"""
from __future__ import annotations

from typing import Any, Optional

from .errors import InstagramApiError, InstagramAuthExpired, InstagramAuthRefused

#: Codes d'erreur Meta qui signifient « ce jeton ne vaut plus rien ». 190 =
#: jeton expiré, changé ou révoqué ; 102 = session invalidée.
_CODES_JETON_MORT = (190, 102)


def _erreur(payload: Any) -> dict:
    """Le bloc d'erreur, quelle que soit la forme rendue par l'hôte. `{}` si aucun."""
    if not isinstance(payload, dict):
        return {}
    bloc = payload.get("error")
    if isinstance(bloc, dict):
        return bloc
    if payload.get("error_type") or payload.get("error_message"):
        return {"type": payload.get("error_type"), "code": payload.get("code"),
                "message": payload.get("error_message")}
    return {}


def _entier(valeur: Any) -> Optional[int]:
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return None


def jeton_mort(status: int, payload: Any) -> bool:
    """Meta dit-il que le JETON est mort — par opposition à « l'appel a raté » ?

    La distinction garde un geste destructeur du point de vue de l'utilisatrice :
    l'appelant lui demande un nouveau consentement. Un 400 pour un paramètre
    invalide n'a pas à déclencher ça."""
    if status == 401:
        return True
    bloc = _erreur(payload)
    if _entier(bloc.get("code")) in _CODES_JETON_MORT:
        return True
    return status == 400 and bloc.get("type") == "OAuthException"


def lire(reponse, geste: str, *, expires_at: Optional[str] = None) -> dict:
    """Le corps JSON d'une réponse OK, ou l'erreur d'`errors` qui convient.

    `geste` est la phrase qu'on met dans le message (« la lecture du profil »,
    « le renouvellement de l'autorisation ») : une erreur qui ne dit pas ce qui a
    échoué envoie chercher au mauvais endroit."""
    try:
        payload = reponse.json()
    except ValueError:
        payload = None
    if reponse.status_code == 200:
        if not isinstance(payload, dict):
            raise InstagramApiError(
                f"Réponse illisible d'Instagram sur {geste} (corps non JSON).",
                reponse.status_code)
        return payload
    bloc = _erreur(payload)
    dit = str(bloc.get("message") or "").strip()
    if jeton_mort(reponse.status_code, payload):
        raise InstagramAuthExpired(
            f"Instagram a refusé {geste} : l'autorisation du compte n'est plus "
            f"valable{f' ({dit})' if dit else ''}.", expires_at)
    raise InstagramApiError(
        f"Instagram a refusé {geste} (HTTP {reponse.status_code})"
        f"{f' : {dit}' if dit else ''}.", reponse.status_code)


def refus_de_consentement(reponse, geste: str) -> None:
    """Comme `lire`, mais pour les étapes d'ACQUISITION du jeton.

    Un refus y a une autre cause dominante que « le jeton est mort » — il n'y a
    pas encore de jeton : c'est le consentement lui-même que Meta refuse (compte
    non invité comme testeur tant que l'application n'est pas publiée, code déjà
    consommé, URL de retour non déclarée). D'où une erreur distincte : l'appelant
    a un tout autre message à composer, et il ne s'adresse pas à la même personne."""
    try:
        payload = reponse.json()
    except ValueError:
        payload = None
    bloc = _erreur(payload)
    dit = str(bloc.get("message") or "").strip()
    raise InstagramAuthRefused(
        f"Meta a refusé {geste} (HTTP {reponse.status_code})"
        f"{f' : {dit}' if dit else ''}.", str(bloc.get("type") or ""))
