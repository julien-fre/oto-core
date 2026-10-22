"""Les cas communs de la fonction longue (`connectors/_cases/background.yaml`), joués côté Python, une ligne par cas.

La lib n'exécute aucune fonction en tâche de fond : son client ignore `background` et appelle en synchrone. Les cas se
jouent donc ici contre la fabrique (règle 21) ; le paquet de l'hôte joue les mêmes, sortis dans
`ts/src/background-cases.ts`, contre `registerConnectors`.
"""
from __future__ import annotations

import copy
import re

import pytest

from fabrique import background_cases, python
from fabrique.descriptions import BACKGROUND_REFUSALS, Description, DescriptionError, background_refusal, check_rules

LOADED = background_cases.load()
WHERE = "connectors/_cases/background.yaml"


@pytest.mark.parametrize("accepted", LOADED.accepted, ids=[accepted["name"] for accepted in LOADED.accepted])
def test_accepted_function_is_long_with_its_own_timeout(accepted):
    function = accepted["function"]
    assert function["background"] is True and "timeout_s" in function
    assert background_refusal(function, LOADED.description.data["functions"]) is None
    check_rules(background_cases.alone(LOADED, [function]), WHERE)


@pytest.mark.parametrize("refused", LOADED.refused, ids=[refused["name"] for refused in LOADED.refused])
def test_refused_function_is_refused_by_rule_21(refused):
    functions = background_cases.refused_functions(refused)
    expected = f"function {refused['function']['name']}: background: {refused['refusal']}: "
    with pytest.raises(DescriptionError, match=re.escape(expected)):
        check_rules(background_cases.alone(LOADED, functions), WHERE)
    assert background_refusal(refused["function"], functions)[0] == refused["refusal"]


@pytest.mark.parametrize("refused", LOADED.refused, ids=[refused["name"] for refused in LOADED.refused])
def test_refused_function_is_accepted_without_background(refused):
    function = {key: value for key, value in refused["function"].items() if key != "background"}
    check_rules(background_cases.alone(LOADED, [function, *refused["beside"]]), WHERE)


def test_every_refusal_has_a_refused_function():
    assert {refused["refusal"] for refused in LOADED.refused} == set(BACKGROUND_REFUSALS)
    assert BACKGROUND_REFUSALS == ("background_no_timeout", "background_async", "background_collect",
                                   "background_paginated")


def test_a_function_without_background_is_not_judged_by_rule_21():
    function = copy.deepcopy(LOADED.refused[0]["function"])
    function.pop("background")
    assert background_refusal(function, [function]) is None


def test_a_refused_case_must_be_refused_by_rule_21_alone(tmp_path):
    """Un cas refusé qu'une autre règle refuse aussi sans `background` est refusé par la fabrique, qui le dit."""
    text = background_cases.CASES.read_text(encoding="utf-8")
    broken = text.replace("    beside: [*get_job]\n    refusal: background_async", "    beside: []\n    refusal: background_async")
    assert broken != text
    path = tmp_path / "background.yaml"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(DescriptionError, match="is refused without background, by another rule than 21"):
        background_cases.load(path)


def test_the_python_table_carries_no_background():
    """Le client Python appelle une fonction longue en synchrone : la table générée n'en dit rien."""
    table = python.declared([Description(path=LOADED.description.path, data=LOADED.description.data)])
    entries = [entry for functions in table.values() for entry in functions.values()]
    assert entries and all("background" not in entry for entry in entries)


def test_typescript_carries_background_after_the_timeout():
    source = background_cases.typescript_source(LOADED)
    assert "  timeoutMs: 300000,\n  background: true,\n" in source
    assert source.count("  background: true,\n") == len(LOADED.accepted) + len(LOADED.refused)
    assert "export const refusedCollectOfAnAsynchronousJobBesideSubmitJob = defineFunction({" in source
    assert "export const backgroundRefusedFunctions: readonly BackgroundRefusedFunction[]" in source
