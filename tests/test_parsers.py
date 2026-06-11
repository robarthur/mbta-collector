"""Fixture tests for the MBTA payload parsers.

Fixtures are real API responses captured 2026-06-11 (see filenames). These pin the parsing
logic that has bitten us before (terminus vs through-station classification, the alerts
train-number join). NB: CPython passing does NOT cover Pyodide runtime quirks -- the
worker's vendored httpx leaves JSON null as a JsNull proxy and fills schedule
departure_time at termini (see notes in mbta.py); that's why classification uses
pickup_type and isinstance(str) checks, which these tests lock in.
"""

import json
from pathlib import Path

import mbta

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


# --- parse_station_board (predictions at a terminus) -------------------------------------

def test_station_board_shape_and_sort():
    rows = mbta.parse_station_board(load("predictions_north"))
    assert len(rows) == 5
    times = [r["predicted_time"] for r in rows]
    assert times == sorted(times)
    for r in rows:
        assert r["trip_id"] and r["route_id"]
        assert isinstance(r["predicted_time"], str)


def test_station_board_confirmed_track_and_arrivals():
    rows = mbta.parse_station_board(load("predictions_north"))
    # Terminating inbound predictions have no departure_time -> arrivals; the one
    # outbound departure in this capture had its track posted (platform 9).
    deps = [r for r in rows if not r["is_arrival"]]
    arrs = [r for r in rows if r["is_arrival"]]
    assert len(deps) == 1 and len(arrs) == 4
    assert deps[0]["confirmed_track"] == "9"
    assert all(r["confirmed_track"] is None for r in arrs)


# --- parse_station_schedules (terminus vs outlying) ---------------------------------------

def test_station_schedules_terminus_classification():
    rows = mbta.parse_station_schedules(load("schedules_north"))
    assert len(rows) == 50
    # pickup_type==1 (no boarding -> terminates here) is the arrival signal.
    assert sum(r["is_arrival"] for r in rows) == 43
    assert sum(not r["is_arrival"] for r in rows) == 7
    # North/South are excluded from schedule-level track ids by MBTA.
    assert all(r["scheduled_track"] is None for r in rows)


def test_station_schedules_outlying_scheduled_track():
    rows = mbta.parse_station_schedules(load("schedules_ruggles"))
    assert len(rows) == 50
    tracks = {r["scheduled_track"] for r in rows}
    # Outlying multi-track stations carry the timetabled platform since May 2023.
    assert tracks == {"1", "2", "3"}
    # Ruggles is a through-station: every train boards here.
    assert all(not r["is_arrival"] for r in rows)


# --- parse_alerts (train-number join) ------------------------------------------------------

def test_alerts_by_train_join():
    out = mbta.parse_alerts(load("alerts"))
    assert len(out["items"]) == 37
    # Alert trip ids end in the train number; the by_train map keys on that.
    assert out["by_train"], "expected at least one train-specific alert in capture"
    assert all(k.isdigit() for k in out["by_train"])
    union = set()
    for it in out["items"]:
        union.update(it["trains"])
        assert "effect" in it and "header" in it
        assert isinstance(it["routes"], list) and isinstance(it["stops"], list)
    assert union == set(out["by_train"])


# --- parse_system_predictions (one row per active trip) ------------------------------------

def test_system_predictions_one_row_per_trip_at_next_stop():
    payload = load("system_predictions")
    rows = mbta.parse_system_predictions(payload)
    trip_ids = [r["trip_id"] for r in rows]
    assert len(trip_ids) == len(set(trip_ids)), "must reduce to one row per trip"
    # Each trip's chosen row is its minimum upcoming stop_sequence in the raw payload.
    min_seq = {}
    for p in payload["data"]:
        tid = ((p["relationships"].get("trip") or {}).get("data") or {}).get("id")
        seq = p["attributes"].get("stop_sequence")
        if tid and seq is not None:
            min_seq[tid] = min(min_seq.get(tid, seq), seq)
    for r in rows:
        if r["next_stop_seq"] is not None and r["trip_id"] in min_seq:
            assert r["next_stop_seq"] == min_seq[r["trip_id"]]
        assert "reported_status" in r and "predicted_time" in r and "scheduled_time" in r
