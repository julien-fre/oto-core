"""Où l'on tape chez Meta, et sous quelle identité d'application.

Deux natures de valeurs, et la ligne entre les deux est le sujet de ce module.

**Les adresses restent ici.** `graph.instagram.com`, `api.instagram.com`, le
dialogue d'autorisation, les permissions demandées : ce sont les coordonnées
PUBLIQUES du produit « Instagram API with Instagram Login », documentées par
Meta et identiques pour tous ceux qui l'appellent. Nommer ce qu'on appelle est
le métier d'un client — un client qui ne nomme rien n'appelle rien.

**L'identité de l'application n'y est pas, et n'y sera pas.** `InstagramApp`
(App ID + secret) est fournie par l'appelant, sans valeur par défaut. Ce dépôt
est public : une application Meta appartient à celui qui l'a créée, qui répond
de ce qu'elle demande et de qui elle invite. Un défaut aurait remis la constante
ici sous un autre nom.

Le partage compte aussi à l'exécution : **le client de DONNÉES n'a besoin que du
jeton**. L'App ID et le secret ne servent qu'à deux moments — l'échange du code
et le passage en jeton long — c'est-à-dire dans `oauth.py`, jamais dans
`client.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, fields

#: Version de la Graph API pour les appels de DONNÉES (profil, médias, insights).
#: Les endpoints d'OAuth, eux, ne sont pas versionnés — d'où les deux racines.
GRAPH_API_VERSION = "v25.0"

#: Racine NON versionnée : elle sert les deux échanges de jeton (`ig_exchange_token`
#: pour passer en jeton long, `ig_refresh_token` pour le renouveler).
GRAPH_ROOT = "https://graph.instagram.com"

#: Base des appels de données, versionnée.
GRAPH_API_BASE = f"{GRAPH_ROOT}/{GRAPH_API_VERSION}"

#: Le dialogue d'autorisation. Il n'y a PAS de Facebook dans cette variante : la
#: personne se connecte avec son compte Instagram, et aucune Page n'est requise.
AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"

#: Échange du code contre un jeton court (POST, corps form-encodé).
TOKEN_URL = "https://api.instagram.com/oauth/access_token"

#: Les permissions demandées dans le dialogue. Elles doivent AUSSI être cochées
#: côté application, sans quoi le consentement aboutit à un jeton qui ne peut pas
#: lire les insights — un échec tardif, sur un appel qui a l'air d'un droit manquant.
#: ⚠️ Instagram attend ces valeurs séparées par des VIRGULES, pas par des espaces
#: (c'est là que diffère le plus visiblement ce dialogue d'un OAuth2 ordinaire).
SCOPES = ("instagram_business_basic", "instagram_business_manage_insights")

#: Borne de chaque appel HTTP sortant, posée à l'appel.
HTTP_TIMEOUT = 30.0

#: Durée de vie d'un jeton long, telle que Meta l'émet.
LONG_LIVED_TTL_DAYS = 60

#: On renouvelle dès qu'il reste MOINS que ça. Volontairement haut (donc
#: renouvellement fréquent) : ce jeton ne se renouvelle que TANT QU'IL VIT — il
#: n'y a pas de `refresh_token` qui survivrait à son expiration. Un seuil serré
#: ferait dépendre la connexion du hasard d'un usage dans les derniers jours ;
#: un appel de plus sur un usage espacé est le prix de sa survie.
RENEW_WHEN_REMAINING_DAYS = 53

#: Meta refuse de renouveler un jeton de moins de 24 h. Le seuil ci-dessus ne
#: peut pas y conduire tant que Meta émet bien 60 jours ; cette borne garde le
#: cas où il en émettrait moins, où renouveler tout de suite ferait un refus en
#: boucle au lieu d'une connexion qui marche.
MIN_TOKEN_AGE_HOURS = 24


@dataclass(frozen=True)
class InstagramApp:
    """L'application Meta au nom de laquelle on demande le consentement.

    Fournie par celui qui déploie le connecteur, sans défaut. `app_secret` est un
    VRAI secret (il signe l'échange du code et le passage en jeton long) : il ne
    doit apparaître dans aucun message d'erreur ni journal — c'est pourquoi ce
    module construit lui-même ses erreurs plutôt que de laisser remonter celles
    de la couche HTTP, qui portent l'URL appelée.
    """

    app_id: str
    app_secret: str

    def __post_init__(self) -> None:
        """Un champ vide LÈVE ici, pas à la première requête.

        Une chaîne vide construit un objet parfaitement valide et produit, plus
        tard et ailleurs, un refus de Meta qu'on lit alors comme « l'utilisatrice
        n'a pas autorisé » — c'est-à-dire qu'on accuse la personne d'une erreur de
        configuration de l'exploitant."""
        vides = [f.name for f in fields(self) if not str(getattr(self, f.name)).strip()]
        if vides:
            raise ValueError(
                f"InstagramApp : {', '.join(vides)} manque(nt). Ces valeurs se posent "
                f"par celui qui déploie le connecteur — il n'y a pas de défaut, et il "
                f"n'y en aura pas.")
