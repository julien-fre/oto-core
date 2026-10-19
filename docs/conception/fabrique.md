# La fabrique

- **Statut** : proposé
- **Dernière révision** : 2026-10-19

## Résumé

La fabrique lit les [fichiers de description](format-de-description.md) et génère, pour chaque connecteur partagé, des définitions TypeScript structurelles et typées, que le paquet d'oto 2 adapte à son contrat de fonction et exécute ; puis, dans un second temps, un client Python dans la lib. Elle vit dans ce dépôt, à côté des descriptions, écrite en Python (`fabrique/`) ; sa sortie TypeScript est commitée sous `ts/`. L'application hôte (oto-saas) en dépend et déclare au paquet d'oto 2 les connecteurs qu'elle choisit ; le paquet, moteur générique, n'en contient aucun. La sortie TypeScript existe ; la sortie Python ne porte encore que des données, le coût et le travail asynchrone de chaque fonction (`oto/connectors/declared.py`).

## Contexte

- Oto 2 connaît deux sortes de connecteurs. Un connecteur propre à un hôte s'écrit dans l'hôte, à la main, au contrat de fonction du paquet. Un connecteur partagé a sa source ici et passe par la fabrique. Le contrat côté hôte (fonction du catalogue, comptes, secret fourni à l'appel, coffre) est décrit dans oto-pkg : docs/conception/connecteurs-et-comptes.md ; ce document ne le répète pas.
- Le langage servi dépend du consommateur, pas du connecteur : Python pour tout consommateur écrit en Python, TypeScript pour le paquet d'oto 2.
- Côté paquet, au relevé du 29/09 : les fonctions s'inscrivent par une liste statique d'imports, la source TypeScript est transpilée par l'hôte, les dépendances sont épinglées. Pour une fonction de connecteur, le paquet reçoit le JSON Schema d'entrée et le valide lui-même, avec un validateur JSON Schema standard.
- Côté lib : depuis la version 1.148.0, aucun client ne lit de secret ; il le reçoit en paramètre et l'exige par `require`, qui lève `MissingCredential`.
- Le backend d'oto 1 consomme la lib en Python et déclare à la main, pour chaque connecteur, ses outils (nom, description, schéma) et une logique propre (avertissements, bornes, messages d'erreur) : une deuxième version de ce que dit la description.

## Objectifs et non-objectifs

- Une description, deux sorties qui servent le même contrat, prouvé par des tests.
- Une sortie TypeScript qu'un hôte d'oto 2 inscrit sans écrire de code.
- Le doublage à la main reste l'exception : un connecteur hors format, ou une entrée `handwritten`.
- Une description invalide ne génère rien.
- Une seule version d'un connecteur pour oto 1 et oto 2 : le backend d'oto 1 bascule connecteur par connecteur sur la description (voir « Oto 1, connecteur par connecteur »).
- Hors objectif : basculer d'un coup les outils d'oto 1 ; un connecteur dont oto 2 n'a pas l'usage peut s'éteindre avec oto 1 sans jamais être décrit.
- Hors objectif : convertir les connecteurs existants ([format](format-de-description.md)).
- Hors objectif : le contrat côté hôte, l'activation, la résolution du compte et le coffre (oto-pkg : docs/conception/connecteurs-et-comptes.md).

## Conception

### Ce qu'elle lit et vérifie

