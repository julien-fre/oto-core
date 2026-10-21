"""Les cas communs du fichier rendu (`connectors/_cases/file.yaml`) joués côté Python, une ligne par cas.

Les cas sont lus par la fabrique (`fabrique.file_cases`), qui contrôle leurs fonctions comme une description et les
convertit dans la forme de `oto/connectors/declared.py` ; cette table remplace `DECLARED` le temps du test, et
`oto.connectors.files.file_output` rend, sur un faux transport, le fichier ou le refus que le fichier attend. Le paquet
de l'hôte joue les mêmes cas, sortis par la même fabrique dans `ts/src/file-cases.ts`, avec un faux `fetch`.
"""
from __future__ import annotations

import logging

import pytest

import files_fake
from fabrique import file_cases
from oto.connectors import files
from oto.connectors.files import FileOutputError, file_output
from oto.tools.common import url_guard

LOADED = file_cases.load()
CONNECTOR = LOADED.connector
BASE_URL = LOADED.description.data["connector"]["base_url"]


@pytest.fixture(autouse=True)
def _declared_and_resolver(monkeypatch):
    monkeypatch.setattr(files, "DECLARED", file_cases.python_declared(LOADED))
    monkeypatch.setattr(url_guard.socket, "getaddrinfo", files_fake.resolve_publicly)


def _addresses(value) -> list[str]:
    """Chaque adresse que porte une réponse JSON : aucune ne doit sortir."""
    if isinstance(value, dict):
        return [a for v in value.values() for a in _addresses(v)]
    if isinstance(value, list):
        return [a for v in value for a in _addresses(v)]
    return [value] if isinstance(value, str) and "://" in value else []


def _play(case):
    transport = files_fake.FakeTransport(case.get("download"))
    result = file_output(CONNECTOR, case["function"]["name"], answer=files_fake.answer(case["answer"]), args=case["args"],
                         session=files_fake.session(transport), base_url=BASE_URL)
    return result, transport


@pytest.mark.parametrize("case", LOADED.cases, ids=[case["name"] for case in LOADED.cases])
def test_file_case(case, caplog):
    caplog.set_level(logging.DEBUG)
    if "refusal" in case:
        with pytest.raises(FileOutputError) as raised:
            _play(case)
        error = raised.value
        assert error.code == case["refusal"]
        assert error.__cause__ is None and error.__context__ is None
        for address in _addresses(case["answer"].get("json")):
            assert address not in str(error) and address not in repr(error.args)
    else:
        result, transport = _play(case)
        assert {"name": result.name, "mime": result.mime, "size": len(result.content)} == case["file"]
        source = case["function"]["output"]["file"]["from"]
        if source in ("body", "url"):
            assert result.content == files_fake.body_of(case["answer"] if source == "body" else case["download"])
    for address in _addresses(case["answer"].get("json")):
        assert all(address not in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("case", [c for c in LOADED.cases if "download" not in c and c["function"]["output"]["file"]["from"] == "url"],
                         ids=lambda c: c["name"])
def test_an_address_refused_before_the_download_is_never_downloaded(case):
    transport = files_fake.FakeTransport(None)
    with pytest.raises(FileOutputError):
        file_output(CONNECTOR, case["function"]["name"], answer=files_fake.answer(case["answer"]), args=case["args"],
                    session=files_fake.session(transport), base_url=BASE_URL)
    assert transport.requests == []
