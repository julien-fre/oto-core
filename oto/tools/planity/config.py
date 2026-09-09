"""Constantes publiques de Planity — extraites du bundle JS de `pro.planity.com`.

Aucun secret ici, et **aucune variable d'environnement** : les identifiants d'un
compte Planity (email + mot de passe) arrivent par argument de `PlanityClient`,
jamais par l'environnement du processus. Ces trois valeurs sont les mêmes pour
tout le monde — ce sont les coordonnées publiques du projet Firebase de Planity
et de ses lambdas REST, telles que le navigateur les envoie.

Deux autres constantes lues dans le bundle ne sont PAS reprises, parce que rien
ici ne les consomme : l'identifiant de projet Firebase (`planity-production`,
déjà porté par les noms d'hôtes dans `firebase_ws`) et l'URL de résolution de
shard (le shard d'un salon se lit sur `businesses/<bid>/db`, cf. `README.md`).
"""
from __future__ import annotations

#: Clé d'API Firebase Auth du projet Planity (publique — elle voyage dans l'URL
#: des appels `identitytoolkit`).
FIREBASE_API_KEY = "AIzaSyDrSE1PzMwLKyhEvh2x8eV7s1NYwKGRC5Q"

#: App ID Firebase, envoyé en `p=` dans la poignée de main WebSocket du RTDB.
FIREBASE_APP_ID = "1:1025269755978:android:26e77f72a3cbd599"

#: Les lambdas REST de Planity (statistiques, tickets, credentials Algolia).
PLANITY_REST_API = "https://product.api.euwest1.prod.planityapp.com"

#: Borne de CHAQUE appel HTTP sortant, posée à l'appel et pas seulement à la
#: construction du client : un client partagé peut être passé par l'appelant, et
#: un appel nu attend alors sans fin. Cf. `tests/test_http_timeouts.py`.
HTTP_TIMEOUT = 30.0

#: La recherche de clientes est interactive : elle a droit à moins d'attente que
#: les lambdas de statistiques, qui agrègent des mois de tickets.
SEARCH_TIMEOUT = 15.0
