"""Réseau & outreach : relations et invitations.

Extrait de `client.py` (découpage par domaine, surface publique figée) :
les corps sont inchangés. Ce mixin n'est jamais instancié seul — il est
composé dans `UnipileClient`, qui fournit le transport (`_request`,
`_acct`, `_norm`, `_by_shape`, `session`).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional
from urllib.parse import quote

from ..const import cursor_with_limit
from ..errors import UnipileError


# Curseur SYNTHÉTIQUE des invitations : `off:<offset>:<empreinte de la page>`.
#
# `relation-requests` est paginé par OFFSET côté Unipile, pas par curseur — il
# ne rend donc JAMAIS de `next_cursor`. Pour garder au tool son contrat
# (« rappelle-moi avec le cursor rendu »), on FABRIQUE ce jeton et on le
# redécode à l'entrée : il n'est JAMAIS transmis en amont. Le préfixe le rend
# lisible en log et empêche toute collision si Unipile finissait par en rendre
# un vrai (auquel cas l'amont gagne, cf. `list_invitations`).
#
# Le jeton porte AUSSI l'empreinte de la page qui l'a produit, et c'est là
# l'arrêt mécanique : qu'`offset` pagine réellement cet endpoint n'a jamais été
# vérifié contre le service réel. Si l'hypothèse est fausse, l'amont ignore
# `offset` et ressert la même page indéfiniment — sans empreinte, la boucle
# appelante ne s'arrête JAMAIS (simulé : 8 pages, 400 lignes rendues pour 50
# distinctes). En comparant la page rendue à celle du tour précédent, on coupe
# au 2e appel. La forme `off:<n>` sans empreinte reste décodée : un curseur
# rendu par une version antérieure ne casse pas en vol.
_INV_CURSOR = "off:"

# Plafond OBSERVÉ (2026-09-10) de `limit` sur relation-requests : 100 passe,
# 101 et 200 rendent `Unipile 400: Invalid querystring` — un message qui ne
# nomme ni le param fautif ni la borne. Unipile ne le documente pas (l'OpenAPI
# v2 dit `default: 20, minimum: 1`, sans maximum : « depends on the
# provider »). On trie donc ICI, pour rendre une erreur qui se lit.
_INV_LIMIT_MAX = 100


def _invitations_page_print(page: list) -> str:
    """Empreinte d'une page d'invitations — ce qui la distingue de la suivante.

    Sur les `id` quand les items en portent (ce que rend l'amont), sur l'item
    entier sinon. Deux pages « identiques » au sens qui compte ici sont deux
    pages qui reservent les MÊMES invitations — pas deux pages de même
    taille."""
    seed = json.dumps(
        [it.get("id", it) if isinstance(it, dict) else it for it in page],
        sort_keys=True, default=str, ensure_ascii=False,
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _invitations_cursor(cursor: Optional[str]) -> tuple[int, Optional[str]]:
    """Décode un curseur d'invitations FABRIQUÉ par nous → `(offset, empreinte
    de la page qui l'a produit)`. L'empreinte est `None` si le curseur n'en
    porte pas (forme antérieure `off:<n>`, toujours acceptée).

    Tout autre curseur est refusé ICI plutôt que transmis : passé en amont il
    déclenchait le 400 « Unexpected parameters: type » (cf.
    `list_invitations`), illisible pour l'appelant."""
    if not cursor:
        return 0, None
    if cursor.startswith(_INV_CURSOR):
        head, _, tail = cursor[len(_INV_CURSOR):].partition(":")
        if head.isdigit():
            return int(head), (tail or None)
    raise UnipileError(
        "list_invitations : curseur invalide. Ne repasse QUE le `cursor` rendu "
        "tel quel par l'appel précédent ; pour repartir du début du listing, "
        "n'en passe aucun. Un curseur venu d'un autre appel — ou écrit à la "
        "main — est refusé ici, avant tout appel en amont."
    )


class _NetworkMixin:
    """Réseau & outreach : relations et invitations."""

    def list_relations(self, cursor: Optional[str] = None,
                       limit: Optional[int] = None) -> dict:
        params: dict[str, Any] = {}
        if cursor:
            # Le limit de l'appel prime sur celui figé dans le cursor (#179).
            params["cursor"] = cursor_with_limit(cursor, limit) if limit else cursor
        if limit:
            params["limit"] = limit
        return self._norm(self._request(
            "GET", self._acct("/users/me/relations"), params=params
        ))

    def list_invitations(self, direction: str = "received",
                         limit: Optional[int] = None,
                         cursor: Optional[str] = None,
                         offset: Optional[int] = None) -> dict:
        """Invitations — v2 : `GET /v2/{account}/users/me/relation-requests`,
        `type=sent|received` (param REQUIS côté Unipile).

        ⚠️ Cet endpoint est paginé par `offset`, PAS par curseur. Unipile :
        « Pagination for this endpoint works with the `offset` parameter. » Il
        ne rend donc jamais de `next_cursor`, et il REFUSE tout param autre que
        `limit`/`meta_only` à côté d'un `cursor` :

            Unipile 400: When cursor is provided, only "limit" and "meta_only"
            are allowed alongside it. Unexpected parameters: type.

        `type` étant OBLIGATOIRE, envoyer un `cursor` était une impasse : la
        page 1 passait, toute page suivante 400ait — la pagination des
        invitations était morte au-delà du premier écran, sans que rien ne le
        signale côté schéma (le tool annonçait « Paginé »). On pagine donc par
        `offset` et on FABRIQUE le curseur rendu (cf. `_invitations_cursor`)
        pour garder au tool son contrat.

        Avance de `limit` par page — contrat Unipile : « increment the offset
        by the limit » — et s'arrête quand `data` est VIDE, pas sur une page
        courte : le provider peut filtrer des items DANS la fenêtre, et
        avancer de `len(data)` re-servirait alors les mêmes. Pour un export
        exhaustif, déduplique quand même par `id`.

        ⚠️ ARRÊT MÉCANIQUE. Qu'`offset` pagine réellement cet endpoint n'a
        jamais été vérifié contre le service réel. Si l'hypothèse est fausse,
        l'amont ignore `offset` et ressert la même page à chaque tour : la
        boucle appelante ne s'arrêterait jamais. Le curseur rendu porte donc
        l'empreinte de la page qui l'a produit, et AUCUN curseur n'est fabriqué
        quand la page rendue est identique à celle du tour précédent — la
        boucle s'arrête alors au 2e appel, et `pagination_note` dit pourquoi.
        Le critère est la page IDENTIQUE, pas la page vide : c'est le vrai mode
        d'échec ici, une page vide n'arrive justement jamais dans ce cas."""
        seen = None
        if offset is None:
            offset, seen = _invitations_cursor(cursor)
        if limit is not None and not 1 <= limit <= _INV_LIMIT_MAX:
            raise UnipileError(
                f"list_invitations : limit doit être entre 1 et "
                f"{_INV_LIMIT_MAX} (reçu {limit}). Au-delà, Unipile rend un "
                "« Invalid querystring » qui ne nomme pas la borne."
            )
        params: dict[str, Any] = {
            "type": "sent" if direction == "sent" else "received"
        }
        if limit:
            params["limit"] = limit
        if offset:
            params["offset"] = offset
        out = self._norm(self._request(
            "GET", self._acct("/users/me/relation-requests"), params=params
        ))
        # Curseur fabriqué UNIQUEMENT si l'amont n'en rend pas (aujourd'hui il
        # n'en rend jamais) : le jour où Unipile en rend un vrai, il gagne.
        # Page vide = fin de liste → pas de curseur, l'appelant s'arrête.
        if isinstance(out, dict) and not out.get("next_cursor"):
            page = out.get("data")
            if isinstance(page, list) and page:
                mark = _invitations_page_print(page)
                if mark == seen:
                    # L'amont vient de resservir la page précédente à
                    # l'identique : il n'avance pas — `offset` ne pagine pas cet
                    # endpoint. On ne fabrique AUCUN curseur, sinon la boucle
                    # appelante tourne à vide sans jamais rencontrer de fin.
                    out["pagination_note"] = (
                        "Pagination arrêtée : l'amont a resservi la page "
                        "précédente à l'identique, il n'avance pas sur cet "
                        "endpoint. Les éléments ci-dessus sont les mêmes que "
                        "ceux de la page précédente ; il n'y a pas de suite à "
                        "demander."
                    )
                else:
                    nxt = (f"{_INV_CURSOR}{offset + (limit or len(page))}"
                           f":{mark}")
                    out["next_cursor"] = nxt
                    out["cursor"] = nxt
        return out

    def send_invitation(self, provider_id: str,
                        message: Optional[str] = None) -> dict:
        """v2 : `POST /users/me/relation-requests`, corps `{user_id, message}`."""
        body: dict[str, Any] = {"user_id": provider_id}
        if message:
            body["message"] = message
        return self._request(
            "POST", self._acct("/users/me/relation-requests"), json=body
        )

    def handle_invitation(
        self, invitation_id: str, shared_secret: str, action: str = "accept"
    ) -> dict:
        """Accepte/refuse une invitation REÇUE. v2 : `request_id` suffit (plus de
        `shared_secret`, gardé dans la signature pour compat appelant). accept →
        `/accept` ; decline → `/cancel`."""
        if action not in ("accept", "decline"):
            raise UnipileError("handle_invitation : action = 'accept' ou 'decline'.")
        verb = "accept" if action == "accept" else "cancel"
        return self._request(
            "POST",
            self._acct(
                f"/users/me/relation-requests/{quote(invitation_id, safe='')}/{verb}"
            ),
        )

    def cancel_invitation(self, invitation_id: str) -> dict:
        """Annule une invitation ENVOYÉE. v2 : `/relation-requests/{id}/cancel`."""
        return self._request(
            "POST",
            self._acct(
                f"/users/me/relation-requests/{quote(invitation_id, safe='')}/cancel"
            ),
        )