Chaque `connectors/<nom>/connector.yaml`, validé contre `connectors/connector.schema.json`, puis les règles que le schéma JSON ne sait pas dire :
1. chaque argument d'`input` va à un seul endroit de `call` (chemin, query, corps ou en-tête) ;
2. chaque secret que nomme `auth` est un champ de `credential` ;
3. un nom côté API reçoit une seule valeur : une constante ne reprend pas le nom d'un argument de la même place, un en-tête n'est posé qu'une fois (authentification, en-têtes du connecteur, de la fonction, à la casse près), une clé en query n'est le nom d'aucun paramètre de query, et `encode` ne nomme qu'un argument placé en query, en corps ou en en-tête ;
4. un contrôle (`checks`, `expect`) nomme un refus de sa fonction, et `equal_sums` une liste dont les éléments déclarent les deux champs ;
5. la sonde, et l'identité d'un `oauth2_user` lue par une fonction, nomment une fonction de lecture, appelée par `call`, sans argument requis ; la fonction d'une sonde qui lit un solde (`balance`) ne déclare pas de coût ; l'identité lue à une adresse complète déclare ses droits, que `scopes` demande dans un connecteur sans niveaux ;
6. un nom n'est déclaré qu'une fois parmi `credential`, `settings` et `from_token` ; le défaut d'une liste fermée en est une valeur ; un gabarit ne cite que des réglages déclarés (et `base_url`, des valeurs de `from_token` et l'identité d'un compte rattaché, règle 8), une adresse libre en tête seulement, un autre réglage après `https://` seulement ; `base_urls` et `token_urls` portent sur une liste fermée et donnent une adresse à chacune de ses valeurs ; tout réglage est cité ;
7. les [niveaux d'accès](niveaux-d-acces.md) : `scope_implies` est clos (une clé liste aussi ce qu'impliquent les droits qu'elle implique) et chacune de ses clés est un droit d'un niveau ; `full` couvre chaque droit d'un niveau restreint et chaque droit exigé par une fonction ; l'identité d'un consentement (par les droits de sa fonction, ou par les siens quand elle se lit à une adresse) et la sonde sont servies à chaque niveau ;
8. l'identité d'un compte rattaché (`account_identity`) : son nom n'est ni un champ de `credential`, ni un réglage, ni une valeur de `from_token` ; elle est citée par `base_url`, ou par chaque adresse de `base_urls`, après l'hôte seulement (jamais à la place du schéma ou de l'hôte), et par aucune autre adresse ; aucun argument d'entrée, aucun nom côté API de `call` (chemin, query, corps, en-tête), aucune constante ni aucun en-tête constant ne porte son nom. Un connecteur dont tous les champs sont `holder: host` reste valide ;
9. `act` suit la classe : jamais `false` sur une fonction `sensitive`, jamais `true` sur une fonction `read` ;
10. le signal de refus du service ([format](format-de-description.md), « Signal de refus du service ») : `body` et `marks_account` sur un refus exigent un statut pour `when` ; un statut 2xx exige une condition sur le corps ; un 403 sans condition ne marque pas `credential_rejected`, ni un 429 sans condition `quota_exhausted` ; une entrée qui marque n'est pas rejouable ; dans une table, une entrée à condition ne suit pas une entrée sans condition qui partage un de ses statuts ;
11. le délai propre à une fonction (`timeout_s`) n'est jamais égal à celui du connecteur, déclaré ou de 30 s par défaut : il ne dirait rien ; plus court ou plus long, il est permis ;
12. le coût d'un appel ([format](format-de-description.md), « Coût d'un appel ») : `items` et `times` (`per: item`) nomment deux arguments distincts de l'entrée, des listes requises d'au moins un élément ; une fonction paginée ne déclare ni `per: item` ni `settle` ;
13. le travail asynchrone ([format](format-de-description.md), « Travail asynchrone ») : `collect` nomme une autre lecture du connecteur, appelée par `call`, non asynchrone, dont `job_id.to` est le seul argument requis ; `within_s`, déclaré, dépasse le délai de la soumission (le schéma exige `within_s` ou `no_deadline` quand le coût se règle, jamais les deux) ; quand le coût se règle, la relève n'est ni paginée ni réglée de son côté ;
14. les fichiers ([format](format-de-description.md), « Fichiers ») : `call.files` n'est porté que par une méthode qui envoie un corps (`POST`, `PUT`, `PATCH`), sur une fonction non paginée ; chaque argument fichier est un texte (`type: string`), qu'`encode` ne nomme pas ; un nom de partie fichier n'est ni une entrée ni une constante de `body`. L'argument fichier est placé comme un autre (règle 1) ;
15. la donnée personnelle ([format](format-de-description.md), « Donnée personnelle ») : `personal` marque une propriété de l'entrée, à toute profondeur, et vaut `true` ; ni sur la racine de l'entrée, ni dans `output.schema`. Seuls les mots de schéma sont lus : une propriété qui s'appellerait `personal` n'est pas une marque ;
16. le poids d'une valeur ([format](format-de-description.md), « Coût d'un appel ») : `cost.weights.field` nomme un champ de chaque élément de `items`, requis, une liste d'au moins une valeur sans doublon (`uniqueItems: true`), dont les valeurs admises (`items.enum`) sont exactement les clés de `weights.values` : une valeur sans poids est refusée avant l'appel, un poids ne vaut que pour une valeur admise.

Le schéma refuse lui-même un `credential` en `oauth2_user` : les jetons d'un consentement ne sont pas des champs. Il exige aussi les `scopes` de chaque fonction d'un connecteur à niveaux, et les refuse ailleurs.

Une règle violée fait refuser le fichier, et rien n'est généré.

### Ce qu'elle génère

