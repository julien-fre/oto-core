"""Data of a range: sort, filter, find and replace.

Composed into `SheetsClient`, which provides the transport (`_batch`, `sheet_id`,
`_grid_range`, `sheets`). Contract: `../sheets_client.py`.
"""
from typing import List, Optional

from .._common import (SheetsClientError, _choice, _column_bounds, _column_index,
                       _column_letters)

_SORT_ORDER = {'asc': 'ASCENDING', 'desc': 'DESCENDING'}


def _entered(value) -> dict:
    """A cell's `userEnteredValue`, typed: bool before number (a bool IS an int)."""
    if isinstance(value, bool):
        return {'userEnteredValue': {'boolValue': value}}
    if isinstance(value, (int, float)):
        return {'userEnteredValue': {'numberValue': value}}
    if value.startswith('='):
        return {'userEnteredValue': {'formulaValue': value}}
    return {'userEnteredValue': {'stringValue': value}}


class _DataMixin:
    def fill(self, spreadsheet_id: str, range: str, value) -> dict:
        """Put ONE value in every cell of a bounded range, in one call: a constant
        (text, number, true/false), or a formula (`=IF(C2>0;"Payé";"À relancer")`)
        written as for the FIRST cell and copied to the others, its relative
        references following each row and column as a fill-down would.

        The range is bounded on both axes (`'Suivi'!F2:F120`): an open `F2:F` would
        reach the last row of the grid, far below the data."""
        grid = self._grid_range(spreadsheet_id, range)
        if not {'startRowIndex', 'endRowIndex', 'startColumnIndex',
                'endColumnIndex'} <= set(grid):
            raise SheetsClientError(
                f"range {range!r}: bounded rows and columns, e.g. 'Tab'!F2:F120")
        if value is None or isinstance(value, (list, dict)):
            raise SheetsClientError("value: one text, number, true/false or formula")
        if isinstance(value, str) and value.startswith('='):
            first = {**grid, 'endRowIndex': grid['startRowIndex'] + 1,
                     'endColumnIndex': grid['startColumnIndex'] + 1}
            requests = [{'updateCells': {'range': first, 'fields': 'userEnteredValue',
                                         'rows': [{'values': [_entered(value)]}]}},
                        {'copyPaste': {'source': first, 'destination': grid,
                                       'pasteType': 'PASTE_FORMULA'}}]
        else:
            requests = [{'repeatCell': {'range': grid, 'cell': _entered(value),
                                        'fields': 'userEnteredValue'}}]
        self._batch(spreadsheet_id, requests)
        cells = ((grid['endRowIndex'] - grid['startRowIndex'])
                 * (grid['endColumnIndex'] - grid['startColumnIndex']))
        return {'range': range, 'cells': cells,
                'formula': isinstance(value, str) and value.startswith('=')}

    def sort(self, spreadsheet_id: str, range: str, sort_by: List[dict]) -> dict:
        """Sort the rows of a range by one or more of its columns, in order:
        `[{"column": "C", "order": "desc"}, {"column": "A"}]` (asc by default). The
        range holds DATA only: leave a header row out of it (`'Tab'!A2:F`)."""
        if not isinstance(sort_by, list) or not sort_by:
            raise SheetsClientError('sort_by: a list of {"column": "C", "order": "asc|desc"}')
        grid = self._grid_range(spreadsheet_id, range)
        start, end = _column_bounds(grid, range)
        specs = []
        for item in sort_by:
            if not isinstance(item, dict) or set(item) - {'column', 'order'} or 'column' not in item:
                raise SheetsClientError(
                    f'sort_by: each item is {{"column": "C", "order": "asc|desc"}} (got {item!r})')
            col = _column_index(item['column'])
            if not start <= col < end:
                raise SheetsClientError(
                    f"sort_by: column {item['column']!r} is outside {range!r}")
            order = _choice(_SORT_ORDER, item.get('order', 'asc'), 'order')
            specs.append({'dimensionIndex': col, 'sortOrder': order})
        self._batch(spreadsheet_id, [{'sortRange': {'range': grid, 'sortSpecs': specs}}])
        back = {v: k for k, v in _SORT_ORDER.items()}
        return {'range': range, 'sorted_by': [
            {'column': _column_letters(s['dimensionIndex']), 'order': back[s['sortOrder']]}
            for s in specs]}

    def set_filter(self, spreadsheet_id: str, range: str) -> dict:
        """Put the filter buttons on a range (its first row = the header). A tab holds
        one such filter: it replaces the one in place."""
        grid = self._grid_range(spreadsheet_id, range)
        self._batch(spreadsheet_id, [{'setBasicFilter': {'filter': {'range': grid}}}])
        return {'range': range, 'filter': True}

    def clear_filter(self, spreadsheet_id: str, sheet) -> dict:
        """Remove the filter of a tab (its data stays, every row shown again)."""
        sid = self.sheet_id(spreadsheet_id, sheet)
        self._batch(spreadsheet_id, [{'clearBasicFilter': {'sheetId': sid}}])
        return {'id': sid, 'filter': False}

    def find_replace(self, spreadsheet_id: str, find: str, replacement: str,
                     range: Optional[str] = None, match_case: bool = False,
                     whole_cell: bool = False) -> dict:
        """Replace `find` by `replacement` in a range, or in EVERY tab without one.
        Formulas are left alone. Returns what changed (occurrences, rows, tabs)."""
        if not isinstance(find, str) or not find:
            raise SheetsClientError("find: a non-empty text")
        request: dict = {'find': find, 'replacement': str(replacement),
                         'matchCase': bool(match_case), 'matchEntireCell': bool(whole_cell),
                         'includeFormulas': False}
        if range:
            request['range'] = self._grid_range(spreadsheet_id, range)
        else:
            request['allSheets'] = True
        reply = self._batch(spreadsheet_id, [{'findReplace': request}])['replies'][0]
        found = reply.get('findReplace', {})
        return {'range': range or '(all tabs)',
                'occurrences': found.get('occurrencesChanged', 0),
                'rows': found.get('rowsChanged', 0), 'tabs': found.get('sheetsChanged', 0)}
