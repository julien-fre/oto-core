# Concevoir un connecteur

Statut : proposé. Dernière révision : 03/11/2026.

## Résumé

Concevoir un connecteur partagé suit sept étapes, toujours dans le même ordre : qualifier le service, choisir le périmètre, décrire, écrire du code seulement si la description ne suffit pas, prouver, préparer ce que verra l'écran, publier. Chaque étape a sa sortie, et la suivante ne commence pas sans elle. La qualification tient en une fiche d'une page, rangée dans l'en-tête du fichier de description ; c'est elle qui décide du reste. Ce document est le point d'entrée d'un agent à qui l'on demande « ajoute le connecteur X » ; les règles du format vivent dans [Format de description](format-de-description.md), celles de la génération dans [La fabrique](fabrique.md).

## Contexte

- Les règles existent, mais sont réparties entre les documents du format, la fabrique, les conventions du dépôt et les commentaires d'en-tête de chaque description : chaque session refaisait le chemin, et la première question posée sur un service était souvent la mauvaise (« quels endpoints ? » avant « qui détient la clé ? »).
- Les retours des utilisateurs d'oto 1 sur les connecteurs (plusieurs centaines de signaux sur 90 jours) visent peu la conception : ils disent surtout une capacité manquante, un branchement qui échoue, une clé morte ou des crédits épuisés sans alerte, une clé en lecture seule que rien ne signale. La moitié de ces problèmes se décide à la qualification et à l'écran, pas dans le code.
- Le but posé : qu'un agent, à qui l'on demande un connecteur, produise une description juste et que le connecteur existe, sans code, dans la plupart des cas.

## Objectifs et non-objectifs

- Un ordre unique, et une sortie vérifiable à chaque étape.
- Une fiche de qualification que l'administrateur d'un client, l'écran et l'agent peuvent relire.
- Savoir s'arrêter : un périmètre de gestes utiles, pas toute l'API.
- Hors objectif : répéter les règles du format ou de la fabrique ; ce document y renvoie.
- Hors objectif : le contrat côté hôte (comptes, partage, coffre), décrit dans oto-core : docs/conception/connecteurs-et-comptes.md.

## Conception

### 1. Qualifier le service

Avant toute ligne de YAML, lire la documentation de l'API et remplir la fiche. Elle va, en anglais, dans le commentaire d'en-tête de `connectors/<nom>/connector.yaml`.

| Question | Ce qu'elle décide |
|---|---|
| **Qui détient l'accès ?** Une personne (sa connexion), l'organisation (une clé de service), l'hôte (une clé pour toutes ses organisations), personne (données publiques). | `auth`, `credential` et `holder`, `modes` ; le type de la carte du parc. |
| **Comment s'authentifie-t-on ?** Clé en en-tête, jeton porteur, identifiant et mot de passe, OAuth entre machines, consentement d'une personne. | `auth.kind`. Un mode absent du format (signature calculée, cookie de session, navigateur) mène à l'étape 4. |
| **Que permet une clé ?** Droits fixes, droits choisis à la création (lecture seule possible), droits OAuth. L'API sait-elle les dire ? | Une sonde qui les lit, des niveaux d'accès (`access_levels`), ou au moins la phrase « une clé en lecture seule refuse X ». |
| **Que coûte un appel ?** Gratuit, à la requête, aux crédits, au résultat. Un solde est-il lisible gratuitement ? | `cost` par fonction, `probe.balance`. |
| **Le service engage-t-il ?** Envoi, paiement, signature, suppression, validation irréversible. | La classe `sensitive` et son récapitulatif ; un service qui engage beaucoup est un service « métier ». |
| **Que rend-il qu'un agent ne doit pas voir ?** Secret de webhook, adresse signée, photo, enregistrement, jeton. | `output.strip`, et le même retrait dans le client Python. |
| **Quelles limites ?** Rythme, quotas, délais longs, travaux en deux temps. | `rate_limit`, `timeout_s`, `async`, `background`. |
| **Une adresse propre à chaque client ?** Sous-domaine, région, serveur. | `settings` et gabarit de `base_url`. |
| **Qui est le propriétaire de l'accès ?** Un produit vendu à des entreprises, ou le back-office propre d'un client. | Le second n'entre jamais dans ce dépôt public (`docs/conventions.md`). |

Sortie : la fiche, relue. Une réponse inconnue s'écrit « inconnu », jamais devinée.

### 2. Choisir le périmètre

- Partir des gestes qu'un agent fera, pas de la liste des endpoints : lire et chercher les objets du métier, créer et modifier ce qu'un utilisateur crée à la main, les actions qui engagent derrière une confirmation.
- Classer chaque fonction : `read`, `write` (une écriture, ou un appel qui dépense des crédits), `sensitive` (irréversible ou qui engage un tiers).
- Nommer ce qu'on laisse de côté, et pourquoi, dans l'en-tête : un manque nommé se rattrape, un manque tu se découvre en production.
- Si un client Python existe (oto 1), la description suit ses noms de fonctions et d'arguments.

Sortie : la liste des fonctions et leur classe, et la liste de ce qui n'est pas décrit.

### 3. Décrire