| Sortie | Contenu |
|---|---|
| Python, dans la lib | Aujourd'hui, des données : `oto/connectors/declared.py`, par connecteur et par fonction qui en déclare, le `cost` et l'`async` contrôlés, dans les noms de la description (et le `max_pages` d'une lecture paginée qui coûte) ; les fonctions pures écrites à la main de `oto/connectors/cost.py` (`worst_case`, `settled_quantity`, `collection_of`) les lisent avec la sémantique d'oto-core (`costOf`, `settledQuantity`, `collectionOf`). Plus tard : une méthode par fonction sur le client du connecteur, au-dessus d'un runtime commun : transport, authentification par `auth.kind`, encodage des listes (`query_arrays`), pagination. |
| TypeScript, sous `ts/src/` | Un module par connecteur : sa définition (authentification telle que décrite, clés en camelCase, `baseUrl` ou `baseUrls`, champs du credential avec leur `holder`, toujours dit, `account` par défaut, identité d'un compte rattaché `accountIdentity`, réglages, table d'erreurs avec, quand elle les déclare, la condition sur le corps `body` et la marque du compte `marksAccount`, délai en millisecondes, exposition, en-têtes constants, rythme maximal, sonde avec, quand elle le déclare, son solde `balance`) et une définition par fonction (nom qualifié `<connecteur>.<fonction>`, classe, `act` résolu, déclaré ou déduit de la classe, droits exigés dans un connecteur à niveaux, description, schéma d'entrée en JSON Schema, exemples avec leur titre, refus en table `code`/`when`/`message` (et `body`, `marksAccount`), contrôles avant l'appel et sur la réponse, spécification de requête avec constantes, encodages et, quand elle les déclare, parties fichier `files`, délai propre en millisecondes `timeoutMs` quand elle le déclare, travail asynchrone `async` quand elle le déclare (relève qualifiée `collect`, `jobId`, délai `withinMs`), pagination, sortie, coût (`per`, et `items`, `times`, `unit`, `settle` quand elle les déclare), résumé de confirmation) ; un index qui les liste. Le contrat de ces définitions est un module écrit à la main, `ts/src/types.ts`. Et les cas communs du coût, `ts/src/cost-cases.ts` (« Les cas communs du coût »). |
| Les deux | La table des erreurs et les `refusals`, en table ; les tests de contrat. |

- La sortie TypeScript ne dépend ni du paquet d'oto 2 ni d'aucune bibliothèque : pas de cycle. Le paquet l'adapte à son contrat (refus en chaînes, exemples sans titre, codes d'erreur à lui) et l'exécute avec son client HTTP, son coffre et son journal.
- La spécification de requête dit la méthode, le chemin et ses `{param}`, et pour `query`, `body` et `headers` le nom côté API de chaque argument ; la sortie ne contient aucun code qui envoie une requête.
- Le schéma d'entrée est le JSON Schema 2020-12 de la description, recopié tel quel une fois les ancres YAML résolues : le schéma servi et le schéma validé sont le même objet. L'hôte le valide avec un validateur standard ; le test de la sortie le fait avec Ajv 2020, `format` restant une annotation comme dans le test des descriptions. La fabrique n'en vérifie qu'une chose, que la racine est un objet strict (`type: object`, `additionalProperties: false`) ; une fonction qui y manque, ou écrite à la main, n'est pas générée : elle est nommée, avec sa raison, en tête du module et à la sortie de la commande.
- La pagination ajoute `all_pages` et `max_pages` au schéma servi ; `max_pages` borne le parcours, que l'hôte mène.
- La sortie décrit, l'hôte exécute : il valide l'entrée contre le schéma ; pose les en-têtes constants du connecteur et de la fonction, puis les constantes de query et de corps ; sérialise en JSON les arguments que nomme `encode` ; envoie le corps quelle que soit la méthode, `DELETE` compris ; tient le rythme maximal par credential ; suit la pagination jusqu'à `next` vide ou `more` faux ; joue les `checks` avant l'appel et les `expect` sur la réponse, en rendant le refus nommé ; appelle la sonde avec `{}`, sans la décompter d'un quota, exige non vides les chemins de `nonEmpty`, et lit le solde au chemin de `balance` : sous `min`, absent ou qui n'est pas un nombre, la sonde n'est pas saine.
- Pour une fonction qui déclare `files`, l'hôte lit chaque fichier en transit sous l'identité de l'appelant (un identifiant inconnu, échu ou d'un autre : le refus d'un fichier inconnu), envoie un corps `multipart/form-data` (les entrées et constantes de `body` en parties texte, chaque fichier en partie à son nom et à son type), et consomme les fichiers après un envoi réussi, jamais après un refus ni un envoi ambigu ; il n'écrit jamais leur contenu dans un résultat ni au journal.
- Pour le compte, l'hôte : propose à la connexion les champs et les réglages (liste fermée, motif) ; résout l'adresse (gabarit ou `baseUrls`) ; garde une adresse libre (`https` seul, hôte qui ne résout jamais vers une adresse interne, à chaque résolution, aucune redirection suivie) et ne substitue une valeur `text` ou `choice` que faite de lettres, chiffres, `-` et `_` ; pose la clé en en-tête ou en query, masquée dans tout journal ; envoie l'identifiant et le secret du client selon `clientAuth` ; prend un champ `holder: "host"` dans sa propre configuration, jamais dans le compte, ne le montre ni ne le fait saisir ; écrit l'identité d'un compte rattaché par un seul service qui la vérifie auprès du tiers et contre `pattern`, jamais par une saisie, et la substitue dans `baseUrl` à l'appel.
- Pour `oauth2_user`, l'hôte mène le consentement avec son application OAuth, ou celle de l'organisation : adresse d'autorisation (scopes joints par des espaces, `authorizeParams`, `state`, PKCE), échange du code en formulaire, lecture de l'identité qui nomme le compte (sa fonction, appelée avec `{}`, ou son adresse complète, en `GET` avec le jeton, sans argument), valeurs de `fromToken` gardées ; il renouvelle selon `refresh`, et sous `rotates` réécrit le refresh token rendu, seulement si le jeton stocké est encore celui qu'il a lu.
- `python -m fabrique` régénère `ts/src/` (cas communs du coût compris) et `oto/connectors/declared.py` ; `python -m fabrique --check` échoue si l'une ou l'autre sortie commitée n'est pas à jour. La sortie Python est un module, pas un JSON en données du paquet : il part dans la roue et l'archive source par la seule règle `oto*` de `packages.find`, sans `package-data` ni `MANIFEST.in` à tenir, et s'importe sans lire de fichier ; la lib ne relit jamais un YAML à l'exécution. On la lance à la main ; la CI vérifie, par `tests/test_fabrique.py`, que la sortie commitée est à jour, et compile et teste `ts/`.
- La projection suit `exposure.mode` : en `per_action`, un outil `<namespace>_<name>` par fonction, schéma tel quel ; en `per_connector`, un outil qui reçoit `action` (l'énumération des noms) et un schéma en `oneOf` des entrées ; en `via_call`, rien n'est exposé et le verbe d'appel lit le registre.
- Tests de contrat : le schéma d'entrée servi est le même des deux côtés ; chaque exemple est joué contre le schéma et contre un serveur simulé.

### Les cas communs du coût

`connectors/_cases/cost.yaml` porte des cas synthétiques (aucun connecteur réel, aucun éditeur) qui prouvent que les fonctions pures du coût rendent la même chose en Python (`oto.connectors.cost`) et dans le paquet d'oto 2 (`costOf`, `settledQuantity`, `collectionOf`). Un cas porte une fonction en forme source (`cost`, `async`, pagination), et sa relève pour un travail asynchrone ; les arguments de l'appel, ses réponses (celles de la relève pour un travail réglé à la relève), la réponse de la soumission ; et ce que rend chaque fonction pure : le pire cas, la quantité réglée avec `from` et `exceeded`, la relève (`within_s` ou `no_deadline`), `null`, ou `error` (un refus, quel que soit son message). Le dossier commence par `_` : il n'est le code d'aucun connecteur (gardes par commit), et la fabrique ne le lit pas comme une description.

- La fabrique (`fabrique/cases.py`) contrôle la forme du fichier, puis assemble le bloc `connector` et les fonctions des cas en une description, contrôlée par le schéma et les seize règles comme toute autre ; un même nom est toujours la même fonction (une ancre YAML la partage entre cas).
- Elle la convertit comme une description : dans la forme de `oto/connectors/declared.py` pour `tests/test_cost_cases.py`, qui la substitue à la table générée et joue chaque cas contre `oto.connectors.cost` ; et dans `ts/src/cost-cases.ts`, le module de ce connecteur (`connector_module`) suivi de la liste `costCases`, la relève attendue convertie par la même fonction que `async` (`withinMs`, `noDeadline`, nom qualifié).
- `ts/src/cost-cases.ts` est une donnée de test : l'index ne le réexporte pas, et aucun hôte ne déclare son connecteur ; le paquet `ts/` l'expose sous `@otomata_tech/connectors/cost-cases`, que les tests d'oto-core importent par une dépendance de développement épinglée à un commit de ce dépôt. `--check` et `tests/test_fabrique.py` échouent quand il ne suit plus le fichier.
- Un cas ajouté ici ne vaut des deux côtés qu'une fois l'épingle de développement d'oto-core montée sur le commit qui l'apporte.

### Ce qu'elle ne génère pas

- **Un adaptateur de port, propre à un fournisseur, s'écrit à la main dans `ts/src/adapters/` ; tout le reste se génère.** Un port est un contrat que définit le paquet d'oto 2 et qu'un fournisseur remplit autrement qu'une fonction décrite (le lien hébergé par lequel une personne connecte un compte chez un tiers, la liste des comptes, la sonde d'une session) ; la sortie en recopie le type, sans dépendre du paquet. La fabrique n'écrit ni ne nettoie ce dossier : elle ne touche qu'aux fichiers de `ts/src/` qui portent sa marque ; l'index qu'elle génère réexporte `ts/src/adapters/index.ts`. Premier adaptateur : `unipileHostedLinks`, pour le port `hostedLinks` (lien `POST /v2/auth/link`, comptes `GET /v2/accounts` par `offset`, sonde `GET /v2/{id}/users/me`, 401 seul vaut session morte). Comme le code généré, il ne lit aucun secret : l'hôte passe sa clé par une fonction, appelée à chaque requête.
- Le corps d'une entrée `handwritten`.
- Le runtime commun, écrit une fois par langage : consentement et renouvellement, cache de jeton (au niveau du processus, indexé par une empreinte du credential, jamais par le secret en clair), rejeu unique sur 401, limiteur de débit partagé.
- La fusion de plusieurs appels, un refus local que les contrôles déclarés ne disent pas, la construction d'un mail, l'identité opérée.
- Le texte d'un résultat : le paquet le compose, dans son adaptateur.

### Un fichier dans le client Python

Le client Python généré, quand il viendra, recevra pour un argument fichier ce que le consommateur lui donne, jamais un identifiant qu'il résoudrait : un triplet `(nom, octets, type)`, la forme d'une partie de `requests` (`files=`). La lib ne lit pas de fichier ni de chemin pour lui ; l'hôte qui l'appelle lit lui-même son fichier en transit, ou tout autre fichier, et passe ses octets. Un corps envoyé en flux, pour un gros fichier, reste au client écrit à la main (`pennylane_firm.upload_dms_file`).

### Le secret

Le code généré ne lit aucun secret. En Python, le constructeur du client reçoit les champs de `credential` et les exige par `require`. En TypeScript, le secret vient du contexte d'appel que l'hôte fournit, une fois le compte résolu (oto-pkg : docs/conception/connecteurs-et-comptes.md). Un appel sans secret échoue ; aucune clé par défaut ne le remplace.

### Le nom d'un connecteur

`connector.name` est la clé par laquelle un hôte référence le connecteur. Côté oto 2, le catalogue des connecteurs est une table et toute référence y est une clé étrangère, pour qu'un renommage ne fasse jamais disparaître des outils en silence (leçon d'oto 1, où une installation au nom inconnu était ignorée au chargement). Renommer un connecteur est donc une migration chez l'hôte, jamais une simple édition du fichier.

### Livraison

- La lib se publie sur PyPI, sur un tag posé à la main (`docs/release.md`).
- La sortie TypeScript (`ts/`, nom provisoire `@otomata_tech/connectors`, privé) n'est pas publiée : l'application hôte en dépend par un commit de ce dépôt, épinglé. Le paquet d'oto 2 n'en dépend pas ; il accepte des définitions de même forme, que l'hôte lui déclare. Une publication npm, si elle vient, part sur un tag posé à la main avec l'accord du mainteneur.

### Oto 1, connecteur par connecteur

Quand la fabrique sait générer un connecteur :
1. elle produit son client Python et ses fonctions TypeScript depuis la description ; le client Python écrit à la main est retiré ;
2. le backend d'oto 1 retire son fichier d'outils pour ce connecteur et l'enregistre par un lecteur générique de la description (écrit une fois), qui appelle le client généré ; sa logique propre passe dans la description ou dans le code écrit à la main que celle-ci référence, partagé avec oto 2 ;
3. les noms d'outils d'oto 1 de ce connecteur changent ce jour-là, avec une note de migration pour ses utilisateurs.

Le double ne reste qu'aux connecteurs pas encore basculés, et il s'éteint au premier des deux termes : tout basculé, ou oto 1 arrêté. Le lecteur exige que les descriptions partent dans la distribution PyPI.

## Décisions et alternatives écartées

- **Écrire chaque connecteur partagé deux fois à la main** : écarté le 29/09, les deux versions divergeraient. Il reste l'exception, pour un connecteur hors format.
- **Un service connecteurs séparé, en Python, sans état, le secret dans un en-tête** : abandonné le 29/09. Les connecteurs s'exécutent dans le paquet, chez l'hôte ; le détail et ses raisons sont dans oto-pkg : docs/conception/connecteurs-et-comptes.md.
- **La fabrique dans le paquet, en TypeScript** : écarté. Elle vit à côté des descriptions et de la lib qu'elle génère, pour qu'une seule source fasse foi.
- **Laisser au backend d'oto 1 ses outils écrits à la main jusqu'à son extinction** : décidé le 29/09, retiré le 06/10 ; le double durerait autant qu'oto 1.
- **Lire la description en gardant les noms et regroupements d'outils d'oto 1** (`op=`) : écarté le 06/10 ; le format porterait un vocabulaire qui disparaîtra avec oto 1.
- **Partir de zéro, sans la lib** : écarté le 30/09. La lib est gardée pour les connecteurs partagés, au secret fourni par le consommateur.
- **TypeScript seul, la lib Python gelée jusqu'à l'extinction d'oto 1** : écarté le 06/10. Une seule version des connecteurs passe par la description et la fabrique, pas par l'abandon d'un des deux langages ; la description devient la source du client Python comme du TypeScript, et un client Python écrit à la main à côté d'elle est un doublon à résorber.
- **Python seul, appelé à distance par oto 2** : écarté de nouveau le 06/10, pour les raisons du service connecteurs abandonné le 29/09.
- **Interdire un secret dans la query d'une adresse** : révisé le 2026-10-08. Certains tiers n'acceptent la clé qu'en query ; elle y est admise pour `api_key` seulement, parce que le tiers la voit déjà, et l'exécution la masque dans tout journal. Les autres secrets (secret du client, code, refresh token) restent dans le corps.
- **L'authentification `oauth2_user` écrite à la main par connecteur** : écarté le 2026-10-08. Elle se décrit ; l'hôte l'exécute une fois pour tous, comme la requête.
- **Le paquet d'oto 2 dépend de la sortie et embarque des connecteurs** : écarté le 07/10. Le paquet est le moteur ; l'application hôte choisit ses connecteurs partagés et propres, et les lui déclare.
- **Une sortie TypeScript au contrat du paquet** (fonctions `defineFunction` prêtes à inscrire) : écarté le 06/10. Elle dépendrait du paquet, qui dépendrait d'elle ; la sortie porte des définitions structurelles, que le paquet adapte.
- **Une sortie produite à la publication, non commitée** : écarté le 06/10. Commitée, elle se relit dans une revue et un test prouve qu'elle suit les descriptions.
- **Traduire le schéma d'entrée en `zod` strict** : écarté le 06/10. Trente-sept fonctions sur 340 ne se traduisaient pas (`minProperties`, `oneOf`, `anyOf` ou `not` à la racine, `dependentRequired`, `not` sur un identifiant, `uniqueItems`) ; un raffinement ne se voit pas dans le schéma servi, et deux langages de schéma devaient rester égaux. Le JSON Schema passe tel quel, validé par l'hôte.
- **La fabrique avant la prise du paquet** : écarté le 06/10. Le paquet d'oto 2 reçoit d'abord sa prise (contrat de connecteur, secret à l'appel, comptes réels), prouvée par un connecteur témoin écrit à la main au contrat du paquet, `notion` ; la fabrique génère ensuite ce même contrat et remplace le témoin.

## Sécurité et confidentialité

- Le code généré ne lit aucun secret, ni dans l'environnement ni dans un fichier. Le Python généré vit sous `oto/` et tombe sous la garde `tests/test_no_secret_read_guard.py`.
- Un secret ne part dans la query d'une adresse que si le tiers l'exige (`api_key`, `in: query`) : le tiers le voit déjà, et l'exécution le masque dans tout journal, message d'erreur compris. Tout autre secret va en en-tête ou dans le corps de la requête de jeton, comme `auth` le décrit.
- Une adresse saisie par un admin ou rendue par un jeton est gardée à l'exécution : `https` seul, jamais un hôte interne, aucune redirection.
- Une constante ou un en-tête constant est écrit en clair dans un fichier public : jamais un secret, et jamais l'en-tête d'authentification, que la règle 3 refuse de poser deux fois.
- Un refus généré dit le fait, au plus une condition, jamais le nom d'un outil (`docs/conventions.md`).
- Le dépôt et ses sorties sont publics : aucune description, aucun code généré ne nomme un client.

## Écart avec le code

- Écrits : le générateur (`fabrique/`), la sortie TypeScript commitée (`ts/src/`, vingt-sept connecteurs) et son contrat (`ts/src/types.ts`), leurs tests (`tests/test_fabrique.py`, `ts/test/`) et le contrôle en CI. Les seize règles hors schéma JSON sont vérifiées.
- Les 515 fonctions sont générées.
- La sortie Python se borne aux données du coût et du travail asynchrone (`oto/connectors/declared.py`, tenue à jour par `tests/test_fabrique.py`) et à leurs fonctions pures (`tests/test_connectors_cost.py`) ; pas de client Python généré, ni de runtime commun, ni de test de contrat entre les deux langages. L'alignement des fonctions pures sur oto-core tient aux cas communs du coût (« Les cas communs du coût »), joués des deux côtés ; ils ont révélé qu'un entier JSON au-delà de la plage d'un double (lu `Infinity` par l'hôte) faisait lever `OverflowError` côté Python, quantité relue comme identifiant de travail : la lib le lit désormais comme l'hôte, illisible (cas `settle_integer_beyond_double`, `async_job_id_integer_beyond_double`). Le client Python Sellsy reste écrit à la main, sur des verbes génériques.
- Le paquet d'oto 2 n'adapte pas encore la sortie : son client HTTP ne connaît ni `PUT`, ni la query, ni un autre mode d'authentification que le jeton porteur ; il n'exécute encore ni la validation JSON Schema, ni les constantes, l'encodage, le rythme, la sonde ou les contrôles, ni les réglages, la clé en query, `clientAuth`, le consentement `oauth2_user` et sa rotation, ni l'identité lue à une adresse complète, ni les niveaux d'accès, ni les gardes d'une adresse libre, ni un champ fourni par l'hôte (`holder: "host"`), ni l'identité d'un compte rattaché et le service qui l'écrit, ni les noms `<connecteur>_act` des fonctions `act`. Il lit le solde d'une sonde (`balance`) à partir de son commit du jalon 3 ; aucune description ne le déclare encore. Il applique le délai propre d'une fonction (`timeoutMs`) à partir de son commit qui l'écrit (oto-now/oto-core#70) ; un paquet antérieur l'ignore et applique le délai du connecteur. Il contrôle le coût d'un appel et le travail asynchrone (`async`) à partir de son commit qui les écrit, et en tire le pire cas, la quantité à régler et la relève par des fonctions pures, sans rien réserver ni régler.
- L'adaptateur `unipileHostedLinks` (2026-10-17) a ses tests contre un faux `fetch`, sans appel réel ; le nom du titulaire que rend sa sonde (`first_name` et `last_name` de `users/me`, sinon `name` ou `public_identifier`) n'est lu par aucun code existant d'oto 1, qui nomme un compte par le `name` de la liste des comptes. La garde mécanique sur les secrets (`tests/test_no_secret_read_guard.py`) ne lit que le Python.
- Les gardes d'une adresse libre ne sont écrites nulle part dans ce dépôt : la sortie les déclare, aucun code ne les exécute.
- La sortie porte `files` (2026-10-19) ; le paquet d'oto 2 l'exécute à partir de son commit qui envoie le corps multipart ; un paquet antérieur ignore `files` et envoie un corps JSON sans le fichier. Le Python n'a ni sortie ni triplet de fichier.
- Le backend d'oto 1 n'a pas de lecteur de la description : tous ses outils restent déclarés à la main.

## Questions ouvertes

- Pendant la bascule d'oto 1 vers oto 2, un connecteur utile sans description passe-t-il par un doublage à la main ?

## Historique

- 2026-09-29 : une description par connecteur et une fabrique qui génère Python et TypeScript ; le doublage à la main reste l'exception — décidé par le mainteneur (source : séance du 29/09 ; conception connecteurs d'oto 2, oto-enterprise, archivé).
- 2026-09-29 : la fabrique vit dans ce dépôt, en Python ; elle génère la lib Python et publie la sortie TypeScript en paquet npm, que le paquet d'oto 2 déclare et inscrit ; le backend d'oto 1 est hors périmètre (retiré le 06/10) — décidé par le mainteneur (source : séance du 29/09, « Périmètre, sortie TypeScript, secrets »).
- 2026-09-29 : la lib ne lit plus aucun secret : résolution locale et ses quatre fournisseurs retirés, secret exigé par `require` ; publié en 1.148.0 — décidé par le mainteneur (source : séance du 29/09).
- 2026-09-30 : la lib est gardée pour les connecteurs partagés, au secret fourni par le consommateur — décidé par le mainteneur, accord du responsable du paquet à l'oral (source : point du 30/09).
- 2026-10-05 : reprise en document de conception vivant depuis la conception connecteurs d'oto 2 (oto-enterprise, archivé) — décidé par le mainteneur.
- 2026-10-06 : une seule version des connecteurs, par la description et la fabrique ; TypeScript seul et Python à distance écartés ; la prise du paquet d'abord, avec un témoin `notion` écrit à la main — décidé par le mainteneur.
- 2026-10-06 : le backend d'oto 1 bascule connecteur par connecteur sur la description, par un lecteur générique ; ses noms d'outils changent connecteur par connecteur — décidé par le mainteneur.
- 2026-10-06 : la sortie TypeScript est commitée dans ce dépôt (`ts/`), en définitions structurelles qui ne dépendent pas du paquet ; schéma d'entrée en `zod` strict généré, refus en table, texte du résultat composé par le paquet ; première version du générateur — décidé par le mainteneur.
- 2026-10-06 : plus de `zod` dans la sortie : le JSON Schema d'entrée est transmis tel quel et validé par l'hôte avec un validateur standard ; la fabrique n'exige qu'une racine stricte, et génère les 340 fonctions ; la sortie porte en-têtes constants, constantes, encodage JSON, arrêt de pagination, rythme, sonde et contrôles — décidé par le mainteneur.
- 2026-10-07 : l'application hôte dépend de la sortie par un commit épinglé et déclare ses connecteurs au paquet d'oto 2, moteur générique sans connecteur ; pas de publication npm pour l'instant — décidé par le mainteneur.
- 2026-10-08 : la fabrique vérifie les réglages, les gabarits et l'identité d'un consentement, et porte telles quelles dans la sortie l'authentification (`oauth2_user` déclaratif compris) et les réglages ; une clé est admise en query, masquée à l'exécution — décidé par le mainteneur.
- 2026-10-16 : règle 7, les niveaux d'accès ; la sortie porte `accessLevels`, `scopeImplies` et les droits exigés d'une fonction, et rien de neuf pour un connecteur sans niveaux — décidé par le mainteneur.
- 2026-10-16 : règles 5 et 7, l'identité d'un consentement lue à une adresse complète, avec ses droits ; la sortie la porte telle quelle, sans qualifier de nom de fonction — décidé par le mainteneur.
- 2026-10-17 : règle 8, l'identité d'un compte rattaché ; la sortie porte `holder` sur chaque champ du credential et `accountIdentity` ; `base_urls` peut citer l'identité, et rien d'autre — choix du projet (source : décision du mainteneur du 16/10 sur le compte de l'hôte et le compte rattaché).
- 2026-10-17 : règle 9, `act` suit la classe ; la sortie porte `act` résolu sur chaque fonction, que l'hôte sert sous `<connecteur>_act.<fonction>` quand il est vrai — décidé par le mainteneur.
- 2026-10-17 : un adaptateur de port, propre à un fournisseur, s'écrit à la main dans `ts/src/adapters/`, réexporté par l'index ; tout le reste se génère ; premier adaptateur, le lien hébergé d'Unipile (`hostedLinks`) — décidé par le mainteneur.
- 2026-10-17 : règle 10, le signal de refus du service ; la sortie porte `body` et `marksAccount` sur une entrée de la table d'erreurs ou un refus qui les déclare, et rien de neuf ailleurs — décidé par le mainteneur.
- 2026-10-19 : règle 5, la fonction d'une sonde qui lit un solde ne déclare pas de coût ; la sortie porte `balance` (`path`, `min`, `unit`) sur la sonde qui le déclare, et rien de neuf ailleurs — décidé par le mainteneur.
- 2026-10-19 : règle 11, le délai propre à une fonction n'est pas celui du connecteur ; la sortie porte `timeoutMs` sur la fonction qui le déclare, et rien de neuf ailleurs — décidé par le mainteneur.
- 2026-10-19 : règles 12 et 13, le coût d'un appel et le travail asynchrone ; la sortie porte les clés de `cost` que la fonction déclare, seulement elles (un `{ per }` reste tel quel), et `async` avec la relève qualifiée et son délai en millisecondes — décidé par le mainteneur.
- 2026-10-19 : règle 14, les fichiers d'un corps multipart ; la sortie porte `files` sur la requête qui le déclare, et rien de neuf ailleurs ; le client Python généré recevra un fichier en triplet `(nom, octets, type)` — choix du projet (source : décision du mainteneur du 16/10).
- 2026-10-19 : règle 15, la donnée personnelle ; la sortie porte `personal: true` tel quel dans le schéma de la fonction, et rien de neuf ailleurs — décidé par Alexis.
- 2026-10-19 : règle 16, le poids d'une valeur (`weights`) ; règle 13, `no_deadline` à la place de `within_s` ; la sortie TypeScript porte `weights` et `noDeadline` quand la fonction les déclare, et rien de neuf ailleurs ; première sortie Python, des données (`oto/connectors/declared.py`) lues par des fonctions pures (`oto.connectors.cost`), vérifiée par `--check` comme la sortie TypeScript — décidé par le mainteneur.
- 2026-10-19 : les cas communs du coût (`connectors/_cases/cost.yaml`), contrôlés comme une description et sortis en `ts/src/cost-cases.ts`, joués par la lib et par oto-core — choix du projet (source : demande du mainteneur d'un jeu de cas commun au coût).
