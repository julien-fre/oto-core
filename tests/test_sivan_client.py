"""Contrat du client Sivan (External API, `X-Api-Key`, données RH en lecture seule).

Mocke `requests.Session.request` : en-tête d'auth, verbes POST et chemins
`/api/external/*`, corps JSON (noms camelCase de l'API), bornes (période ≤ 31 j,
ordre des dates), énumérations de statuts, ids entiers, re-tentatives sur 429 —
et la clé jamais lue de l'environnement.
"""
from __future__ import annotations

import pytest

from oto.tools.sivan import client as sv
from oto.tools.common.errors import UpstreamHTTPError


class _Resp:
    def __init__(self, status_code: int = 200, body=None, text=None):
        self.status_code = status_code
        self._body = body if body is not None else []
        self.content = b"x"
        self.text = text if text is not None else str(self._body)
        self.headers = {}

    def json(self):
        return self._body


@pytest.fixture()
def capture(monkeypatch):
    seen = {"calls": [], "responses": []}

    def fake_request(self, method, url, **kwargs):
        seen.update(method=method, url=url, kwargs=kwargs,
                    headers=dict(self.headers))
        seen["calls"].append((method, url))
        if seen["responses"]:
            return seen["responses"].pop(0)
        return _Resp(200)

    monkeypatch.setattr(sv.requests.Session, "request", fake_request)
    monkeypatch.setattr(sv.time, "sleep", lambda _s: None)
    return seen


@pytest.fixture()
def cli():
    return sv.SivanClient(api_key="siv_test")


BASE = "https://api2.sivan.io/api/external"


# --- auth, sonde ------------------------------------------------------------

def test_auth_header_is_x_api_key(capture, cli):
    cli.probe()
    assert capture["headers"]["X-Api-Key"] == "siv_test"
    assert "Authorization" not in capture["headers"]
    assert capture["calls"] == [("POST", f"{BASE}/companies")]
    assert capture["kwargs"]["json"] == {}


def test_missing_key_is_named_never_read_from_env(monkeypatch):
    """The library never reads secrets: an absent key is a named refusal."""
    from oto.tools.common.credentials import MissingCredential
    monkeypatch.setenv("SIVAN_API_KEY", "siv_env")
    with pytest.raises(MissingCredential, match="SIVAN_API_KEY"):
        sv.SivanClient()


# --- bodies & mapping -------------------------------------------------------

def test_list_salaries_maps_counter_flags(capture, cli):
    cli.list_salaries(with_counter=True)
    assert capture["calls"] == [("POST", f"{BASE}/salaries")]
    # `None` flags are dropped; only the set one is sent.
    assert capture["kwargs"]["json"] == {"withCounter": True}


def test_list_events_maps_body_to_camel_case(capture, cli):
    cli.list_events("2026-01-01", "2026-01-31", with_absence_type=True,
                    companies_ids=[1575], salaries_ids=[10, 11])
    assert capture["calls"] == [("POST", f"{BASE}/events")]
    assert capture["kwargs"]["json"] == {
        "start": "2026-01-01", "end": "2026-01-31",
        "withAbsenceType": True, "companiesIds": [1575],
        "salariesIds": [10, 11]}


def test_list_events_drops_empty_filters(capture, cli):
    cli.list_events("2026-01-01", "2026-01-31")
    assert capture["kwargs"]["json"] == {"start": "2026-01-01", "end": "2026-01-31"}


def test_list_absences_has_no_period_cap_and_maps_status(capture, cli):
    # 90 days: absences carry no 31-day cap.
    cli.list_absences("2026-01-01", "2026-03-31", status=["ACCEPTED"])
    assert capture["calls"] == [("POST", f"{BASE}/absences")]
    assert capture["kwargs"]["json"] == {
        "start": "2026-01-01", "end": "2026-03-31", "status": ["ACCEPTED"]}


def test_list_timesheets_maps_salaries(capture, cli):
    cli.list_timesheets("2026-01-01", "2026-01-31", salaries_ids=[42])
    assert capture["calls"] == [("POST", f"{BASE}/timesheets")]
    assert capture["kwargs"]["json"] == {
        "start": "2026-01-01", "end": "2026-01-31", "salariesIds": [42]}


def test_list_badged_events_path(capture, cli):
    cli.list_badged_events("2026-01-01", "2026-01-10")
    assert capture["calls"] == [("POST", f"{BASE}/badged-events")]


def _timesheet_with_days():
    return [{
        "salary": {"id": 42, "name": "x"},
        "weeks": [{
            "weekNumber": "40", "year": "2026",
            "workingTime": 144000, "accountedWorkingTime": 140400,
            "days": [{"date": "2026-10-05", "workingTime": 28800,
                      "eventsPlanned": [], "eventsDone": []}],
        }],
    }]


def test_summary_strips_days_keeps_weekly_totals(capture, cli):
    capture["responses"] = [_Resp(200, body=_timesheet_with_days())]
    out = cli.list_timesheets_summary("2026-10-01", "2026-10-31")
    week = out[0]["weeks"][0]
    assert "days" not in week
    assert week["workingTime"] == 144000 and week["accountedWorkingTime"] == 140400
    assert capture["calls"] == [("POST", f"{BASE}/timesheets")]


def test_list_timesheets_keeps_days(capture, cli):
    capture["responses"] = [_Resp(200, body=_timesheet_with_days())]
    out = cli.list_timesheets("2026-10-01", "2026-10-31")
    assert "days" in out[0]["weeks"][0]


# --- validation -------------------------------------------------------------

def test_period_over_31_days_is_refused(cli):
    with pytest.raises(ValueError, match="31 days"):
        cli.list_events("2026-01-01", "2026-03-01")


def test_end_before_start_is_refused(cli):
    with pytest.raises(ValueError, match="before"):
        cli.list_timesheets("2026-02-01", "2026-01-01")


def test_bad_date_is_refused(cli):
    with pytest.raises(ValueError, match="ISO-8601"):
        cli.list_events("not-a-date", "2026-01-31")


def test_unknown_absence_status_is_refused(cli):
    with pytest.raises(ValueError, match="status"):
        cli.list_absences("2026-01-01", "2026-01-31", status=["MAYBE"])


def test_non_integer_id_is_refused(cli):
    with pytest.raises(ValueError, match="integer"):
        cli.list_events("2026-01-01", "2026-01-31", salaries_ids=["10"])


# --- transport --------------------------------------------------------------

def test_upstream_error_is_raised_with_service(capture, cli):
    capture["responses"] = [_Resp(401, body={"error": "Invalid API key"})]
    with pytest.raises(UpstreamHTTPError) as exc:
        cli.list_companies()
    assert exc.value.status_code == 401
    assert exc.value.service == "sivan"


def test_429_is_retried_then_succeeds(capture, cli):
    capture["responses"] = [_Resp(429), _Resp(200, body=[{"id": 1}])]
    out = cli.list_companies()
    assert out == [{"id": 1}]
    assert len(capture["calls"]) == 2
