"""Faux transport pour `oto.connectors.files` : un adaptateur `requests` monté sur une vraie `Session`.

Le client construit sa session et l'appel à l'API ; `file_output` lit la réponse, puis télécharge une adresse par la
session (sous `auth: account`) ou par une requête sans authentification. Le faux rejoue ces deux réponses sans réseau, en
passant par le vrai chemin de `requests` (préparation, en-têtes, lecture du corps en flux) ; il note chaque requête
téléchargée et les octets lus. Toute adresse résout vers une adresse publique, sauf une adresse IP littérale, rendue
telle quelle : la garde d'adresse (`oto.tools.common.url_guard`) s'exerce sans DNS.
"""
from __future__ import annotations

import io
import ipaddress
import json
import socket

import requests
from requests.adapters import HTTPAdapter
from urllib3.response import HTTPResponse

PUBLIC_ADDRESS = "93.184.216.34"
TOKEN = "Bearer test-token-of-the-account"


class CountingBody(io.BytesIO):
    """Un corps qui compte ce qu'on en lit."""

    def __init__(self, data: bytes):
        super().__init__(data)
        self.read_bytes = 0

    def read(self, size: int | None = -1) -> bytes:
        chunk = super().read(size)
        self.read_bytes += len(chunk)
        return chunk

    def read1(self, size: int = -1) -> bytes:
        return self.read(size)


def body_of(spec: dict) -> bytes:
    if "text" in spec:
        return spec["text"].encode("utf-8")
    if "json" in spec:
        return json.dumps(spec["json"]).encode("utf-8")
    return b""


def raw(spec: dict) -> HTTPResponse:
    return HTTPResponse(body=CountingBody(body_of(spec)), headers=spec["headers"], status=spec["status"],
                        preload_content=False, decode_content=False, enforce_content_length=False)


class FakeTransport(HTTPAdapter):
    """Rend `download` à toute requête, et la note ; sans `download`, rien ne doit partir."""

    def __init__(self, download: dict | None = None):
        super().__init__()
        self.download = download
        self.requests: list[tuple[requests.PreparedRequest, dict]] = []
        self.bodies: list[CountingBody] = []

    def send(self, request, **kwargs):
        self.requests.append((request, kwargs))
        if self.download is None:
            raise AssertionError("nothing should be downloaded")
        response_raw = raw(self.download)
        self.bodies.append(response_raw._fp)
        return self.build_response(request, response_raw)


def session(transport: FakeTransport) -> requests.Session:
    """La session d'un client : son authentification, le faux transport."""
    built = requests.Session()
    built.headers["Authorization"] = TOKEN
    built.mount("https://", transport)
    built.mount("http://", transport)
    return built


def answer(spec: dict, url: str = "https://api.example.test/v1/call") -> requests.Response:
    """La réponse de l'appel à l'API, telle que le client la reçoit (lue en flux)."""
    prepared = requests.Request("GET", url).prepare()
    return HTTPAdapter().build_response(prepared, raw(spec))


def resolve_publicly(host, port, *args, **kwargs):
    try:
        address = str(ipaddress.ip_address(host))
    except ValueError:
        address = PUBLIC_ADDRESS
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]
