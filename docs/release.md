# Release — PyPI, npm, tags, et le pin d'oto-backend

Sur PyPI depuis 1.6.0 (promesse ADR 0005). Sur npm, la sortie TypeScript de la fabrique
(`ts/`, paquet public `@otomata_tech/connectors`), à la même version, depuis le 20/10/2026.

## Le geste

1. Bumper la version, la même aux trois endroits, dans le même commit `chore(release): vX.Y.Z` :
   - `version` dans `pyproject.toml` (pas d'`oto/__init__.py`), et `uv.lock` qui la recopie ;
   - le paquet npm : `cd ts && npm version --no-git-tag-version X.Y.Z`, qui monte `ts/package.json` et
     `ts/package-lock.json`.
   `tests/test_npm_package_version.py` refuse un paquet npm resté en arrière.
2. Tag `vX.Y.Z` → **publication automatique** par `.github/workflows/publish.yml` :
   - PyPI, en trusted publishing OIDC, aucun jeton stocké. Jamais de `twine` à la main ;
   - npm, avec provenance, par le secret `NPM_TOKEN` du dépôt. Sans lui, le job `publish-npm` échoue
     en le disant ; la lib part quand même sur PyPI, et le paquet se rattrape par « Re-run failed
     jobs » une fois le secret posé.
3. Bumper le pin `oto-core@vX.Y.Z` dans oto-backend (il pin **par tag git**), et la version de
   `@otomata_tech/connectors` chez l'hôte qui l'installe.

Un tag poussé depuis un poste est déclenché par le push ; un tag posé par `tag-release.yml` est
dispatché par lui (un tag du `GITHUB_TOKEN` ne déclenche aucun événement `push`).
Rejouer une version : `gh workflow run publish.yml --ref main -f tag=vX.Y.Z`.

## Les gardes et les pièges

- Le job **refuse un tag dont la version ne se retrouve pas** dans le pyproject, le sdist et la roue ;
  le job `npm`, dans `ts/package.json` et `ts/package-lock.json`. `tag-release.yml` refuse de poser
  un tag que le pyproject ou `ts/package.json` ne portent pas.
- npm ne republie jamais une version, comme PyPI : rejouer un tag fait échouer la publication déjà
  partie.
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
