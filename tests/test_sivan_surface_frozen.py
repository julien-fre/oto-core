"""La surface de `SivanClient` est un CONTRAT, pas un détail.

oto-backend épingle oto-core par tag et importe `oto.tools.sivan` : renommer une
méthode, changer un défaut ou déplacer un symbole hors de `client.py` casse un
consommateur au bump du pin, loin d'ici. Ce test fige les membres AVEC leurs
signatures, les noms importables depuis `oto.tools.sivan[.client]`, la
correspondance entre les fonctions de la description et les méthodes du client,
et la taille des modules du paquet.

⚠️ Ce test échoue si tu ajoutes une méthode : c'est voulu — mets à jour la
constante EN CONNAISSANCE DE CAUSE, jamais par réflexe pour faire passer le vert.
"""
import inspect
import pathlib

import yaml

import oto.tools.sivan as pkg
import oto.tools.sivan.client as mod

ROOT = pathlib.Path(__file__).resolve().parent.parent
DESCRIPTION = ROOT / "connectors" / "sivan" / "connector.yaml"

EXPECTED_MEMBERS = {
    '_int_ids': "(name: 'str', values: 'Optional[Sequence[int]]') -> 'Optional[List[int]]'",
    '_parse_day': "(name: 'str', value: 'Any') -> 'datetime'",
    '_period': "(start: 'Any', end: 'Any', *, max_days: 'Optional[int]' = 31) -> 'Dict[str, str]'",
    '_post': "(self, path: 'str', body: 'Optional[Dict[str, Any]]' = None) -> 'Any'",
    '_statuses': "(values: 'Optional[Sequence[str]]') -> 'Optional[List[str]]'",
    '_strip_days': "(timesheets: 'Any') -> 'Any'",
    'list_absences': "(self, start: 'str', end: 'str', *, status: 'Optional[Sequence[str]]' = None, salaries_ids: 'Optional[Sequence[int]]' = None) -> 'Any'",
    'list_badged_events': "(self, start: 'str', end: 'str', *, companies_ids: 'Optional[Sequence[int]]' = None, salaries_ids: 'Optional[Sequence[int]]' = None) -> 'Any'",
    'list_companies': "(self) -> 'Any'",
    'list_events': "(self, start: 'str', end: 'str', *, with_absence_type: 'Optional[bool]' = None, companies_ids: 'Optional[Sequence[int]]' = None, salaries_ids: 'Optional[Sequence[int]]' = None) -> 'Any'",
    'list_salaries': "(self, with_counter: 'Optional[bool]' = None, with_absences_counter: 'Optional[bool]' = None) -> 'Any'",
    'list_timesheets': "(self, start: 'str', end: 'str', *, salaries_ids: 'Optional[Sequence[int]]' = None) -> 'Any'",
    'list_timesheets_summary': "(self, start: 'str', end: 'str', *, salaries_ids: 'Optional[Sequence[int]]' = None) -> 'Any'",
    'probe': "(self) -> 'Any'",
}

#: Méthode publique que la description ne porte pas, et pourquoi.
#: `probe` est une commodité de vérification de clé, pas une fonction exposée.
OUTSIDE_DESCRIPTION = {"probe"}


def _members():
    return {n: str(inspect.signature(getattr(mod.SivanClient, n)))
            for n in dir(mod.SivanClient)
            if not n.startswith("__") and callable(getattr(mod.SivanClient, n))}


def test_membres_et_signatures_figes():
    assert _members() == EXPECTED_MEMBERS


def test_noms_importables():
    assert pkg.__all__ == ["SivanClient"]
    for name in ("SivanClient", "BASE_URL", "EXTERNAL_PREFIX", "MAX_PERIOD_DAYS",
                 "ABSENCE_STATUSES", "RETRY_STATUSES", "MAX_ATTEMPTS", "HTTP_TIMEOUT"):
        assert hasattr(mod, name), name


def test_une_fonction_decrite_est_une_methode_du_meme_nom():
    described = {f["name"] for f in yaml.safe_load(
        DESCRIPTION.read_text(encoding="utf-8"))["functions"]}
    public = {n for n in EXPECTED_MEMBERS if not n.startswith("_")}
    assert described == public - OUTSIDE_DESCRIPTION


def test_aucun_module_de_500_lignes_ou_plus():
    package = pathlib.Path(mod.__file__).parent
    for path in package.rglob("*.py"):
        assert len(path.read_text(encoding="utf-8").splitlines()) < 500, path
