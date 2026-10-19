"""FolkPacer and its use by FolkClient: per-key spacing shared across threads,
429 still retried after Retry-After."""

import json
import threading

import pytest

from oto.tools.folk import client as folk_client
from oto.tools.folk.client import FolkClient
from oto.tools.folk.pacing import DEFAULT_MIN_INTERVAL_S, FolkPacer, key_fingerprint


class _Clock:
    """Monotonic clock driven by the sleeps it is asked for."""

    def __init__(self):
        self.now = 0.0
        self.slept = []
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            return self.now

    def sleep(self, seconds):
        with self._lock:
            self.slept.append(seconds)


class _Resp:
    def __init__(self, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.content = json.dumps({"data": {}}).encode()

    def json(self):
        return {"data": {}}


class _Stub:
    def apply(self, x):
        return x


def test_default_interval_stays_under_folk_burst_policy():
    # Folk: 20 requests per 2 s, 600 per minute.
    assert 2 / DEFAULT_MIN_INTERVAL_S <= 20
    assert 60 / DEFAULT_MIN_INTERVAL_S <= 600


def test_sequential_starts_are_spaced():
    clock = _Clock()
    pacer = FolkPacer(clock=clock, sleep=clock.sleep)
    waits = [pacer.reserve("k", 0.125) for _ in range(4)]
    assert waits == [0.0, 0.125, 0.25, 0.375]


def test_time_passing_frees_the_next_start():
    clock = _Clock()
    pacer = FolkPacer(clock=clock, sleep=clock.sleep)
    assert pacer.reserve("k", 0.125) == 0.0
    clock.now = 1.0
    assert pacer.reserve("k", 0.125) == 0.0


def test_keys_are_paced_apart():
    clock = _Clock()
    pacer = FolkPacer(clock=clock, sleep=clock.sleep)
    assert pacer.reserve("a", 0.125) == 0.0
    assert pacer.reserve("b", 0.125) == 0.0
    assert pacer.reserve("a", 0.125) == 0.125


def test_zero_interval_never_waits_and_negative_is_refused():
    clock = _Clock()
    pacer = FolkPacer(clock=clock, sleep=clock.sleep)
    assert [pacer.reserve("k", 0) for _ in range(3)] == [0.0, 0.0, 0.0]
    with pytest.raises(ValueError):
        pacer.reserve("k", -1)
    with pytest.raises(ValueError):
        FolkClient(api_key="k", field_filter=_Stub(), min_interval_s=-0.1)


def test_threads_sharing_a_key_get_distinct_starts():
    clock = _Clock()
    pacer = FolkPacer(clock=clock, sleep=clock.sleep)
    n = 16
    start = threading.Barrier(n)
    waits = []
    lock = threading.Lock()

    def worker():
        start.wait()
        w = pacer.reserve("k", 0.125)
        with lock:
            waits.append(w)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(waits) == [i * 0.125 for i in range(n)]


def test_clients_built_per_call_share_the_pacing(monkeypatch):
    clock = _Clock()
    pacer = FolkPacer(clock=clock, sleep=clock.sleep)
    monkeypatch.setattr(folk_client.requests, "request",
                        lambda *a, **k: _Resp())
    for _ in range(3):
        FolkClient(api_key="k", field_filter=_Stub(), pacer=pacer).get_deal("g", "d")
    assert clock.slept == [0.125, 0.25]


def test_429_is_still_retried_and_the_retry_is_paced(monkeypatch):
    clock = _Clock()
    pacer = FolkPacer(clock=clock, sleep=clock.sleep)
    responses = [_Resp(429, {"Retry-After": "3"}), _Resp()]
    retry_sleeps = []
    monkeypatch.setattr(folk_client.requests, "request",
                        lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(folk_client.time, "sleep", retry_sleeps.append)
    c = FolkClient(api_key="k", field_filter=_Stub(), pacer=pacer)
    c.get_deal("g", "d")
    assert retry_sleeps == [3]
    assert responses == []
    assert clock.slept == [0.125]


def test_fingerprint_never_contains_the_key():
    assert "secret-key" not in key_fingerprint("secret-key")
