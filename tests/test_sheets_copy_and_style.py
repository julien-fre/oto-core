"""Copier un onglet et mettre en forme un tableur Google, sans recopie par le modèle.

Besoin : produire un fichier aussi mis en forme que le modèle d'un utilisateur
(colonnes grisées, largeurs, en-tête figé et renvoyé à la ligne, listes déroulantes),
alors que les données arrivent déjà côté serveur. Ce que ce fichier verrouille :

1. `copy_sheet` LIT la source (`sheets.copyTo` sur elle) et n'écrit que dans la
   destination — renommage et position compris ;
2. `format` ne pose QUE les champs donnés (masque exact), refuse une clé inconnue
   en nommant les bonnes, et une valeur mal formée avant tout appel ;
3. `column_width`, `freeze`, `dropdown` composent UNE requête `batchUpdate` exacte ;
4. `upload_bytes(convert=True)` convertit vers le type natif, et refuse un fichier
   sans équivalent natif au lieu de le déposer tel quel.
"""
from unittest.mock import MagicMock, patch

import pytest

from oto.tools.google.sheets.lib.sheets_client import SheetsClient, SheetsClientError


def _client(tabs=None):
    with patch("oto.tools.google.sheets.lib.sheets_client.build"):
        client = SheetsClient(credentials=object())
    client.sheets.get.return_value.execute.return_value = {
        "spreadsheetId": "sid", "properties": {"title": "T"},
        "sheets": [{"properties": {"sheetId": i, "title": t}}
                   for i, t in enumerate(tabs or ["Modèle"])]}
    return client, client.sheets.batchUpdate


def _requests(batch):
    return batch.call_args.kwargs["body"]["requests"]


# --- copier un onglet -----------------------------------------------------------------

def test_copy_sheet_lit_la_source_et_renomme_dans_la_destination():
    client, batch = _client(["Notes", "Modèle"])
    client.sheets.sheets.return_value.copyTo.return_value.execute.return_value = {
        "sheetId": 99, "title": "Copie de Modèle", "index": 3}
    out = client.copy_sheet("src", "Modèle", to_spreadsheet_id="dst", title="Octobre",
                            index=0)
    client.sheets.sheets.return_value.copyTo.assert_called_once_with(
        spreadsheetId="src", sheetId=1, body={"destinationSpreadsheetId": "dst"})
    assert batch.call_args.kwargs["spreadsheetId"] == "dst"
    assert _requests(batch) == [{"updateSheetProperties": {
        "properties": {"sheetId": 99, "title": "Octobre", "index": 0},
        "fields": "title,index"}}]
    assert out == {"spreadsheet_id": "dst", "id": 99, "title": "Octobre", "index": 0}


def test_copy_sheet_sans_titre_ni_position_ne_touche_pas_a_la_copie():
    client, batch = _client()
    client.sheets.sheets.return_value.copyTo.return_value.execute.return_value = {
        "sheetId": 5, "title": "Copie de Modèle", "index": 1}
    out = client.copy_sheet("sid", 0)
    batch.assert_not_called()
    assert out == {"spreadsheet_id": "sid", "id": 5, "title": "Copie de Modèle", "index": 1}


def test_copy_sheet_refuse_un_titre_vide_avant_la_copie():
    client, _ = _client()
    with pytest.raises(SheetsClientError, match="1 to 100"):
        client.copy_sheet("sid", 0, title=" ")
    client.sheets.sheets.return_value.copyTo.assert_not_called()


# --- style de cellule -------------------------------------------------------------------

def test_format_ne_pose_que_les_champs_donnes():
    client, batch = _client()
    client.format("sid", "'Modèle'!A1:AI1", {"background": "#d9d9d9", "bold": True,
                                              "wrap": True, "valign": "middle"})
    [req] = _requests(batch)
    cell = req["repeatCell"]
    assert cell["range"] == {"sheetId": 0, "startColumnIndex": 0, "startRowIndex": 0,
                             "endColumnIndex": 35, "endRowIndex": 1}
    fmt = cell["cell"]["userEnteredFormat"]
    assert fmt["backgroundColor"] == pytest.approx(
        {"red": 217 / 255, "green": 217 / 255, "blue": 217 / 255})
    assert fmt["textFormat"] == {"bold": True}
    assert fmt["wrapStrategy"] == "WRAP" and fmt["verticalAlignment"] == "MIDDLE"
    assert cell["fields"] == ("userEnteredFormat.backgroundColor,"
                              "userEnteredFormat.textFormat.bold,"
                              "userEnteredFormat.wrapStrategy,"
                              "userEnteredFormat.verticalAlignment")