Écrire `connectors/<nom>/connector.yaml` selon [Format de description](format-de-description.md), puis lancer `python -m fabrique`. La relecture passe la liste suivante :

- chaque description de fonction dit à l'agent ce qu'il obtient, ce que ça coûte et quand ne pas l'appeler (c'est le texte servi, en anglais, 1000 caractères au plus) ;
- au moins un exemple par fonction ;
- les arguments qui nomment une personne portent `personal: true` ;
- la table d'erreurs couvre la clé refusée (`marks_account: credential_rejected`) et les crédits épuisés (`quota_exhausted`), avec un message qui dit quoi faire ;
- une sonde dès qu'une lecture gratuite sans argument existe, avec le solde quand il est lisible ;
- la pagination, et le plafond d'éléments quand le coût en dépend ;
- les retraits de sortie ;
- la version du connecteur monte (semver) à chaque commit qui change sa description ou son client.

Sortie : `python -m fabrique --check` vert ; la fonction que la fabrique ne génère pas est listée avec sa raison.

### 4. Écrire du code, seulement si la description ne suffit pas

Le format décrit une requête et sa réponse. Il ne calcule pas : composer un message MIME, signer une requête, construire une requête GraphQL selon les filtres, enchaîner plusieurs services, lire un PDF. Trois sorties possibles, dans cet ordre de préférence :

1. **La forme revient** chez plusieurs services : elle entre au format (une règle de plus, des cas partagés, et le moteur d'oto-core qui l'exécute), dans un lot à part.
2. **Le geste est propre à un service** : il reste au client Python, et l'hôte d'oto 2 l'écrit au contrat `defineFunction` s'il le sert.
3. **Ce n'est pas un connecteur** (un script qui enchaîne, un traitement) : il sort du sujet.

### 5. Prouver

- Les tests de la description (`tests/test_connector_descriptions.py`) et, si un client Python existe, le test de concordance `tests/test_<nom>_description.py` : la description envoie exactement la requête du client, argument absent compris.
- Les tests touchés seulement, par `tests-poste` ; la suite complète est le rôle de la CI.
- Un vrai appel, avec une vraie clé, avant de dire le connecteur servi : la sonde, puis une lecture. Un banc vert ne prouve pas qu'un service répond comme sa documentation.

### 6. Préparer ce que verra l'écran

Le connecteur sera branché par une personne qui ne lit pas le YAML. La fiche de l'étape 1 donne à l'écran : la phrase de catalogue (ce que l'agent saura faire), où créer la clé chez l'éditeur, les droits à donner, les champs à saisir et leur aide, et les pièges pour l'administrateur (« ces droits ouvrent toutes les boîtes du tenant », « une clé gratuite plafonne à 25 recherches par mois »).

### 7. Publier

Commit de la description, du client et de la sortie générée ; version de la lib montée et tag posé à la main avec l'accord du responsable produit ([docs/release.md](../release.md)) ; puis l'hôte déclare le connecteur et monte sa version. La [carte du parc](../carte-du-parc.md) se régénère avec la fabrique.

## Décisions et alternatives écartées

- **Qualifier avant de décrire** : commencer par les endpoints menait à des descriptions justes et inutilisables (clé de service décrite comme personnelle, coût oublié, lecture seule non dite). Écarté : une checklist unique en fin de travail.
- **La fiche vit dans l'en-tête de la description**, à côté de ce qu'elle justifie. Écarté : un document par connecteur dans `docs/`, qui divergerait du fichier.
- **Un périmètre de gestes**, pas l'API entière : plus de fonctions, c'est plus de texte servi à l'agent et plus de surface à tenir. Écarté : décrire tout l'API d'office.
- **Le code n'est pas un échec** : forcer dans le format un geste qui calcule le rend illisible. Écarté : un langage d'expressions dans le YAML.

## Sécurité et confidentialité

- Le secret est toujours fourni par le consommateur ; ni la description ni le client n'en lisent un.
- Aucun secret ni adresse qui s'ouvre sans connexion ne revient à l'agent : retrait dans la description et dans le client.
- Dépôt public : la fiche ne nomme aucun client ni partenaire, et ne raconte ni la reconstitution d'une API ni un diagnostic sur l'éditeur (`docs/conventions.md`).

## Écart avec le code

- Le vrai appel de l'étape 5 n'a pas d'outillage commun : chaque session le fait à sa façon, ou pas.
- La fiche de l'étape 1 est un commentaire libre : ni le schéma ni la fabrique ne la lisent, et l'écran de l'hôte ne peut pas encore s'en servir (étape 6).
- La carte du parc ne sait pas quels connecteurs un hôte sert, ni lesquels ont été testés par un vrai appel.

## Questions ouvertes

- Faire de l'étape 6 une rubrique structurée de la description (où créer la clé, droits, pièges), lue par la fabrique et servie à l'écran de l'hôte : proposition en cours, avec le responsable de l'écran.
- Un compte de test par service, pour rendre l'étape 5 reproductible.

## Historique

- 2026-11-03 : création, sept étapes et fiche de qualification — décidé par le responsable produit (source : demande de rationalisation des connecteurs).
