"""Les trois refus de ce connecteur — distincts parce qu'ils appellent trois gestes.

Le sujet n'est pas la taxonomie : c'est qu'un appelant sache **quoi dire à qui**.
Sur cette API, trois causes se ressemblent en HTTP (toutes des 400 avec un corps
`OAuthException`) et ne se ressemblent pas du tout du point de vue de la personne :

- son autorisation est **morte** (60 jours passés, ou révoquée) → elle doit
  reconnecter son compte, et rien d'autre ne peut le faire à sa place ;
- Meta **refuse le consentement** — typiquement parce que le compte n'est pas
  invité comme testeur tant que l'application n'est pas publiée → ce n'est pas
  elle qui peut le régler, c'est l'exploitant ;
- l'appel a **échoué** pour tout le reste → réessayer a un sens.

Les confondre coûte cher dans ce sens précis : un refus d'autorisation présenté
comme une panne fait réessayer indéfiniment, et une panne présentée comme une
autorisation morte fait refaire un consentement parfaitement inutile.

⚠️ **Aucun message d'ici ne nomme d'outil ni d'écran.** La lib ne connaît pas la
surface qui l'appelle (un serveur MCP, une CLI, un travail périodique) ; c'est à
elle de traduire un fait en geste, avec les mots de son produit.
"""
from __future__ import annotations

from typing import Optional


class InstagramError(RuntimeError):
    """Racine — tout ce que ce connecteur lève lui-même."""


class InstagramAuthExpired(InstagramError):
    """L'autorisation est morte : jeton expiré, révoqué, ou renouvellement refusé.

    Un jeton Instagram long vit 60 jours et **ne se renouvelle que tant qu'il
    vit** : il n'y a pas de `refresh_token` qui survivrait à son expiration. Passé
    ce terme, rien ne le rattrape — il faut un nouveau consentement.

    `expires_at` porte l'échéance quand on la connaît, pour que l'appelant puisse
    la DIRE. « Ton autorisation a expiré » sans date se lit comme une panne ;
    avec la date, ça se lit comme ce que c'est."""

    def __init__(self, message: str, expires_at: Optional[str] = None):
        super().__init__(message)
        self.expires_at = expires_at


class InstagramAuthRefused(InstagramError):
    """Meta a refusé le consentement ou l'échange du code.

    `reason` reprend le code que Meta a rendu quand il y en a un, pour que
    l'appelant compose son message sans re-deviner la cause."""

    def __init__(self, message: str, reason: str = ""):
        super().__init__(message)
        self.reason = reason


class InstagramApiError(InstagramError):
    """L'appel a échoué pour une autre raison — réessayer a un sens.

    `status` = le code HTTP quand il y en a un. **Le corps de la réponse n'y entre
    pas** : il porte le jeton sur certains chemins d'erreur, et ce texte-là finit
    dans un transcript d'agent."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status
