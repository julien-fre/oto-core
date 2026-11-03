# Travaux longs : travail asynchrone et fonction longue

- **Statut** : validé par le mainteneur le 29/09/2026 (issu du [format de description](format-de-description.md))
- **Dernière révision** : 2026-11-03

## Résumé

Deux formes disent un appel dont le résultat n'arrive pas tout de suite. `async` : le tiers tient le travail ; une soumission rend un identifiant, une fonction de relève décrite le relit. `background: true` : le tiers répond en minutes à un appel unique et synchrone ; l'hôte d'oto 2 l'exécute en tâche de fond et rend aussitôt un identifiant de travail, relevé par sa fonction native. Les deux sont des faits du tiers, pas des choix de l'hôte.

## Contexte

- Un rapport, un téléchargement, une ingestion, un enrichissement en lot se soumettent, puis se relèvent par une autre route.
- Une transcription audio répond en un seul appel, mais de 20 s à 5 min pour 30 min d'audio : l'assistant ne doit pas attendre la réponse dans sa requête.
- Un coût réglé à la relève demande de savoir quand la quantité est lisible ([coût et solde](cout-et-solde.md)).

## Objectifs et non-objectifs

- Relier une soumission à sa relève, par l'identifiant seul, pour l'agent comme pour l'hôte.
- Dire quand un travail est fini, ou dire qu'il n'a pas d'échéance, sans inventer de délai.
- Hors objectif : la table des travaux de l'hôte et sa relève native (oto-pkg : docs/conception/fonctions-longues.md).

## Conception

### Travail asynchrone

```yaml
- name: start_insights_report
  async: { collect: get_report_status, job_id: { from: report_run_id, to: report_run_id } }

# Un lot réglé à la relève :
- name: submit_enrichment
  cost: { per: item, items: contacts, unit: credits, settle: { path: cost.credits } }
  async: { collect: get_enrichment, job_id: { from: id, to: enrichment_id }, within_s: 600 }
```

- `collect` : une autre fonction de lecture du connecteur, appelée par `call`, qui n'est pas elle-même asynchrone, et dont `job_id.to` est le seul argument requis : la relève se fait avec l'identifiant du travail seul (règle 13 de la [fabrique](fabrique.md)).
- `job_id.from` : chemin pointé de l'identifiant dans la réponse de la soumission ; `job_id.to` : l'argument de la relève qui le reçoit. Un identifiant lu comme un nombre qui n'est pas fini (un entier JSON au-delà de la plage d'un double) est illisible et refusé ([coût et solde](cout-et-solde.md), « Nombre fini »).
- `within_s` : le délai de relève, en secondes après la soumission ; passé ce délai, le travail est fini et sa quantité lisible. Un entier de 1 à 86 400 : une réservation tient des crédits de l'organisation tant qu'elle court, et un travail plus long qu'un jour n'est plus un appel qu'un agent attend. Plus long que le délai de la soumission (règle 13). Exigé quand le coût se règle (`settle`), sauf `no_deadline`, facultatif sinon ; aucune valeur ne s'invente sans source qui borne la durée du travail.
- `no_deadline: true`, exclusif de `within_s` : la référence de l'éditeur dit qu'un travail n'a pas d'échéance (« Jobs don't expire and there's no automatic timeout »), et le fichier le cite. La réservation court jusqu'à la première quantité lisible dans les réponses de la relève, ou jusqu'à un plafond fixé par le moteur qui réserve, un réglage de ce moteur, le même pour tous ; au-delà, sans valeur lisible, on règle le pire cas, et le règlement le dit. Un règlement est idempotent : une quantité lue plus tard ne le modifie pas. Le plafond n'est pas dans la description : il dit combien de temps une organisation accepte de voir des crédits retenus, pas ce que fait l'éditeur.

Le règlement d'une fonction asynchrone se déclare sur la fonction qui soumet, et `cost.settle.path` se lit dans les réponses de sa relève. La réservation naît à la soumission, de ses arguments ; la relève, appelée tant que le travail court, ne réserve rien et ne déclare ni `settle` ni pagination (règle 13). La première réponse de la relève qui porte au chemin un nombre lisible le règle ; avant elle, une valeur absente veut dire « pas encore » ; à l'échéance, `within_s` après la soumission (ou au plafond du moteur, sous `no_deadline`), sans valeur lisible, on règle le pire cas. Sans `settle`, la quantité se connaît dès la soumission et rien n'attend la relève.

