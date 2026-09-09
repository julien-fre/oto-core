"""La FORME des coordonnées de Planity, et les bornes de temps. **Aucune valeur.**

⚠️ **Ce module ne porte, et ne portera, aucune constante de Planity.** Il en a porté
trois jusqu'au 2026-09-09. Elles sont publiques par conception (tout navigateur qui
ouvre `pro.planity.com` les reçoit), donc les retirer n'est pas un geste de
sécurité : c'est un geste de GÉNÉRICITÉ. Ce dépôt est public et open source ; un
client qu'on y publie décrit un protocole, il n'embarque pas les coordonnées d'une
entreprise tierce en dur, comme s'il était son intégration officielle. Elles sont
désormais **fournies par l'appelant**, sans valeur par défaut : celui qui déploie
le connecteur les pose, et c'est lui qui répond de ce qu'il appelle.

Sans défaut, et c'est le point : une valeur par défaut aurait remis la constante
ici sous un autre nom, et personne n'aurait vu la différence.
"""
from __future__ import annotations

from dataclasses import dataclass, fields

#: Borne de CHAQUE appel HTTP sortant, posée à l'appel et pas seulement à la
#: construction du client : un client partagé peut être passé par l'appelant, et
#: un appel nu attend alors sans fin. Cf. `tests/test_http_timeouts.py`.
HTTP_TIMEOUT = 30.0

#: La recherche de clientes est interactive : elle a droit à moins d'attente que
#: les lambdas de statistiques, qui agrègent des mois de tickets.
SEARCH_TIMEOUT = 15.0


@dataclass(frozen=True)
class PlanityEndpoints:
    """Où taper, et sous quelle identité d'application — fourni par l'appelant.

    Ce ne sont pas des secrets : elles identifient l'application Planity, elles
    n'autorisent rien à elles seules (ce qui autorise, c'est le mot de passe de la
    personne).
    Elles peuvent donc apparaître dans un message d'erreur ou un journal de
    débogage sans que ce soit une fuite.

    - `firebase_api_key` — clé d'API Firebase Auth, envoyée en `?key=` aux
      endpoints `identitytoolkit` ;
    - `firebase_app_id` — identifiant d'application Firebase, envoyé en `p=` dans
      la poignée de main WebSocket du Realtime Database ;
    - `rest_api` — racine des lambdas REST (statistiques, tickets, credentials de
      recherche), SANS barre oblique finale.
    """

    firebase_api_key: str
    firebase_app_id: str
    rest_api: str

    def __post_init__(self) -> None:
        """Un champ vide LÈVE, ici, plutôt qu'à la première requête.

        Une chaîne vide construit un objet parfaitement valide et produit, plus
        tard et ailleurs, un 400 de Firebase — qu'on lit alors comme « mauvais mot
        de passe ». C'est le mode de panne le plus cher de cette famille : il
        accuse l'utilisatrice d'une erreur de configuration de l'opérateur."""
        vides = [f.name for f in fields(self) if not str(getattr(self, f.name)).strip()]
        if vides:
            raise ValueError(
                f"PlanityEndpoints : {', '.join(vides)} manque(nt). Ces valeurs se "
                f"posent par celui qui déploie le connecteur — il n'y a pas de "
                f"défaut, et il n'y en aura pas.")
        object.__setattr__(self, "rest_api", self.rest_api.rstrip("/"))
