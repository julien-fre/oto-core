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

### Lire BORNÉ

Un nœud Planity porte l'historique entier d'un salon : des milliers de rendez-vous,
des centaines de sessions de caisse, des milliers de mouvements de stock. Une
lecture non bornée n'est pas une lecture lente, c'est une lecture qui ne finit pas.

```python
from oto.tools.planity.firebase_ws import limit_last, range_on

await db.get("un/noeud", limit_last(20))                 # les 20 derniers
await db.get("un/noeud", range_on("createdAt", a, b))    # une fenêtre
```

⚠️ **Une requête bornée exige un tag dans la trame.** Il est émis par `get()`, et
nulle part ailleurs : sans lui, l'amont refuse avec `permission_denied` — un refus
qu'on lit comme un droit manquant alors qu'il manque un champ de protocole.

### Les rendez-vous

```python
rdv = await planity.list_appointments(salon_id, "2026-09-01", "2026-09-07")
un = await planity.get_appointment(salon_id, vevent_id)          # ou + employee_id
rec = await planity.list_recurring_appointments(salon_id)
```

Trois choses en décident, et chacune échoue en rendant « rien » plutôt qu'une erreur :

- la fenêtre est en **jours** (`AAAA-MM-JJ`), pas en horodatage : l'amont stocke
  l'heure MURALE du salon, sans décalage, et convertir en millisecondes en perd ou
  en gagne une selon la saison ;
- un rendez-vous est rangé sous l'**enfant d'agenda** (la collaboratrice), pas sous
  l'agenda — `list_appointments` balaie donc tous les enfants du salon, ou celui
  qu'on nomme ;
- un rendez-vous **annulé** n'a pas de statut, il a une date de suppression :
  `cancelled=True`. Il est rendu comme les autres — le filtrer d'office cacherait
  les annulations à qui les cherche.

Les **récurrents** vivent dans un autre nœud et n'apparaissent dans AUCUNE lecture
par jour : un agenda qui n'a que des récurrences se lit comme un agenda vide.

⚠️ **Un rendez-vous et un ticket portent les coordonnées de la cliente** (nom,
téléphone, email ; un ticket y ajoute l'adresse). Le client rend ce que l'amont donne — c'est
une bibliothèque. Ce qu'on en expose se décide au-dessus, et s'y réduit à
l'identifiant.

### Le prix d'une prestation, et le stock d'un produit

Une prestation n'a pas de prix simple : `services.prix()` rend un `kind` — ferme,
fourchette, sur devis, ou **absent**. Un `0` à la place dirait « offerte », et un
zéro ne lève jamais.

Un produit n'a pas non plus un stock simple : `stock.produit()` rend la liste des
**lots d'achat**, chacun avec son prix d'achat. Ses seuils (`stock_threshold`,
`stock_ceiling`) valent `None` quand le salon ne s'en sert pas — `None` n'est pas
`0`, et confondre les deux fait commander tout, tout le temps.


Ce fichier dit comment se servir du paquet. Le reste — comment chaque transport
est parlé, et pourquoi — se lit dans le code des modules, à côté de ce qu'il
explique.
