"""Compléter le tableur Google : structure, données, mise en forme avancée, graphiques.

Ce que ce fichier verrouille, requête `batchUpdate` par requête :

1. colonnes supprimées / lignes et colonnes insérées / masquées : bornes exactes
   (lettres → index 0, fin exclusive), et refus d'un bloc là où il faut des
   lignes ou des colonnes entières ;
2. tri, filtre, rechercher-remplacer : colonne de tri DANS la plage, formules
   jamais touchées par le remplacement, nombre d'occurrences rendu ;
3. bordures, fusion, règles conditionnelles : refus d'une condition au mauvais
   nombre de valeurs ou d'un style que Google n'admet pas en conditionnel ;
4. graphique : catégories = 1re colonne, une série par colonne suivante, un
   camembert à deux colonnes exactement ; ancrage par cellule ou onglet à part.
"""
from unittest.mock import patch

import pytest

from oto.tools.google.sheets.lib.sheets_client import SheetsClient, SheetsClientError


def _client(tabs=None, reply=None):
    with patch("oto.tools.google.sheets.lib.sheets_client.build"):
        client = SheetsClient(credentials=object())
    client.sheets.get.return_value.execute.return_value = {
        "spreadsheetId": "sid", "properties": {"title": "T"},
        "sheets": [{"properties": {"sheetId": i, "title": t}}
                   for i, t in enumerate(tabs or ["Suivi"])]}
    client.sheets.batchUpdate.return_value.execute.return_value = reply or {"replies": [{}]}
    return client, client.sheets.batchUpdate


def _requests(batch):
    return batch.call_args.kwargs["body"]["requests"]


# --- structure -----------------------------------------------------------------------

def test_delete_columns_c_a_e_supprime_trois_colonnes():
    client, batch = _client()
    out = client.delete_columns("sid", "Suivi", "C", "e")
    assert _requests(batch) == [{"deleteDimension": {"range": {
        "sheetId": 0, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 5}}}]
    assert out == {"id": 0, "deleted_columns": 3, "from_column": "C", "to_column": "E"}


@pytest.mark.parametrize("start, end", [("E", "C"), ("C3", "E"), ("", "C"), ("1", "2")])
def test_delete_columns_refuse_des_bornes_mal_formees(start, end):
    client, batch = _client()
    with pytest.raises(SheetsClientError):
        client.delete_columns("sid", "Suivi", start, end)
    batch.assert_not_called()


def test_insert_rows_avant_la_ligne_5_herite_du_format_du_dessus():
    client, batch = _client()
    out = client.insert_rows("sid", "Suivi", 5, 2)
    assert _requests(batch) == [{"insertDimension": {
        "range": {"sheetId": 0, "dimension": "ROWS", "startIndex": 4, "endIndex": 6},
        "inheritFromBefore": True}}]
    assert out["from_row"] == 5 and out["to_row"] == 6


def test_insert_columns_en_tete_n_herite_de_rien():
    client, batch = _client()
    out = client.insert_columns("sid", "Suivi", "A", 1)
    assert _requests(batch)[0]["insertDimension"]["inheritFromBefore"] is False
    assert out["from_column"] == out["to_column"] == "A"


@pytest.mark.parametrize("count", [0, -1, 10001])
def test_insert_refuse_un_nombre_hors_bornes(count):
    client, batch = _client()
    with pytest.raises(SheetsClientError, match="count"):
        client.insert_rows("sid", "Suivi", 2, count)
    batch.assert_not_called()


