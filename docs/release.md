# Release — PyPI, tags, et le pin d'oto-backend

Sur PyPI depuis 1.6.0 (promesse ADR 0005).

## Le geste

1. Bumper `version` dans `pyproject.toml` — **seul endroit** (pas d'`oto/__init__.py`).
2. Tag `vX.Y.Z` → **publication PyPI automatique** par `.github/workflows/publish.yml`
   (trusted publishing OIDC, aucun jeton stocké). Jamais de `twine` à la main.
3. Bumper le pin `oto-core@vX.Y.Z` dans oto-backend (il pin **par tag git**).

Un tag poussé depuis un poste est déclenché par le push ; un tag posé par `tag-release.yml` est
dispatché par lui (un tag du `GITHUB_TOKEN` ne déclenche aucun événement `push`).
Rejouer une version : `gh workflow run publish.yml --ref main -f tag=vX.Y.Z`.

## Les gardes et les pièges

- Le job **refuse un tag dont la version ne se retrouve pas** dans le pyproject, le sdist et la roue.
- ⚠️ **Toujours bumper `version` AVEC le tag.** Un tag `vX.Y.Z` posé sans bumper le champ fait mentir
  `pip show oto-core` : la prod affiche l'ancienne version malgré le bon code, et on part en fausse
  piste « bump non appliqué ».
- ⚠️ PyPI reconnaît le workflow par son **nom de fichier** : le renommer coupe la publication.
- Les installs **editable** (box, checkout local) ne sont PAS affectées par un publish — `git pull`
  reste requis.

## La version d'un connecteur

Distincte de celle de la lib : `connector.version` de `connectors/<nom>/connector.yaml` monte avec tout commit qui
change la description ou le client de ce connecteur. Le job `commits` de la CI juge chaque commit nouveau d'une PR ou
d'un push de `main` contre son parent (`python -m fabrique.commits <avant> <après>`) ; un commit de publication, qui ne
touche que la version de la lib, n'est jamais concerné, et ni un tag ni un dispatch ne lancent le job. Pour un
changement sans importance, ou un correctif urgent, un trailer du commit, à côté de `Changelog:`, en dispense :

    Version-dispense: <connecteur> — <raison>

`Version-dispense: * — <raison>` ne vaut que dans un commit qui touche `connectors/connector.schema.json` ou
`fabrique/`. Un client ajouté a sa description, ou une exception de principe motivée dans `connectors/clients.yaml`
(`tests/test_clients_described.py`) ; les exceptions en attente ne font que décroître. Détail :
`docs/conception/format-de-description.md`, « Contrôles ».
