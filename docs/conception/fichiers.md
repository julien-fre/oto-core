# Fichiers envoyés et rendus

- **Statut** : validé par le mainteneur le 29/09/2026 (issu du [format de description](format-de-description.md))
- **Dernière révision** : 2026-11-03

## Résumé

Un fichier ne passe jamais par le contexte de l'agent, ni en octets ni en adresse. Une fonction qui envoie un fichier à un tiers reçoit l'identifiant d'un fichier de l'hôte (`call.files`, corps `multipart/form-data`) ; une fonction dont la sortie est un fichier le déclare par `output.file`, et l'hôte d'oto 2 le range en fichier en transit de la personne qui appelle et ne rend que son identifiant, que l'agent passe tel quel à une fonction qui prend un fichier. Exemple directeur : l'enregistrement d'un appel, que relit une transcription.

## Contexte

- Une adresse signée de tiers fait des centaines de caractères, l'agent l'abîme en la recopiant, elle expire et donne le fichier à qui la détient ; des octets en base64 rempliraient le contexte.
- L'hôte d'oto 2 tient des fichiers en transit, propres à une personne, pour 24 heures, et des fichiers joints à une page (oto-pkg : docs/conception/fichiers-et-stockage.md, « Fichier en transit » ; connecteurs-et-comptes.md, « Fichiers envoyés à un tiers », « Fichiers rendus par un tiers »).

## Objectifs et non-objectifs

- Un argument fichier et une sortie fichier dits dans le fichier de description, exécutés pareil par les deux langages.
- L'entrée reste un JSON Schema 2020-12 standard.
- Hors objectif : la durée et le stockage d'un fichier, règles de l'hôte.

## Conception

### Un fichier envoyé

`call.files` associe un nom de partie à l'argument qui porte l'identifiant d'un fichier, et fait partir le corps en `multipart/form-data` :

```yaml
input:
  type: object
  additionalProperties: false
  required: [company_id, parent_folder_id, file]
  properties:
    company_id: { type: integer }
    parent_folder_id: { type: integer }
    file: { type: string, format: uuid, description: "Id of a transit file of yours: the file to upload." }
    name: { type: string, maxLength: 255 }
call:
  method: POST
  path: "/companies/{company_id}/dms/files"
  body: { parent_folder_id: parent_folder_id, name: name }
  files: { file: file }
```

- Chaque entrée de `body` et chaque constante de corps devient une partie texte (un texte tel quel, un nombre ou un booléen écrit, le reste en JSON) ; chaque entrée de `files`, une partie fichier, au nom et au type du fichier, que l'agent ne fournit pas. Un argument absent ne part pas.
- L'hôte lit le fichier sous l'identité de l'appelant : un fichier en transit de l'appelant, ou un fichier joint à une page qu'il lit, son lien `/f/<id>`. Un identifiant inconnu, échu, d'une autre personne ou d'une page qu'il ne lit pas est refusé de la même façon qu'un fichier inconnu, sans dire pourquoi. Le contenu n'est jamais rendu à l'agent ni écrit au journal.
- Un fichier joint à une page n'est jamais consommé : il vit avec sa page. Après un envoi réussi, l'hôte consomme le fichier en transit (il l'efface) ; sur un refus du tiers ou un envoi ambigu (délai dépassé, 5xx), il ne le consomme pas, et le fichier reste à son auteur jusqu'à son échéance. Le texte servi d'un argument fichier dit les deux sortes : « Id of an audio file: a transit file of yours, or a file on a page you can read (from its link /f/<id>). », et celui de la fonction, quand il dit la consommation, dit qu'un fichier en transit est consommé une fois que le tiers l'accepte et qu'un fichier de page reste.
- La fabrique refuse (règle 14, [fabrique](fabrique.md)) : `files` sur une méthode qui n'envoie pas de corps (`GET`, `DELETE`) ou sur une fonction paginée ; un argument fichier qui n'est pas un texte ou que `encode` nomme ; un nom de partie fichier qui est aussi une entrée ou une constante de `body`. Le corps multipart n'a pas de table emboîtée ni de corps entier ([corps d'une requête](corps-de-requete.md)).
- Le type « fichier » est porté par la place de l'argument, `files`, pas par son schéma.