Une soumission qui ne fait que lire (un rapport, un téléchargement, une ingestion d'une source publique) est une lecture (`class: read`), même si elle consomme un quota du tiers. Le résultat d'un travail terminé lu par une troisième fonction n'est pas relié par le format.

### Fonction longue

```yaml
- name: transcribe_audio
  class: read
  call:
    method: POST
    path: /audio/transcriptions
    body: { language: language }
    files: { file: file }
  timeout_s: 300                   # le délai de l'appel lui-même, file non comprise
  background: true
  cost: { per: request, unit: seconds, settle: { path: usage.audio_seconds } }
  output:
    file: { from: json, name: { template: transcription.json } }
```

- La réponse finale est exactement celle de l'appel synchrone (données, fichier rendu, refus) ; seul le moment change.
- `timeout_s` propre à la fonction est exigé, de 1 à 300 s : le délai de l'appel lui-même, l'attente en file non comprise ; jamais égal à celui du connecteur (règle 11). Celui du connecteur ne suffit pas : un délai est un plafond, pas une durée attendue, et la tâche de fond ne se déduit pas d'un délai long, que déclarent aussi des fonctions qui répondent en une seconde.
- La description ne dit rien de l'identifiant de travail : l'hôte ajoute au texte servi une phrase fixe sur la relève, et aucune description ne la réécrit.
- `class` et `act` valent tels quels, `write` et `act: true` compris. `confirm` se juge avant le lancement : le récapitulatif d'une fonction sensible est montré avant la mise en file. Le coût se règle à la fin du travail, sur la réponse finale, comme pour un appel synchrone.
- `output.file` est admis (règle 17) : le fichier vient du même appel. `call.files` aussi : le fichier d'entrée n'est consommé qu'après un envoi réussi ([fichiers](fichiers.md)).
- Le client Python ignore `background` et appelle en synchrone : son consommateur choisit où l'appel tourne. La sortie TypeScript porte `background: true` sur la fonction (`ConnectorFunction.background`), à côté de `timeoutMs` ; les données Python (`oto/connectors/declared.py`) ne le portent pas.

### Contrôles

La fabrique refuse (règle 21), dans cet ordre, chacun par son code : une fonction longue sans `timeout_s` propre (`background_no_timeout`) ; avec `async` (`background_async` : un travail que tient le tiers a sa relève décrite) ; relève d'un travail asynchrone (`background_collect` : une relève répond tout de suite) ; paginée (`background_paginated` : un appel, une réponse). Le schéma n'admet que `true`. Le test du schéma fait refuser, pour le travail asynchrone, quatorze variantes (délai nul, au-delà d'un jour, non entier, en texte, clé inconnue, identifiant sans `to`, à segment vide, à clé inconnue, sans `collect`, coût réglé sans délai, `no_deadline` faux, en texte, avec un délai, et faux sur un coût réglé) ; pour la fonction longue, quatre (`background` faux, en texte, en nombre, nul). Cas communs : `connectors/_cases/cost.yaml` (la relève) et `connectors/_cases/background.yaml`, une fonction refusée par code et des fonctions acceptées qui combinent `background` avec ce qu'il admet.

## Décisions et alternatives écartées

- **Laisser `within_s` absent sans rien dire** : écarté le 2026-10-19 ; on ne distinguerait pas une échéance oubliée d'une échéance qui n'existe pas (`no_deadline`).
- **Déduire la tâche de fond d'un délai long** : écarté le 2026-10-22 ; un délai est un plafond, pas une durée attendue.
- **Décrire un appel long comme un travail asynchrone** : écarté ; `async` est la forme d'un travail que tient le tiers (une soumission, puis une relève décrite), `background` celle d'un appel long dont l'hôte tient l'attente.

## Sécurité et confidentialité

- L'identifiant d'un travail ne donne rien de plus que la fonction de relève, servie sous les mêmes droits du compte.
- Une fonction longue sensible est confirmée avant sa mise en file, jamais après.

## Écart avec le code

- Oto-core contrôle `async` comme la fabrique et en tire la relève et son échéance par une fonction pure (`collectionOf`, relu à son commit d26f513), que son moteur n'appelle pas.
- Oto-core n'exécute pas encore la fonction longue : ni la table des travaux, ni `runJobs`, ni `job.read` ne sont écrits (oto-pkg : docs/conception/fonctions-longues.md). Relu à son commit 194b1b8, il ne refuse aucune clé inconnue sur une fonction : un paquet antérieur ignore `background` sans bruit et appelle en synchrone, l'assistant attendant jusqu'à 300 s. Une description qui le déclare n'est épinglée qu'avec un paquet qui l'exécute, les deux épingles montant ensemble.

## Questions ouvertes

- Le résultat d'un travail asynchrone lu par une autre fonction que sa relève (les lignes d'un rapport `meta_ads`).
- Le résultat d'un travail asynchrone rendu en fichier par sa relève.
- Un travail asynchrone (import, export) qui rend `{processId}` et se suit par une route commune (`brevo`), que le client ne lit pas : rien n'est déclaré.

## Historique

- 2026-10-17 : une soumission qui ne fait que lire est une lecture (`class: read`) — décidé par le mainteneur.
- 2026-10-19 : `async` relie une soumission à sa relève (`collect`, `job_id`, `within_s` d'un jour au plus, exigé quand le coût se règle, la quantité lue alors dans les réponses de la relève) ; règle 13 de la fabrique — décidé par le mainteneur.
- 2026-10-19 : `async.no_deadline`, exclusif de `within_s`, à la condition que la description cite la source qui dit qu'un travail n'a pas d'échéance ; le plafond d'une telle réservation est un réglage du moteur qui réserve, hors du format ; au-delà, règlement au pire cas, idempotent — décidé par le mainteneur.
- 2026-10-22 : la fonction longue : `background: true`, un `timeout_s` propre exigé, refusée avec `async`, sur une relève et paginée (règle 21) ; `class: write`, `act` et `confirm` admis ; `output.file` admis ; le client Python l'ignore — décidé par le mainteneur (source : oto-pkg, docs/conception/fonctions-longues.md).
- 2026-11-03 : sorti de la note « Format de description » lors de son redécoupage en documents par sujet ; les résumés par connecteur sortent pour la carte du parc et l'en-tête de chaque description — décidé par le responsable produit (source : demande de rationalisation des connecteurs).
