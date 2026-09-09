# `oto.tools.planity` — l'agenda et la caisse d'un salon Planity

Client **asynchrone** et **en lecture seule** d'un compte Planity pro. Aucune écriture
n'est exposée : pas de création, de modification ni d'annulation de rendez-vous.

Le client se connecte avec l'email et le mot de passe du compte. Il n'y a pas de
clé d'API à obtenir, et il n'y en aura pas.

## Installer

```bash
pip install 'oto-core[planity]'
```

L'extra apporte `httpx` et `websockets`. Sans lui, l'import du paquet lève une erreur
qui le dit — c'est le seul client asynchrone de la lib, et les deux dépendances ne
servent qu'à lui.

## S'en servir

```python
from oto.tools.planity import PlanityClient, PlanityEndpoints, resolve_range

coordonnees = PlanityEndpoints(
    firebase_api_key=...,   # les trois coordonnées de l'application Planity,
    firebase_app_id=...,    # fournies par celui qui déploie le connecteur
    rest_api=...,           # (racine, sans barre oblique finale)
)

async with PlanityClient("moi@exemple.fr", "mot-de-passe", coordonnees) as planity:
    salons = await planity.list_salons()            # l'`id` sert partout ailleurs
    gte, lte = resolve_range(preset="last_month")   # ou date_from/date_to en ISO
    ca = await planity.get_key_indicators(salons[0].id, gte, lte)
```

### Ce avec quoi le client s'authentifie

L'email et le mot de passe du compte Planity, et rien d'autre : le client n'emprunte
aucun autre chemin d'authentification de l'application Planity. **Ce qu'il peut lire
est donc exactement ce que ce compte peut lire** — le périmètre se règle en
choisissant le compte, pas en configurant le client.

### Les coordonnées, et pourquoi elles ne sont pas ici

`PlanityEndpoints` n'a **aucune valeur par défaut**, et n'en aura pas. Les trois
valeurs sont publiques par conception, elles identifient l'application Planity et
n'autorisent rien à elles seules — ce qui autorise, c'est le mot de passe de la
personne.

Les sortir d'ici n'est donc pas un geste de secret, c'en est un de **généricité** : ce
dépôt est public et open source, un client qu'on y publie décrit un protocole et
n'embarque pas les constantes d'une entreprise tierce en dur, comme s'il était son
intégration officielle. Celui qui déploie le connecteur les pose, et répond de ce
qu'il appelle. Un défaut aurait remis la constante ici sous un autre nom.

### Le reste, en une liste

- **Les coordonnées sont obligatoires** — il n'y a pas de mode « sans configuration ».
- **Tout est asynchrone.** Ce n'est pas un choix de style : l'amont l'impose, et il n'y
  a pas d'équivalent synchrone à écrire.
- **Les montants sont en centimes** et **les horodatages en millisecondes** — le client
  les rend tels que Planity les donne ; `ms_to_iso` convertit, la conversion en euros
  appartient à l'appelant.
- **Les fenêtres de dates** passent par `resolve_range(date_from, date_to, preset)` :
  presets `today`, `yesterday`, `this_week`, `last_week`, `this_month`, `last_month`,
  `ytd`, `7d`/`30d`/`90d`… Défaut : les sept derniers jours, fuseau Europe/Paris.
- **Un compte qui s'authentifie sans ouvrir aucun salon** est un compte sans
  établissement rattaché — pas une panne, et rien à réessayer.

Ce fichier dit comment se servir du paquet. Le reste — comment chaque transport
est parlé, et pourquoi — se lit dans le code des modules, à côté de ce qu'il
explique.