**Compatibilité des épingles.** Une description qui déclare `call.files` exige oto-core à partir de son commit 3fe2fa6 (fichiers envoyés en multipart, lus sous l'identité de l'appelant) ; une description qui dit un fichier joint à une page l'exige à partir de son commit 9e58c01 : un paquet plus ancien refuse ce fichier comme un fichier inconnu. Un hôte monte ensemble ses deux épingles, celle de ce dépôt et celle d'oto-core. Ce dépôt n'a pas de journal des versions : ce rappel en tient lieu.

### Un fichier rendu

```yaml
# Une téléphonie dont la fiche d'un appel porte l'adresse signée de son enregistrement (une heure).
- name: get_call_recording
  class: read
  description: >-
    Get the audio recording of one call as a file of yours, kept 24 hours:
    the answer gives its file id, to pass as is to a function that takes a
    file (a transcription). Never a link.
  call: { method: GET, path: "/v1/calls/{call_id}" }
  output:
    file:
      from: url                    # body, url, base64, base64url ou json
      path: call.recording         # le champ de la réponse JSON qui porte l'adresse
      types: { mp3: [audio/mpeg, audio/mp3] }
      name: { template: "call-{call_id}-recording.mp3" }
# Une téléphonie qui rend l'audio pour corps, derrière l'authentification du compte :
  output: { file: { from: body, types: { wav: [audio/wav, audio/x-wav, audio/wave], mp3: [audio/mpeg] },
                    name: { header: Content-Disposition, template: "recording-{recording_id}.wav" } } }
# Un service qui rend sa transcription en JSON : la branche `data.result` devient le fichier.
  output: { file: { from: json, path: data.result, name: { template: "transcription-{transcription_id}.json" } } }
```