@pytest.mark.parametrize("style, attendu", [
    ({"fond": "#fff"}, "unknown key"),
    ({}, "at least one"),
    ({"background": "gris"}, "#rrggbb"),
    ({"bold": "oui"}, "true or false"),
    ({"align": "justify"}, "left | center | right"),
    ({"font_size": 0}, "1 to 400"),
])
def test_un_style_mal_forme_est_refuse_avant_l_appel(style, attendu):
    client, batch = _client()
    with pytest.raises(SheetsClientError, match=attendu):
        client.format("sid", "A1", style)
    batch.assert_not_called()


# --- largeurs, volets figés, listes déroulantes -------------------------------------------

def test_column_width_pose_la_largeur_des_colonnes_de_la_plage():
    client, batch = _client()
    out = client.column_width("sid", "'Modèle'!B:D", 140)
    assert _requests(batch) == [{"updateDimensionProperties": {
        "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 4},
        "properties": {"pixelSize": 140}, "fields": "pixelSize"}}]
    assert out["columns"] == 3


def test_column_width_refuse_une_plage_sans_colonne():
    client, batch = _client()
    with pytest.raises(SheetsClientError, match="names no column"):
        client.column_width("sid", "'Modèle'!1:3", 100)
    batch.assert_not_called()


def test_freeze_ne_pose_que_ce_qui_est_donne():
    client, batch = _client()
    client.freeze("sid", "Modèle", rows=1)
    assert _requests(batch) == [{"updateSheetProperties": {
        "properties": {"sheetId": 0, "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount"}}]
    with pytest.raises(SheetsClientError, match="rows and/or cols"):
        client.freeze("sid", "Modèle")


def test_dropdown_pose_une_liste_stricte_et_une_liste_vide_la_retire():
    client, batch = _client()
    client.dropdown("sid", "'Modèle'!F2:F", ["À relancer", "Payé"])
    [req] = _requests(batch)
    rule = req["setDataValidation"]["rule"]
    assert rule["condition"] == {"type": "ONE_OF_LIST", "values": [
        {"userEnteredValue": "À relancer"}, {"userEnteredValue": "Payé"}]}
    assert rule["strict"] is True and rule["showCustomUi"] is True
    out = client.dropdown("sid", "'Modèle'!F2:F", [])
    assert "rule" not in _requests(batch)[0]["setDataValidation"]
    assert out["removed"] is True


# --- import Drive avec conversion ---------------------------------------------------------

def _drive():
    from oto.tools.google.drive.lib.drive_client import DriveClient
    client = DriveClient.__new__(DriveClient)
    client.service = MagicMock()
    client.service.files.return_value.create.return_value.execute.return_value = {
        "id": "f1", "name": "Suivi.xlsx", "mimeType": "application/vnd.google-apps.spreadsheet",
        "webViewLink": "https://docs.google.com/spreadsheets/d/f1"}
    return client


def test_upload_bytes_convertit_un_xlsx_en_google_sheets():
    client = _drive()
    out = client.upload_bytes(b"PK..", "Suivi.xlsx", "application/octet-stream",
                              folder_id="fold", convert=True)
    body = client.service.files.return_value.create.call_args.kwargs["body"]
    assert body == {"name": "Suivi.xlsx", "parents": ["fold"],
                    "mimeType": "application/vnd.google-apps.spreadsheet"}
    assert out["id"] == "f1" and out["converted"] is True


def test_upload_bytes_sans_conversion_depose_le_fichier_tel_quel():
    client = _drive()
    client.upload_bytes(b"%PDF", "note.pdf", "application/pdf")
    body = client.service.files.return_value.create.call_args.kwargs["body"]
    assert body == {"name": "note.pdf"}


def test_upload_bytes_refuse_de_convertir_ce_qui_n_a_pas_d_equivalent_natif():
    from oto.tools.google.drive.lib.drive_client import DriveClientError
    client = _drive()
    with pytest.raises(DriveClientError, match="no Google-native counterpart"):
        client.upload_bytes(b"%PDF", "note.pdf", "application/pdf", convert=True)
    client.service.files.return_value.create.assert_not_called()
