"""Les cas communs du coût (`connectors/_cases/cost.yaml`) joués côté Python, une ligne par cas.

Les cas sont lus par la fabrique (`fabrique.cases`), qui contrôle leurs fonctions comme une description et les convertit
dans la forme de `oto/connectors/declared.py` ; cette table remplace `DECLARED` le temps du test, et les fonctions pures
de `oto.connectors.cost` rendent ce que le fichier attend. Le paquet de l'hôte joue les mêmes cas, sortis par la même
fabrique dans `ts/src/cost-cases.ts`.
"""
from __future__ import annotations

import pytest
import yaml

from fabrique import cases as cost_cases
from fabrique.descriptions import DescriptionError
from oto.connectors import cost
from oto.connectors.cost import CostError, collection_of, settled_quantity, worst_case

LOADED = cost_cases.load()
CONNECTOR = LOADED.connector


@pytest.fixture(autouse=True)
def _declared(monkeypatch):
    monkeypatch.setattr(cost, "DECLARED", cost_cases.python_declared(LOADED))


def _outcome(expected, compute):
    if expected == cost_cases.ERROR:
        with pytest.raises(CostError):
            compute()
    else:
        assert compute() == expected


@pytest.mark.parametrize("case", LOADED.cases, ids=[case["name"] for case in LOADED.cases])
def test_cost_case(case):
    function = case["function"]["name"]
    _outcome(case["worst_case"], lambda: worst_case(CONNECTOR, function, case["args"]))
    _outcome(case["settled"], lambda: settled_quantity(CONNECTOR, function, case["args"], case["answers"]))
    _outcome(cost_cases.python_collection(CONNECTOR, case["collection"]),
             lambda: collection_of(CONNECTOR, function, case.get("submission")))


def test_the_cases_cover_the_format():
    """Chaque forme du coût et du travail asynchrone a au moins un cas."""
    functions = [case["function"] for case in LOADED.cases]
    costs = [f["cost"] for f in functions if "cost" in f]
    assert {c["per"] for c in costs} == {"request", "page", "item"}
    assert any("times" in c for c in costs) and any("weights" in c for c in costs)
    assert any("unit" in c for c in costs) and any("unit" not in c for c in costs)
    assert any("pagination" in f and "cost" in f for f in functions)
    jobs = [f["async"] for f in functions if "async" in f]
    assert any("within_s" in j for j in jobs) and any(j.get("no_deadline") for j in jobs)
    settled = [case["settled"] for case in LOADED.cases if isinstance(case["settled"], dict)]
    assert {s["from"] for s in settled} == {"response", "requests", "worst_case", "unreadable"}
    assert any(s["exceeded"] for s in settled)


def _write(tmp_path, mutate):
    data = yaml.safe_load(cost_cases.CASES.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "cost.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _case(data, name):
    return next(case for case in data["cases"] if case["name"] == name)


@pytest.mark.parametrize("mutate, message", [
    # Règle 12, comme pour une description : une liste comptée requise et non vide.
    (lambda d: _case(d, "item_without_times")["function"]["input"].update(required=[]), "must be a required list argument"),
    # Règle 13 : la relève est une autre lecture du connecteur.
    (lambda d: _case(d, "async_without_cost_nor_deadline")["collect"].update(name="get_other"), "is not another function"),
    (lambda d: _case(d, "request_declared_unit")["function"].update(name="get_record"), "differs from another of that name"),
    (lambda d: _case(d, "no_cost_not_async").update(collection={"function": "ping", "args": {"a": 1}}), "not asynchronous"),
    (lambda d: _case(d, "settle_zero").update(settled={"quantity": 0, "unit": "fields", "from": "read", "exceeded": False}),
     "does not match the cost cases form"),
], ids=["rule_12", "rule_13", "same_name", "collection_without_job", "unknown_from"])
def test_a_case_is_checked_like_a_description(tmp_path, mutate, message):
    with pytest.raises(DescriptionError, match=message):
        cost_cases.load(_write(tmp_path, mutate))
