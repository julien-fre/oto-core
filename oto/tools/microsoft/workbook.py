"""Microsoft Graph client — the cells of an Excel workbook stored in SharePoint or
OneDrive, read and written in place by a signed-in person (delegated access, scope
`scopes.FILES`): its worksheets, a range's values, a range written.

## Protocol facts that shape a caller

- **A workbook is a drive item** (`.xlsx`, `.xlsm`), addressed like any file: `drive_id`
  plus `item_id` or `path` (see `FilesClient`). Graph's workbook API does not open
  `.xls` nor `.csv` (400).
- **Writing a range changes only its cells**: formatting, other sheets, formulas
  elsewhere and the file's history stay — unlike re-uploading the file. It works
  while the workbook is open in Excel (co-authoring), without a session.
- **`values` is a 2-D array** whose shape must be exactly the range's
  (`A2:B4` = 3 rows × 2 columns), or Graph refuses (400). A `None` cell is left
  unchanged; an empty string clears it; a string starting with `=` is a formula.
- **The used range** (`address=None`) is the rectangle from A1… to the last cell
  holding a value: the way to find a sheet's header row and its size.
- A sheet is named by its name or its id; a range by its A1 address on that sheet
  (`"B2:C17"`, `"D:D"`).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote

from ..common.credentials import require
from ._transport import GraphBase, segment
from .files import FilesClient, _odata_string

_RANGE_FIELDS = "address,rowCount,columnCount,values,text,numberFormat"


def _shape(values: Sequence[Sequence[Any]]) -> tuple:
    """(rows, columns) of a rectangular 2-D array, or `ValueError`."""
    if not values or not all(isinstance(r, (list, tuple)) for r in values):
        raise ValueError("values is a non-empty list of rows (a list of lists)")
    rows = [list(r) for r in values]
    widths = {len(r) for r in rows}
    if len(widths) != 1 or 0 in widths:
        raise ValueError("values must be rectangular: every row has the same number "
                         "of cells, at least one")
    return len(rows), widths.pop()


class WorkbookClient(GraphBase):
    """The cells of one person's Excel workbooks, on SharePoint and OneDrive."""

    @staticmethod
    def _workbook(drive_id: str, item_id: Optional[str], path: Optional[str]) -> str:
        return f"{FilesClient._item_path(drive_id, item_id, path)}/workbook"

    def _sheet(self, drive_id: str, sheet: str, item_id: Optional[str],
               path: Optional[str]) -> str:
        return (f"{self._workbook(drive_id, item_id, path)}/worksheets/"
                f"{segment(sheet, 'sheet')}")

    def list_worksheets(self, drive_id: str, *, item_id: Optional[str] = None,
                        path: Optional[str] = None) -> List[Dict[str, Any]]:
        """GET …/workbook/worksheets — `id`, `name`, `position`, `visibility`."""
        return (self._json("GET", f"{self._workbook(drive_id, item_id, path)}/worksheets")
                or {}).get("value") or []

    def get_range(self, drive_id: str, sheet: str, address: Optional[str] = None, *,
                  item_id: Optional[str] = None, path: Optional[str] = None
                  ) -> Dict[str, Any]:
        """GET …/worksheets/{sheet}/range(address='…') — or the sheet's used range
        when `address` is None: `address`, `rowCount`, `columnCount`, `values` (typed),
        `text` (as displayed), `numberFormat`."""
        base = self._sheet(drive_id, sheet, item_id, path)
        cible = (f"{base}/range(address='{quote(_odata_string(address), safe='')}')"
                 if address else f"{base}/usedRange(valuesOnly=true)")
        return self._json("GET", cible, params={"$select": _RANGE_FIELDS})

    def update_range(self, drive_id: str, sheet: str, address: str,
                     values: Sequence[Sequence[Any]], *, item_id: Optional[str] = None,
                     path: Optional[str] = None) -> Dict[str, Any]:
        """PATCH …/worksheets/{sheet}/range(address='…') `{values}` — only these cells
        change. `values` must be rectangular (checked here); its shape must match the
        range's (checked by Graph). Returns the range as written."""
        _shape(values)
        base = self._sheet(drive_id, sheet, item_id, path)
        return self._json(
            "PATCH",
            f"{base}/range(address='{quote(_odata_string(require(address, 'address')), safe='')}')",
            json={"values": [list(r) for r in values]})
