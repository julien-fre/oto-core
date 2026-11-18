"""La surface de `SheetsClient` est un CONTRAT.

oto-backend importe `SheetsClient`, `SheetsClientError` et `values_from_csv` depuis
`oto.tools.google.sheets.lib.sheets_client` et pinne par tag : le chemin, les méthodes et
leurs signatures sont figés.

Posé avec le découpage du client par famille d'opérations (2026-11-18, 816 lignes →
`sheets_client.py` + `_common.py` + `_style.py` + `_api/*`).

⚠️ Ajouter une méthode fait échouer ce test : c'est voulu — mets à jour la constante en
connaissance de cause.
"""
import inspect
import pathlib

from oto.tools.google.sheets.lib import sheets_client as mod

# {nom de membre: signature str, ou None pour un attribut de classe}
EXPECTED_MEMBERS = {
    '_anchor': '(self, spreadsheet_id: str, anchor: str) -> dict',
    '_batch': '(self, spreadsheet_id: str, requests: List[dict]) -> dict',
    '_dimension': '(self, spreadsheet_id: str, range: str) -> tuple',
    '_grid_range': '(self, spreadsheet_id: str, range: str) -> dict',
    '_insert': '(self, spreadsheet_id: str, sid: int, dimension: str, start: int, n: int)',
    'add_chart': "(self, spreadsheet_id: str, range: str, type: str = 'column', title: Optional[str] = None, anchor: Optional[str] = None, new_sheet: bool = False) -> dict",
    'add_sheet': '(self, spreadsheet_id: str, title: str, index: Optional[int] = None) -> dict',
    'append': "(self, spreadsheet_id: str, range: str, values: List[List[Any]], value_input: str = 'USER_ENTERED') -> dict",
    'auto_fit': '(self, spreadsheet_id: str, range: str) -> dict',
    'clear': '(self, spreadsheet_id: str, range: str) -> dict',
    'clear_conditional_formats': '(self, spreadsheet_id: str, sheet) -> dict',
    'clear_filter': '(self, spreadsheet_id: str, sheet) -> dict',
    'column_width': '(self, spreadsheet_id: str, range: str, width: int) -> dict',
    'conditional_format': '(self, spreadsheet_id: str, range: str, rule: dict) -> dict',
    'copy_sheet': '(self, spreadsheet_id: str, sheet, to_spreadsheet_id: Optional[str] = None, title: Optional[str] = None, index: Optional[int] = None) -> dict',
    'create': '(self, title: str, sheets: Optional[List[str]] = None) -> dict',
    'delete_chart': '(self, spreadsheet_id: str, chart_id: int) -> dict',
    'delete_columns': '(self, spreadsheet_id: str, sheet, start_column: str, end_column: str) -> dict',
    'delete_rows': '(self, spreadsheet_id: str, sheet, start_row: int, end_row: int) -> dict',
    'delete_sheet': '(self, spreadsheet_id: str, sheet) -> dict',
    'dropdown': '(self, spreadsheet_id: str, range: str, options: List[str]) -> dict',
    'fill': '(self, spreadsheet_id: str, range: str, value) -> dict',
    'find_replace': '(self, spreadsheet_id: str, find: str, replacement: str, range: Optional[str] = None, match_case: bool = False, whole_cell: bool = False) -> dict',
    'format': '(self, spreadsheet_id: str, range: str, style: dict) -> dict',
    'freeze': '(self, spreadsheet_id: str, sheet, rows: Optional[int] = None, cols: Optional[int] = None) -> dict',
    'get_metadata': '(self, spreadsheet_id: str) -> dict',
    'insert_columns': '(self, spreadsheet_id: str, sheet, before_column: str, count: int) -> dict',
    'insert_rows': '(self, spreadsheet_id: str, sheet, before_row: int, count: int) -> dict',
    'list_charts': '(self, spreadsheet_id: str) -> list',
    'merge': '(self, spreadsheet_id: str, range: str) -> dict',
    'number_format': "(self, spreadsheet_id: str, range: str, pattern: str, type: str = 'NUMBER') -> dict",
    'read': "(self, spreadsheet_id: str, range: str = 'A:ZZ', value_render: str = 'FORMATTED_VALUE') -> List[List[Any]]",
    'read_csv': "(self, spreadsheet_id: str, range: str = 'A:ZZ') -> str",
    'rename_sheet': '(self, spreadsheet_id: str, sheet, new_title: str) -> dict',
    'set_filter': '(self, spreadsheet_id: str, range: str) -> dict',
    'set_hidden': '(self, spreadsheet_id: str, range: str, hidden: bool) -> dict',
    'sheet_id': '(self, spreadsheet_id: str, sheet) -> int',
    'sort': '(self, spreadsheet_id: str, range: str, sort_by: List[dict]) -> dict',
    'unmerge': '(self, spreadsheet_id: str, range: str) -> dict',
    'write': "(self, spreadsheet_id: str, range: str, values: List[List[Any]], value_input: str = 'USER_ENTERED') -> dict",
    'write_csv': '(self, spreadsheet_id: str, csv_path: str, sheet_name: Optional[str] = None) -> dict',
}


def _members(cls):
    out = {}
    for name, member in inspect.getmembers(cls):
        if name.startswith("__"):
            continue
        try:
            out[name] = str(inspect.signature(member))
        except (TypeError, ValueError):
            out[name] = None
    return out


def test_membres_et_signatures_inchanges():
    got = _members(mod.SheetsClient)
    assert set(got) == set(EXPECTED_MEMBERS), (
        f"membres ajoutés: {sorted(set(got) - set(EXPECTED_MEMBERS))} / "
        f"disparus: {sorted(set(EXPECTED_MEMBERS) - set(got))}")
    for name, sig in sorted(EXPECTED_MEMBERS.items()):
        assert got[name] == sig, f"signature changée pour {name}: {got[name]}"


def test_symboles_toujours_importables_depuis_sheets_client():
    """Ce que les tests et le backend importent par ce chemin (le backend : les deux
    `_column_*`, pour l'essai à blanc de `delete_columns`)."""
    for name in ("SheetsClient", "SheetsClientError", "values_from_csv", "neutralize_formula",
                 "SCOPES", "_col_row", "_append_anchor", "_column_index", "_column_letters"):
        assert hasattr(mod, name), name


def test_aucun_module_du_connecteur_ne_depasse_500_lignes():
    lib_dir = pathlib.Path(mod.__file__).parent
    trop_gros = {
        p.name: n for p in sorted(lib_dir.rglob("*.py"))
        if (n := len(p.read_text(encoding="utf-8").splitlines())) >= 500}
    assert not trop_gros, trop_gros
