"""Minimal Firebase Realtime Database WebSocket client.

⚠️ **The WebSocket is not an optimisation — it is the only transport that works
here.** There is no simpler one to fall back to: do not "simplify" this module by
rewriting it over plain HTTP.

The database is sharded across three families (master, per-business, per-calendar):
the classmethods below build each one, and `calendar_shard_index` computes the
calendar one rather than looking it up.

Large messages arrive multi-frame, in two variants — both handled by `_recv_raw`.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

import websockets


def calendar_shard_index(calendar_id: str) -> int:
    """Planity's hash function for calendar shards (returns 1..4)."""
    return sum(ord(c) for c in calendar_id) % 4 + 1


class FirebaseRTDB:
    """One connection to one Firebase RTDB namespace."""

    def __init__(self, host: str, namespace: str, id_token: str, app_id: str):
        self.host = host
        self.namespace = namespace
        self.id_token = id_token
        # App ID Firebase de Planity — fourni par l'appelant, jamais en dur ici
        # (cf. `config.PlanityEndpoints`). Il part en `p=` dans la poignée de main.
        self.app_id = app_id
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._req_id = 0

    @classmethod
    def master(cls, id_token: str, app_id: str) -> "FirebaseRTDB":
        return cls("planity-production.firebaseio.com", "planity-production",
                   id_token, app_id)

    @classmethod
    def business_shard(cls, shard_name: str, id_token: str,
                       app_id: str) -> "FirebaseRTDB":
        host = f"planity-production-{shard_name}.europe-west1.firebasedatabase.app"
        ns = f"planity-production-{shard_name}"
        return cls(host, ns, id_token, app_id)

    @classmethod
    def calendars_shard(cls, calendar_id: str, id_token: str,
                        app_id: str) -> "FirebaseRTDB":
        idx = calendar_shard_index(calendar_id)
        host = f"planity-production-calendars-{idx}.firebaseio.com"
        ns = f"planity-production-calendars-{idx}"
        return cls(host, ns, id_token, app_id)

    async def connect(self):
        uri = f"wss://{self.host}/.ws?v=5&p={self.app_id}&ns={self.namespace}"
        # Bornes explicites sur l'ouverture et la fermeture : un WebSocket qui
        # attend un tiers sans délai maximal à SON niveau tient l'appelant
        # indéfiniment, même quand les enveloppes au-dessus croient l'avoir borné.
        self.ws = await websockets.connect(uri, max_size=32 * 1024 * 1024,
                                           open_timeout=15, close_timeout=5)
        # Swallow handshake (control msg)
        await self._recv_raw(timeout=10)
        # Authenticate
        await self._send_action("auth", {"cred": self.id_token})
        auth_reply = await self._recv_until_reply(self._req_id, timeout=10)
        if auth_reply.get("s") != "ok":
            raise RuntimeError(f"Firebase auth failed: {auth_reply}")

    async def close(self):
        if self.ws:
            await self.ws.close()
            self.ws = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    # ─────────────────────── wire protocol ───────────────────────

    async def _recv_raw(self, timeout: float = 5.0) -> Optional[dict]:
        """Receive one logical message (handles Firebase's two multi-frame formats).

        Format A: '<count>\\n<first_part>' then (count-1) follow-up frames.
        Format B: '<count>' alone, then `count` follow-up frames.
        """
        first = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
        # Multi-frame detection
        if first and first[:1].isdigit():
            if "\n" in first[:10]:
                # Format A
                count_str, _, rest = first.partition("\n")
                try:
                    count = int(count_str)
                    parts = [rest] if rest else []
                    while len(parts) < count:
                        parts.append(await asyncio.wait_for(self.ws.recv(), timeout=timeout))
                    first = "".join(parts)
                except ValueError:
                    pass
            elif first.isdigit():
                # Format B: the whole frame is just the count
                try:
                    count = int(first)
                    parts: list[str] = []
                    while len(parts) < count:
                        parts.append(await asyncio.wait_for(self.ws.recv(), timeout=timeout))
                    first = "".join(parts)
                except ValueError:
                    pass
        try:
            return json.loads(first)
        except (ValueError, TypeError):
            # Une trame qui n'est pas du JSON n'est PAS un échec : le protocole
            # mêle des trames de contrôle aux trames de données, et l'appelant
            # (`_recv_until_reply`) ignore ce qui n'est pas un dict et continue
            # d'attendre SA réponse — jusqu'à son propre délai maximal, qui est
            # ce qui tranche pour de bon.
            return None

    async def _send_action(self, action: str, body: dict) -> int:
        """Send a data frame. Returns req_id."""
        self._req_id += 1
        rid = self._req_id
        frame = {"t": "d", "d": {"r": rid, "a": action, "b": body}}
        await self.ws.send(json.dumps(frame))
        return rid

    async def _recv_until_reply(
        self,
        rid: int,
        timeout: float = 10.0,
        data_collector: Optional[dict] = None,
    ) -> dict:
        """Receive frames until we get the reply for rid.

        If data_collector is passed, intermediate data-push frames matching its
        'path' key are stored in data_collector['value'].
        """
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError(f"No reply for req {rid}")
            msg = await self._recv_raw(timeout=remaining)
            if not isinstance(msg, dict):
                continue
            d = msg.get("d")
            if not isinstance(d, dict):
                continue
            if d.get("a") == "d" and data_collector is not None:
                b = d.get("b", {})
                if isinstance(b, dict) and b.get("p") == data_collector.get("path"):
                    data_collector["value"] = b.get("d")
            if d.get("r") == rid:
                return d.get("b", {}) or {}

    # ─────────────────────── public API ───────────────────────

    async def get(self, path: str, query: Optional[dict] = None) -> Any:
        """Read a path once. Returns the value, or None when it holds nothing.

        ⚠️ It opens a listen and does NOT close it — the connection is short-lived
        and dropped with the client, which is why that costs nothing here. The
        docstring claimed "listen + unlisten" until 2026-09-09; there was no
        unlisten, and no caller ever missed it.

        Raises RuntimeError with the upstream status on failure.
        """
        collector: dict = {"path": path, "value": None}
        body: dict = {"p": path, "h": ""}
        if query:
            body["q"] = query
        rid = await self._send_action("q", body)
        reply = await self._recv_until_reply(rid, data_collector=collector)
        status = reply.get("s")
        if status != "ok":
            raise RuntimeError(f"Firebase '{path}' failed: {status} / {reply.get('d')}")
        # Data usually arrives via a data-push frame before the ack; fall back to
        # the reply body if nothing was pushed (e.g. empty/null value).
        if collector["value"] is not None:
            return collector["value"]
        return reply.get("d")