- `from`, où sont les octets : `body`, le corps de la réponse (une réponse binaire) ; `url`, une adresse que porte la réponse JSON au chemin pointé `path`, téléchargée aussitôt ; `base64` ou `base64url`, les octets encodés dans un champ de la réponse JSON, au chemin `path` ; `json`, la réponse JSON elle-même, ou sa branche au chemin `path`, facultatif. La réponse JSON qui porte l'adresse ou l'encodage ne sort jamais : ni rendue, ni journalisée. Le client Python rend le fichier à son consommateur, qui le range où il veut.
- `from: json` : un résultat trop gros ou trop riche pour être rendu à l'agent (une transcription, un export) devient un fichier. Le fichier est la réponse entière, ou, sous `path`, sa branche, lue comme tout chemin d'un fichier rendu (des clés séparées par des points, un indice de liste en nombre : `pages.1` ; une liste n'est pas traversée, `pages.text` ne désigne rien), par le même code que `url` et `base64` de chaque côté. Il est écrit en JSON comme l'écrit l'hôte, `JSON.stringify` de ce que lit `JSON.parse` : sans espace, en UTF-8, un nombre lu en double (`1.0` s'écrit `1`, `1.5e16` `15000000000000000`, un entier au-delà de 2⁵³ arrondi), les clés qui sont des indices de tableau d'abord, une clé en double gardant sa dernière valeur ; la lib Python l'écrit à l'identique. Son type est `application/json` : `types` est refusé. Son nom est son gabarit seul, qui finit par `.json` : ni `header`, ni `name.path`. `max_bytes` va de 1 octet à 4 Mo (4 194 304, la borne d'une réponse JSON chez l'hôte d'oto 2), 4 Mo par défaut, et borne le fichier écrit ; une réponse de plus de 4 Mo est refusée (`file_too_large`) avant d'être lue. Un chemin qui ne mène à rien, ou à une valeur nulle, une chaîne, une liste ou un objet vides (la réponse entière comprise) refuse le fichier (`file_missing`) : jamais un fichier vide ; `0` et `false` sont des fichiers. Une réponse qui n'est pas du JSON (`NaN` compris) est illisible (`file_unreadable`). `auth` n'a pas de sens ; `expect` vaut, la réponse étant du JSON.
- `auth` (`from: url` seulement) : `none` par défaut, une adresse signée portant sa propre signature et ne recevant aucun secret ; `account`, l'authentification du compte, posée seulement si l'adresse est à la même origine (schéma, hôte, port) que `base_url` résolue, sinon l'appel est refusé sans rien télécharger.
- `types` : les extensions que la fonction peut rendre, chacune avec les types MIME que le tiers peut annoncer, le premier étant celui du fichier rangé. Une réponse dont le type annoncé (`Content-Type`, sans ses paramètres) n'est ni l'un des types MIME de l'extension retenue pour le nom, ni `application/octet-stream` ou `binary/octet-stream`, ni absent, est refusée : une page d'erreur HTML ou un JSON sous un 200 ne passe pas pour le fichier. Chez l'hôte, le type d'un fichier vient de l'extension de son nom ; chaque extension déclarée est donc un type du paquet d'oto 2, au même premier type MIME (vérifié par l'hôte à la déclaration), jamais un type qu'ouvre le lecteur propre à un hôte.
- `name`, essayé dans cet ordre : `header` (un en-tête de la réponse ; `Content-Disposition` se lit selon la RFC 6266, `filename*` avant `filename`), `path` (un champ de la réponse JSON), puis `template`, exigé, un gabarit sur les arguments requis de l'entrée (`{call_id}`) qui finit par une extension de `types`. Le premier nom dont l'extension est déclarée l'emporte. Un nom se réduit à son dernier segment, sans caractère de contrôle, 255 caractères au plus.
- `max_bytes` : de 1 octet à 50 Mo (52 428 800, le plafond d'un fichier chez l'hôte d'oto 2), 50 Mo par défaut (4 Mo pour `from: json`) ; un fichier vide est refusé. Un `Content-Length` au-delà fait refuser avant toute lecture ; sinon les octets se comptent à la lecture, arrêtée au premier qui passe la borne. Une réponse en base64 se lit jusqu'à la taille encodée de `max_bytes`, au-delà des 4 Mo d'une réponse JSON ordinaire.
- Délai : celui de la fonction (`timeout_s`) vaut pour chaque requête, le téléchargement compris, lecture du corps comprise. Durée : 24 heures, celle de tout fichier en transit ; la description ne la change pas.
- L'adresse téléchargée (`from: url`) : `https` seul, sans identifiants, vers un hôte qui ne résout jamais vers une adresse interne, aucune redirection suivie ; elle n'apparaît dans aucun résultat, message ni journal.
- Refus, rien n'étant gardé : champ d'adresse ou d'encodage absent ou vide, ou branche JSON absente ou vide (le tiers n'a pas de fichier), téléchargement refusé (statut hors 2xx : une adresse expirée se relit en rappelant la fonction), trop gros, type annoncé refusé, encodage illisible, délai dépassé, adresse d'une autre origine sous `auth: account`. Les refus de la fonction et la table d'erreurs valent pour l'appel à l'API ([erreurs](signal-de-refus.md)). Le vocabulaire de chaque côté est dans sa conception : oto-pkg, « Fichiers rendus par un tiers » ; [fabrique](fabrique.md), « Un fichier dans le client Python ».
- `output.file` est exclusif des autres formes d'`output` (`items`, `strip`, `projection`, `schema`), jamais sur une fonction paginée, asynchrone ou relève d'un travail asynchrone, mais admis sur une fonction longue ([travaux longs](travaux-longs.md)), dont le fichier vient du même appel. La fabrique juge le reste par sa règle 17 ([fabrique](fabrique.md)) : `path` selon `from`, `auth` hors `from: url`, les contraintes de `from: json`, `header` avec un `from` en base64, le gabarit, les extensions (1 à 16 minuscules ou chiffres), les types MIME (bien formés, sans paramètre, jamais un type qu'un navigateur rend en page ou exécute : `text/html`, `image/svg+xml`, XML, JavaScript), `max_bytes`, `expect` avec `from: body`. Ses cinq codes (`file_output_not_alone`, `file_auth_not_url`, `file_json_types`, `file_json_name`, `file_json_max_bytes`), les mêmes des deux côtés, sont jugés avant les autres refus de la règle ; les cas communs (`connectors/_cases/file.yaml`) portent une fonction refusée pour chacun.

### Contrôles

Le test du schéma fait refuser, pour les fichiers envoyés, cinq variantes (`files` vide, en liste, à argument vide, qui n'est pas un identifiant ou pas un texte) ; pour le fichier rendu, vingt-cinq (`from` inconnu ou absent, `types` absent ou vide, extension sans type, en majuscules, de plus de 16 caractères ou à point, type MIME à paramètres, mal formé, en majuscules ou en double, `name` absent ou vide, sans gabarit, gabarit vide, clé de nom inconnue, en-tête mal formé, `auth` inconnu, `max_bytes` nul, au-delà de 50 Mo, non entier ou en texte, chemin mal formé, durée déclarée : `transit_hours`, clé inconnue).

## Décisions et alternatives écartées

- **Un `type: file` dans le schéma d'entrée** (ou un mot-clé propre, `x-file`) : écarté le 2026-10-19. L'entrée est un JSON Schema 2020-12 servi et validé tel quel par un validateur standard, qui refuse un type inconnu ; un argument fichier y est un texte, l'identifiant, et c'est sa place, `call.files`, qui le dit fichier.
- **Les octets en base64 dans un argument, ou une adresse à télécharger** : écartés le 2026-10-16. Les octets passeraient par le contexte de l'agent ; une destination ne reçoit qu'un identifiant de fichier de l'hôte.
- **Rendre à l'agent l'adresse signée du tiers, ou les octets en base64** : écarté par le mainteneur le 2026-10-21. L'agent abîme l'adresse en la recopiant (refus 400 ou 403 du tiers, sans cause lisible), elle expire, elle donne le fichier à qui la détient et entrerait en clair au journal de l'appel suivant. Les lectures qui rendaient de telles adresses les retirent (`output.strip`) et l'audio se rend par une fonction à sortie fichier.
- **Un bloc `response` ou une sortie nommée à côté d'`output`** : écarté le 2026-10-21. Un fichier est une forme d'`output`, exclusive des autres.
- **Le type du fichier pris du `Content-Type` du tiers, ou une liste de types MIME seule** : écarté le 2026-10-21. L'hôte décide le type par l'extension du nom ; le type annoncé ne sert qu'à refuser ce qui n'est manifestement pas le fichier.
- **Une durée de transit déclarée par la fonction** (`transit_hours`) : écartée le 2026-10-21. La durée est une règle de stockage et de quota de l'hôte, une seule pour tout fichier en transit ; un fichier à conserver plus longtemps se garde sur une page.
- **Des types réservés au transit, ou ouverts par un hôte** (`registerReaders`) : écartés le 2026-10-21. Les types audio (`mp3`, `wav`, `m4a`, `ogg`) entrent dans les types du paquet d'oto 2, pour tout fichier ; un type ouvert par un hôte ne vaut pas pour une description partagée, qui les sert tous.
- **Un plafond au-delà de 50 Mo pour un enregistrement** : écarté le 2026-10-21. Un WAV de téléphonie non compressé passe 50 Mo vers 55 minutes, un MP3 vers plusieurs heures ; au-delà, le refus `file_too_large`.
- **Suivre les redirections d'une adresse de téléchargement** : écarté à l'étape 1 le 2026-10-21. L'adresse directe suffit aux cas connus ; chaque saut serait une adresse de plus à garder, et l'authentification ne devrait pas le suivre. À rouvrir avec une description qui en a besoin.

## Sécurité et confidentialité

- Une adresse que rend un tiers pour télécharger un fichier est un jeton porteur : consommée par l'exécution, gardée comme une adresse saisie (`https`, jamais un hôte interne, aucune redirection), jamais rendue, citée dans un message ni journalisée. L'authentification du compte ne la suit que sous `auth: account` et vers l'origine de l'API : le secret ne part jamais vers un autre hôte.
- Un fichier envoyé est lu sous l'identité de l'appelant ; un identifiant d'autrui est refusé comme inconnu.

## Écart avec le code

- Oto-core exécute `call.files` (relu à son commit d26f513, `multipart.ts`) et `output.file` hors `from: json` (relu à son commit f14aa1b, `file-output.ts`). Il n'exécute pas encore `from: json` : un paquet antérieur le refuse à la déclaration ; une description qui le déclare n'est épinglée qu'avec un paquet qui l'exécute.
- Le corps brut (le fichier seul pour corps) n'est pas écrit.
- La lib écrit le fichier rendu (`oto/connectors/files.py`) mais n'a pas de sortie Python générée qui enverrait un fichier ; la forme prévue est dans [fabrique](fabrique.md). Des clients écrits à la main rendent encore leurs octets sans `file_output`.
- `aircall` et `allo` : que les adresses d'enregistrement soient signées par leur propre query, le type que sert le stockage et le format réel se vérifient au premier essai réel, avant toute publication. `aircall` rend encore les adresses audio des messages d'une ligne (`messages.welcome`, `messages.voicemail`…, `list_numbers`, `get_number`), à revoir.

## Questions ouvertes

- Le corps brut (le fichier seul pour corps, son nom dans un en-tête : téléversement de média), décidé le 16/10 et pas encore écrit, faute de description qui l'attende.
- Les types qu'un tiers admet (une pièce comptable : PDF ou image), que la description ne dit pas et que le tiers refuse à l'envoi.
- Un fichier dont la réponse ne dit ni le nom ni le type (`gmail.get_attachment` : le nom est dans le message, pas dans la pièce), qui demanderait un nom passé en argument.
- Un fichier envoyé en base64 dans un corps JSON (`origami.upload_documents`, la pièce jointe d'un courriel `brevo`), que `call.files` ne dit qu'en multipart ; une réponse CSV, à rendre en fichier (`lemlist`) ; une sortie audio générée en octets ou en base64 (`elevenlabs`).

## Historique

- 2026-10-16 : type fichier et corps multipart ; un fichier passe par un identifiant de l'hôte, jamais en octets ni en adresse — décidé par le mainteneur (source : revue des connecteurs d'oto 2 du 16/10).
- 2026-10-19 : fichiers en entrée : `call.files`, l'argument qui porte l'identifiant d'un fichier en transit de l'appelant ; les entrées de `body` en sont les parties texte ; lu sous l'identité de l'appelant, consommé après un envoi réussi seulement ; le type fichier dit par la place de l'argument ; règle 14 de la fabrique, sortie TypeScript `request.files` — choix du projet (source : décision du mainteneur du 16/10).
- 2026-10-21 : le fichier rendu : `output.file` (`from`, `path`, `auth`, `types`, `name`, `max_bytes` jusqu'à 50 Mo) ; l'adresse ou l'encodage du tiers jamais rendu ni journalisé ; règle 17 ; durée de 24 h pour tous, non déclarable ; types audio admis par le paquet d'oto 2 ; aucune redirection suivie — décidé par le mainteneur (source : chantier « fichier », étape 1).
- 2026-10-22 : le fichier JSON : `output.file.from: json`, la réponse JSON ou sa branche, écrite comme l'écrit l'hôte, 4 Mo au plus ; cinq codes de la règle 17 — décidé par le mainteneur.
- 2026-10-22 : `output.file` admis sur une fonction longue — décidé par le mainteneur.
- 2026-10-23 : un argument fichier admet aussi un fichier joint à une page que l'appelant lit (son lien `/f/<id>`), jamais consommé ; le texte servi le dit — choix du projet, qui applique une règle d'oto-core (source : oto-pkg, docs/conception/connecteurs-et-comptes.md, « Fichiers envoyés à un tiers »).
- 2026-11-03 : sorti de la note « Format de description » lors de son redécoupage en documents par sujet ; les résumés par connecteur sortent pour la carte du parc et l'en-tête de chaque description — décidé par le responsable produit (source : demande de rationalisation des connecteurs).
