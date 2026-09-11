"""Faux serveur de l'API admin HelloStock — rejoue le contrat OpenAPI `1.0.0`.

Un vrai serveur HTTP local (stdlib), pour que le banc exerce le transport réel du
client — en-têtes, encodage de la query string, corps JSON, redirections — et non un
`Session.request` remplacé. Il rejoue ce que le contrat promet, et seulement ça :

- 401 pour un jeton inconnu, 403 pour le jeton d'un compte non administrateur ;
- des filtres validés strictement : une valeur hors référentiel, une date mal formée
  ou une limite hors [1, 200] répondent 400 `{"error": …}`, jamais une liste vide ;
- la pagination `{items, nextCursor, total}` : demandes et offres par id décroissant,
  membres et positionnements par id croissant, `nextCursor` nul en dernière page ;
- les écritures : `PATCH` de statut, `PATCH` d'offre (au moins un champ, aucun champ
  inconnu, mots-clés bornés et refusés en bloc s'ils portent une identité), et
  l'envoi d'une demande (1 à 50 destinataires, message ≤ 2 000 caractères).

Là où le contrat se tait ou se trompe, le faux suit le serveur réel plutôt que
d'inventer : un paramètre de query au nom inconnu est IGNORÉ (le contrat promet
qu'aucun filtre ne l'est), un `PATCH` de demande sur un identifiant inconnu rend une
500 (le contrat ne déclare aucun 404 à cet endroit), et l'envoi rend UN seul message
pour tout échec de schéma, message trop long compris.
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ADMIN_TOKEN = "hs_admin_test"
MEMBER_TOKEN = "hs_member_test"

STATUSES = ("declared", "qualified", "published", "closed")
MATIERES = ("acier", "inox", "aluminium", "cuivre", "laiton", "autre")
CERTIFICATS = ("dispo", "verifie", "sans-mots-cles")
SECTORS = ("tolerie_chaudronnerie", "usinage_mecanique", "decoupe_service",
           "negoce_metaux", "recyclage_ferraille", "fonderie",
           "construction_metallique", "industrie_fabricant", "autre")
SERVICES = ("decoupe_laser", "pliage", "soudure")

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$")
_DEPT = re.compile(r"^(0[1-9]|[1-8]\d|9[0-5]|2A|2B|97[1-6])$")
_IDENTITE = re.compile(r"coul[ée]e|commande|acierie", re.I)


class _Bad(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _entreprise(i: int) -> dict:
    return {"id": f"e{i}", "name": f"Entreprise {i}", "publicRef": i,
            "sector": SECTORS[i % len(SECTORS)], "postalCode": f"{69 + i % 3}000",
            "city": "Ville", "departement": f"{69 + i % 3}"}


def _contact(i: int) -> dict:
    return {"userId": i, "name": f"Membre {i}", "email": f"m{i}@example.test",
            "company": f"Entreprise {i}", "phone": None, "location": None}


def _provenance() -> dict:
    return {"pageVariant": None, "utmSource": None, "utmMedium": None,
            "utmCampaign": None}


def seed() -> dict:
    """Une population déterministe, assez grande pour paginer (120 demandes)."""
    demandes = {}
    for i in range(1, 121):
        demandes[i] = {
            "id": i, "status": STATUSES[i % 4], "source": "form",
            "createdAt": f"2026-0{1 + i % 8}-{10 + i % 18:02d}T09:00:00.000Z",
            "matiere": MATIERES[i % 6], "nuance": "304L", "format": "tôle",
            "dimensions": "2000x1000", "epaisseur": "3", "quantite": "10",
            "delai": None, "reference": f"REF-{i}", "certificatRequis": bool(i % 2),
            "fichiers": [], "services": [SERVICES[i % 3]], "customServices": [],
            "commentaire": "x" * (i % 7), "contact": _contact(i),
            "entreprise": _entreprise(i), "nbPositionnements": 0, "nbEnvois": 0,
            "provenance": _provenance(), "data": {"champ": "valeur"},
        }
    offres = {}
    for i in range(1, 31):
        offres[i] = {
            "id": i, "status": STATUSES[i % 4], "source": "form",
            "createdAt": f"2026-08-{i:02d}T09:00:00.000Z", "matiere": MATIERES[i % 6],
            "nuance": "316L", "format": "barre", "dimensions": "ø20",
            "epaisseur": None, "quantite": "5", "etat": "neuf",
            "prixIndicatif": None, "photos": [], "commentaire": None,
            "keywords": [] if i % 3 == 0 else ["316l"], "departement": "69",
            "certificat": {"dispo": True, "joint": i % 3 == 0, "url": None,
                           "verdict": None, "verdictAt": None,
                           "verdictObsolete": False},
            "contact": _contact(i), "entreprise": _entreprise(i), "nbThreads": 0,
            "provenance": _provenance(), "data": None,
        }
    users = {}
    for i in range(1, 61):
        users[i] = {
            "id": i, "name": f"Membre {i}", "email": f"m{i}@example.test",
            "phone": None, "isAdmin": i == 1, "createdAt": "2026-01-01T00:00:00.000Z",
            "lastLoginAt": None, "company": f"Entreprise {i}",
            "sector": SECTORS[i % len(SECTORS)], "location": "69000 Ville",
            "companyRole": "owner", "entreprise": _entreprise(i),
            "services": [SERVICES[i % 3]], "customServices": [],
            "nbOffres": i % 2, "nbDemandes": (i + 1) % 2, "nbPositionnements": 0,
        }
    positionnements = {}
    for i in range(1, 8):
        positionnements[i] = {
            "id": f"cpos{i:04d}", "demandeId": 1 + i % 2, "status": "open",
            "message": "Nous pouvons livrer.", "createdAt": "2026-08-01T00:00:00.000Z",
            "devisUrl": None,
            "seller": {"id": i, "name": f"Membre {i}", "email": f"m{i}@example.test",
                       "company": f"Entreprise {i}", "phone": None},
            "entreprise": _entreprise(i),
        }
    return {"demandes": demandes, "offres": offres, "users": users,
            "positionnements": positionnements, "envois": []}


class FakeHelloStock:
    """Démarre un serveur sur 127.0.0.1:<port libre> ; `requests_log` garde chaque
    requête reçue (méthode, chemin, query, en-têtes, corps)."""

    def __init__(self):
        self.db = seed()
        self.requests_log: list[dict] = []
        self.force: dict[str, tuple[int, object, dict]] = {}
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence du serveur de test
                return

            def _serve(self, method: str):
                parts = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                entry = {"method": method, "path": parts.path,
                         "query": parse_qs(parts.query, keep_blank_values=True),
                         "headers": dict(self.headers), "body": raw}
                fake.requests_log.append(entry)
                status, payload, headers = fake.dispatch(entry)
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                if isinstance(payload, (bytes, str)):
                    data = payload.encode() if isinstance(payload, str) else payload
                else:
                    data = json.dumps(payload).encode()
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._serve("GET")

            def do_PATCH(self):
                self._serve("PATCH")

            def do_POST(self):
                self._serve("POST")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)

    def start(self) -> "FakeHelloStock":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    # --- routage --------------------------------------------------------------

    def dispatch(self, req: dict) -> tuple[int, object, dict]:
        forced = self.force.get(req["path"])
        if forced:
            return forced
        auth = req["headers"].get("Authorization", "")
        if auth != f"Bearer {ADMIN_TOKEN}":
            if auth == f"Bearer {MEMBER_TOKEN}":
                return 403, {"error": "Forbidden"}, {}
            return 401, {"error": "Unauthorized"}, {}
        q = {k: v[-1] for k, v in req["query"].items()}
        path, method = req["path"], req["method"]
        try:
            m = re.fullmatch(r"/api/admin/(demandes|offres|users|positionnements)"
                             r"(?:/([^/]+))?(/envoyer)?", path)
            if not m:
                raise _Bad(404, "Route inconnue")
            kind, ident, envoyer = m.groups()
            if ident is None and method == "GET":
                return 200, self._page(kind, q), {}
            if ident is None or kind == "positionnements":
                raise _Bad(404, "Route inconnue")
            if not ident.isdigit():
                raise _Bad(400, "Identifiant invalide")
            rec = self.db[kind].get(int(ident))
            if envoyer and method == "POST" and kind == "demandes":
                return 200, self._envoyer(rec, req["body"]), {}
            if method == "GET" and not envoyer:
                if rec is None:
                    raise _Bad(404, "Introuvable")
                return 200, self._detail(kind, rec), {}
            if method == "PATCH" and kind in ("demandes", "offres") and not envoyer:
                return 200, self._patch(kind, rec, req["body"]), {}
            raise _Bad(404, "Route inconnue")
        except _Bad as e:
            return e.status, {"error": str(e)}, {}

    # --- lectures -------------------------------------------------------------

    @staticmethod
    def _enum(q: dict, name: str, allowed) -> None:
        if name in q and q[name] not in allowed:
            raise _Bad(400, f"{name} invalide : {q[name]!r}")

    @staticmethod
    def _bool(q: dict, name: str):
        if name not in q:
            return None
        if q[name] not in ("true", "false"):
            raise _Bad(400, f"{name} doit valoir true ou false")
        return q[name] == "true"

    def _page(self, kind: str, q: dict) -> dict:
        limit = q.get("limit", "50")
        if not limit.isdigit() or not 1 <= int(limit) <= 200:
            raise _Bad(400, "limit doit être un entier entre 1 et 200")
        for name in ("since", "until"):
            if name in q and not _DATE.match(q[name]):
                raise _Bad(400, f"{name} : date mal formée")
        if "departement" in q and not _DEPT.match(q["departement"]):
            raise _Bad(400, "departement invalide")
        rows = list(self.db[kind].values())
        if kind in ("demandes", "offres"):
            self._enum(q, "status", STATUSES)
            self._enum(q, "matiere", MATIERES)
            if kind == "demandes":
                self._enum(q, "service", SERVICES)
            else:
                self._enum(q, "certificat", CERTIFICATS)
            for f in ("status", "matiere"):
                if f in q:
                    rows = [r for r in rows if r[f] == q[f]]
            if q.get("certificat") == "sans-mots-cles":
                rows = [r for r in rows if r["certificat"]["joint"] and not r["keywords"]]
            if "since" in q:
                rows = [r for r in rows if r["createdAt"] >= q["since"]]
            rows.sort(key=lambda r: -r["id"])
        elif kind == "users":
            self._enum(q, "sector", SECTORS)
            self._enum(q, "service", SERVICES)
            is_admin = self._bool(q, "isAdmin")
            self._bool(q, "hasOffres")
            self._bool(q, "hasDemandes")
            if is_admin is not None:
                rows = [r for r in rows if r["isAdmin"] == is_admin]
            if "sector" in q:
                rows = [r for r in rows if r["sector"] == q["sector"]]
            rows.sort(key=lambda r: r["id"])
        else:
            if "demandeId" in q:
                if not q["demandeId"].isdigit():
                    raise _Bad(400, "demandeId invalide")
                rows = [r for r in rows if r["demandeId"] == int(q["demandeId"])]
            rows.sort(key=lambda r: r["id"])
        total = len(rows)
        cursor = q.get("cursor")
        if cursor is not None:
            ids = [str(r["id"]) for r in rows]
            if cursor not in ids:
                raise _Bad(400, "cursor invalide")
            rows = rows[ids.index(cursor) + 1:]
        page = rows[:int(limit)]
        more = len(rows) > int(limit)
        return {"items": page, "nextCursor": str(page[-1]["id"]) if more else None,
                "total": total}

    def _detail(self, kind: str, rec: dict) -> dict:
        out = dict(rec)
        if kind == "demandes":
            out["positionnements"] = [p for p in self.db["positionnements"].values()
                                      if p["demandeId"] == rec["id"]]
            out["envois"] = [{k: v for k, v in e.items() if k != "demandeId"}
                             for e in reversed(self.db["envois"])
                             if e["demandeId"] == rec["id"]]
        if kind == "offres":
            out["certificat"] = dict(rec["certificat"], verdictDetail=None)
        if kind == "users":
            out.update(authMethod="password", emailVerified=True,
                       demandes=[], offres=[], threads=[])
        return out

    # --- écritures ------------------------------------------------------------

    @staticmethod
    def _json(body: bytes) -> dict:
        try:
            data = json.loads(body or b"null")
        except ValueError:
            raise _Bad(400, "Corps JSON illisible")
        if not isinstance(data, dict):
            raise _Bad(400, "Corps attendu : un objet JSON")
        return data

    def _patch(self, kind: str, rec, body: bytes) -> dict:
        data = self._json(body)
        if rec is None:
            # Le contrat ne déclare aucun 404 sur `PATCH /demandes/{id}` ; le serveur
            # réel rend une 500 non JSON. Une offre inconnue, elle, rend 404.
            if kind == "demandes":
                raise _Bad(500, "Internal Server Error")
            raise _Bad(404, "Offre introuvable")
        if kind == "demandes":
            if data.get("status") not in STATUSES:
                raise _Bad(400, "status invalide")
            rec["status"] = data["status"]
            return {"success": True}
        if not data:
            raise _Bad(400, "Au moins un champ : status ou keywords")
        extra = set(data) - {"status", "keywords"}
        if extra:
            raise _Bad(400, f"Champ inconnu : {sorted(extra)}")
        if "status" in data and data["status"] not in STATUSES:
            raise _Bad(400, "status invalide")
        if "keywords" in data:
            kw = data["keywords"]
            if (not isinstance(kw, list) or not 1 <= len(kw) <= 30
                    or any(not isinstance(k, str) or not 1 <= len(k) <= 60 for k in kw)):
                raise _Bad(400, "keywords : 1 à 30 termes de 1 à 60 caractères")
            bad = [k for k in kw if _IDENTITE.search(k)]
            if bad:
                raise _Bad(400, f"Mots-clés refusés, ils portent une identité : {bad}")
            rec["keywords"] = sorted({" ".join(k.split()).lower() for k in kw})
        if "status" in data:
            rec["status"] = data["status"]
        return {"success": True}

    def _envoyer(self, rec, body: bytes) -> dict:
        data = self._json(body)
        ids = data.get("userIds")
        message = data.get("message")
        # Un seul message pour TOUT échec de schéma, message trop long compris : c'est
        # ce que rend le serveur réel, et c'est pourquoi la face servie borne le
        # message elle-même avant d'appeler.
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 50
                or any(isinstance(u, bool) or not isinstance(u, int) or u < 1 for u in ids)
                or (message is not None
                    and (not isinstance(message, str) or len(message) > 2000))):
            raise _Bad(400, "Sélectionnez au moins un destinataire")
        if rec is None:
            raise _Bad(404, "Demande introuvable")
        ids = list(dict.fromkeys(ids))
        unknown = [u for u in ids if u not in self.db["users"]]
        if unknown:
            raise _Bad(400, "Destinataires inconnus : " + ", ".join(map(str, unknown)))
        for u in ids:
            user = self.db["users"][u]
            self.db["envois"].append({
                "id": f"env{len(self.db['envois']) + 1}", "demandeId": rec["id"],
                "userId": u, "sentById": 1, "message": message,
                "sentAt": "2026-09-11T10:00:00.000Z",
                "user": {"id": u, "name": user["name"], "email": user["email"],
                         "company": user["company"]},
                "sentBy": {"id": 1, "name": "Membre 1", "email": "m1@example.test"}})
        rec["nbEnvois"] += len(ids)
        return {"success": True, "envoyes": len(ids), "echecs": [], "noop": False}