def test_set_hidden_colonnes_entieres():
    client, batch = _client()
    client.set_hidden("sid", "'Suivi'!C:E", True)
    assert _requests(batch) == [{"updateDimensionProperties": {
        "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 5},
        "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}}]


def test_set_hidden_lignes_entieres_puis_affichees():
    client, batch = _client()
    client.set_hidden("sid", "'Suivi'!5:9", False)
    req = _requests(batch)[0]["updateDimensionProperties"]
    assert req["range"] == {"sheetId": 0, "dimension": "ROWS", "startIndex": 4, "endIndex": 9}
    assert req["properties"] == {"hiddenByUser": False}


def test_set_hidden_refuse_un_bloc():
    client, batch = _client()
    with pytest.raises(SheetsClientError, match="whole rows"):
        client.set_hidden("sid", "'Suivi'!B2:C3", True)
    batch.assert_not_called()


def test_auto_fit_ajuste_les_colonnes_de_la_plage():
    client, batch = _client()
    client.auto_fit("sid", "'Suivi'!A:F")
    assert _requests(batch) == [{"autoResizeDimensions": {"dimensions": {
        "sheetId": 0, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 6}}}]


# --- données ---------------------------------------------------------------------------

def test_sort_par_deux_colonnes_dans_l_ordre():
    client, batch = _client()
    out = client.sort("sid", "'Suivi'!A2:F", [{"column": "C", "order": "desc"}, {"column": "A"}])
    req = _requests(batch)[0]["sortRange"]
    assert req["sortSpecs"] == [{"dimensionIndex": 2, "sortOrder": "DESCENDING"},
                                {"dimensionIndex": 0, "sortOrder": "ASCENDING"}]
    assert req["range"]["startRowIndex"] == 1
    assert out["sorted_by"] == [{"column": "C", "order": "desc"},
                                {"column": "A", "order": "asc"}]


@pytest.mark.parametrize("sort_by, motif", [
    ([], "sort_by"), ([{"column": "H"}], "outside"), ([{"col": "A"}], "sort_by"),
    ([{"column": "A", "order": "up"}], "order")])
def test_sort_refuse_avant_tout_appel(sort_by, motif):
    client, batch = _client()
    with pytest.raises(SheetsClientError, match=motif):
        client.sort("sid", "'Suivi'!A2:F", sort_by)
    batch.assert_not_called()


def test_set_filter_et_clear_filter():
    client, batch = _client()
    client.set_filter("sid", "'Suivi'!A1:F")
    assert "setBasicFilter" in _requests(batch)[0]
    client.clear_filter("sid", "Suivi")
    assert _requests(batch) == [{"clearBasicFilter": {"sheetId": 0}}]


def test_find_replace_dans_une_plage_ne_touche_pas_aux_formules():
    client, batch = _client(reply={"replies": [{"findReplace": {
        "occurrencesChanged": 4, "rowsChanged": 3, "sheetsChanged": 1}}]})
    out = client.find_replace("sid", "En cours", "Relancé", range="'Suivi'!D:D")
    req = _requests(batch)[0]["findReplace"]
    assert req["includeFormulas"] is False and "allSheets" not in req
    assert req["range"]["startColumnIndex"] == 3
    assert out == {"range": "'Suivi'!D:D", "occurrences": 4, "rows": 3, "tabs": 1}


def test_find_replace_sans_plage_vise_tous_les_onglets():
    client, batch = _client()
    out = client.find_replace("sid", "x", "y")
    assert _requests(batch)[0]["findReplace"]["allSheets"] is True
    assert out["occurrences"] == 0


def test_find_replace_refuse_un_texte_vide():
    client, batch = _client()
    with pytest.raises(SheetsClientError, match="find"):
        client.find_replace("sid", "", "y")
    batch.assert_not_called()


# --- mise en forme avancée -------------------------------------------------------------

def test_format_bordures_seules_n_envoie_pas_de_repeatcell():
    client, batch = _client()
    client.format("sid", "'Suivi'!A1:F10", {"borders": "outer", "border_color": "#999999"})
    reqs = _requests(batch)
    assert len(reqs) == 1 and set(reqs[0]["updateBorders"]) == {
        "range", "top", "bottom", "left", "right"}
    assert reqs[0]["updateBorders"]["top"]["style"] == "SOLID"


def test_format_style_et_bordures_en_une_requete():
    client, batch = _client()
    client.format("sid", "'Suivi'!A1:F1", {"bold": True, "borders": "all"})
    reqs = _requests(batch)
    assert [next(iter(r)) for r in reqs] == ["repeatCell", "updateBorders"]
    assert "innerVertical" in reqs[1]["updateBorders"]


@pytest.mark.parametrize("style, motif", [
    ({"borders": "dotted"}, "borders"), ({"border_color": "#000000"}, "goes with"),
    ({"borders": "all", "border_color": "red"}, "border_color"), ({"shadow": 1}, "unknown")])
def test_format_refuse_une_bordure_mal_formee(style, motif):
    client, batch = _client()
    with pytest.raises(SheetsClientError, match=motif):
        client.format("sid", "'Suivi'!A1:B2", style)
    batch.assert_not_called()


def test_merge_et_unmerge():
    client, batch = _client()
    client.merge("sid", "'Suivi'!A1:C1")
    assert _requests(batch)[0]["mergeCells"]["mergeType"] == "MERGE_ALL"
    client.unmerge("sid", "'Suivi'!A1:C1")
    assert "unmergeCells" in _requests(batch)[0]


def test_conditional_format_negatif_en_rouge_passe_en_tete():
    client, batch = _client()
    client.conditional_format("sid", "'Suivi'!E2:E", {
        "when": "number_less", "values": [0], "style": {"background": "#f4cccc", "bold": True}})
    req = _requests(batch)[0]["addConditionalFormatRule"]
    assert req["index"] == 0
    rule = req["rule"]["booleanRule"]
    assert rule["condition"] == {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]}
    assert rule["format"]["textFormat"] == {"bold": True}
    assert req["rule"]["ranges"][0]["startColumnIndex"] == 4


def test_conditional_format_sans_valeur_pour_vide():
    client, batch = _client()
    client.conditional_format("sid", "'Suivi'!B2:B", {"when": "blank", "style": {"color": "#ff0000"}})
    assert _requests(batch)[0]["addConditionalFormatRule"]["rule"]["booleanRule"][
        "condition"] == {"type": "BLANK"}


@pytest.mark.parametrize("rule, motif", [
    ({"when": "number_between", "values": [1], "style": {"bold": True}}, "2 value"),
    ({"when": "plus_grand", "values": [1], "style": {"bold": True}}, "rule.when"),
    ({"when": "blank", "style": {"font_size": 14}}, "not allowed"),
    ({"when": "blank", "style": {}}, "rule.style"),
    ({"when": "blank", "style": {"bold": True}, "range": "A1"}, "rule:")])
def test_conditional_format_refuse_avant_tout_appel(rule, motif):
    client, batch = _client()
    with pytest.raises(SheetsClientError, match=motif):
        client.conditional_format("sid", "'Suivi'!A:A", rule)
    batch.assert_not_called()


def test_clear_conditional_formats_retire_chaque_regle():
    client, batch = _client()
    client.sheets.get.return_value.execute.return_value = {"sheets": [
        {"properties": {"sheetId": 0, "title": "Suivi"}, "conditionalFormats": [{}, {}, {}]}]}
    out = client.clear_conditional_formats("sid", 0)
    assert _requests(batch) == [{"deleteConditionalFormatRule": {"sheetId": 0, "index": 0}}] * 3
    assert out == {"id": 0, "removed_rules": 3}


# --- graphiques ------------------------------------------------------------------------

def test_add_chart_colonnes_une_serie_par_colonne_a_cote_des_donnees():
    client, batch = _client(reply={"replies": [{"addChart": {"chart": {"chartId": 7}}}]})
    out = client.add_chart("sid", "'Suivi'!A1:C13", "column", title="Encaissements")
    chart = _requests(batch)[0]["addChart"]["chart"]
    basic = chart["spec"]["basicChart"]
    assert basic["chartType"] == "COLUMN" and basic["headerCount"] == 1
    assert basic["domains"][0]["domain"]["sourceRange"]["sources"][0]["startColumnIndex"] == 0
    assert [s["series"]["sourceRange"]["sources"][0]["startColumnIndex"]
            for s in basic["series"]] == [1, 2]
    assert chart["spec"]["title"] == "Encaissements"
    assert chart["position"] == {"overlayPosition": {"anchorCell": {
        "sheetId": 0, "rowIndex": 0, "columnIndex": 4}}}
    assert out == {"id": 7, "type": "column", "title": "Encaissements", "range": "'Suivi'!A1:C13"}


def test_add_chart_camembert_ancre_sur_un_autre_onglet():
    client, batch = _client(["Suivi", "Synthèse"],
                            reply={"replies": [{"addChart": {"chart": {"chartId": 8}}}]})
    client.add_chart("sid", "'Suivi'!A1:B6", "pie", anchor="'Synthèse'!H2")
    chart = _requests(batch)[0]["addChart"]["chart"]
    assert set(chart["spec"]["pieChart"]) == {"domain", "series", "legendPosition"}
    assert chart["position"]["overlayPosition"]["anchorCell"] == {
        "sheetId": 1, "rowIndex": 1, "columnIndex": 7}


def test_add_chart_sur_un_onglet_a_part():
    client, batch = _client(reply={"replies": [{"addChart": {"chart": {"chartId": 9}}}]})
    client.add_chart("sid", "'Suivi'!A1:B6", "line", new_sheet=True)
    assert _requests(batch)[0]["addChart"]["chart"]["position"] == {"newSheet": True}


@pytest.mark.parametrize("kwargs, motif", [
    ({"range": "'Suivi'!A1:A9"}, "two columns"),
    ({"range": "'Suivi'!A1:C9", "type": "pie"}, "exactly two"),
    ({"range": "'Suivi'!A1:B9", "type": "radar"}, "type"),
    ({"range": "'Suivi'!A1:B9", "anchor": "'Suivi'!H2", "new_sheet": True}, "not both"),
    ({"range": "'Suivi'!A1:B9", "anchor": "H2"}, "anchor"),
    ({"range": "'Suivi'!A1:B9", "anchor": "'Suivi'!H2:I3"}, "anchor")])
def test_add_chart_refuse_avant_tout_appel(kwargs, motif):
    client, batch = _client()
    with pytest.raises(SheetsClientError, match=motif):
        client.add_chart("sid", **kwargs)
    batch.assert_not_called()


def test_list_charts_rend_type_titre_et_onglet():
    client, _ = _client()
    client.sheets.get.return_value.execute.return_value = {"sheets": [
        {"properties": {"sheetId": 0, "title": "Suivi"}, "charts": [
            {"chartId": 7, "spec": {"title": "Encaissements", "basicChart": {"chartType": "COLUMN"}}},
            {"chartId": 8, "spec": {"pieChart": {"legendPosition": "RIGHT_LEGEND"}}}]},
        {"properties": {"sheetId": 1, "title": "Vide"}}]}
    assert client.list_charts("sid") == [
        {"id": 7, "title": "Encaissements", "type": "column", "sheet": "Suivi"},
        {"id": 8, "title": "", "type": "pie", "sheet": "Suivi"}]


def test_delete_chart():
    client, batch = _client()
    assert client.delete_chart("sid", "7") == {"id": 7, "deleted": True}
    assert _requests(batch) == [{"deleteEmbeddedObject": {"objectId": 7}}]


# --- remplir une plage -----------------------------------------------------------------

def test_fill_constante_en_une_requete():
    client, batch = _client()
    out = client.fill("sid", "'Suivi'!F2:F120", "À relancer")
    assert _requests(batch) == [{"repeatCell": {
        "range": {"sheetId": 0, "startRowIndex": 1, "endRowIndex": 120,
                  "startColumnIndex": 5, "endColumnIndex": 6},
        "cell": {"userEnteredValue": {"stringValue": "À relancer"}},
        "fields": "userEnteredValue"}}]
    assert out == {"range": "'Suivi'!F2:F120", "cells": 119, "formula": False}


@pytest.mark.parametrize("value, typed", [
    (0, {"numberValue": 0}), (1.5, {"numberValue": 1.5}), (True, {"boolValue": True})])
def test_fill_type_la_valeur(value, typed):
    client, batch = _client()
    client.fill("sid", "'Suivi'!A1:B2", value)
    assert _requests(batch)[0]["repeatCell"]["cell"] == {"userEnteredValue": typed}


def test_fill_formule_posee_en_tete_puis_recopiee():
    client, batch = _client()
    out = client.fill("sid", "'Suivi'!G2:G50", '=IF(C2>0;"Payé";"À relancer")')
    first, copy = _requests(batch)
    assert first["updateCells"]["range"] == {"sheetId": 0, "startRowIndex": 1, "endRowIndex": 2,
                                             "startColumnIndex": 6, "endColumnIndex": 7}
    assert first["updateCells"]["rows"] == [{"values": [{"userEnteredValue": {
        "formulaValue": '=IF(C2>0;"Payé";"À relancer")'}}]}]
    assert copy["copyPaste"]["source"] == first["updateCells"]["range"]
    assert copy["copyPaste"]["destination"]["endRowIndex"] == 50
    assert copy["copyPaste"]["pasteType"] == "PASTE_FORMULA"
    assert out["formula"] is True and out["cells"] == 49


@pytest.mark.parametrize("range_, value, motif", [
    ("'Suivi'!F2:F", "x", "bounded"), ("'Suivi'!F:F", "x", "bounded"),
    ("'Suivi'!F2:F9", None, "value"), ("'Suivi'!F2:F9", ["x"], "value")])
def test_fill_refuse_avant_tout_appel(range_, value, motif):
    client, batch = _client()
    with pytest.raises(SheetsClientError, match=motif):
        client.fill("sid", range_, value)
    batch.assert_not_called()
