"""MBTA V3 API client + parsing for North Station Commuter Rail.

One request per poll: predictions at North Station (route_type=2) with the related
vehicle included, so we get each train's live position/status/stop in the same payload.
"""

import httpx

API_BASE = "https://api-v3.mbta.com"
STATION = "place-north"        # North Station parent
TRACK_PREFIX = "BNT-0000-"     # child stops BNT-0000-01 .. BNT-0000-10 carry the track number
ROUTE_TYPE_CR = "2"            # Commuter Rail


def track_from_stop(stop_id):
    """'BNT-0000-03' -> '3'; anything else (incl. generic 'BNT-0000') -> None."""
    if not stop_id or not stop_id.startswith(TRACK_PREFIX):
        return None
    suffix = stop_id[len(TRACK_PREFIX):]
    return str(int(suffix)) if suffix.isdigit() else suffix


async def fetch_predictions(api_key=None):
    params = {
        "filter[stop]": STATION,
        "filter[route_type]": ROUTE_TYPE_CR,
        "include": "vehicle",
        "sort": "arrival_time",
    }
    headers = {"accept": "application/vnd.api+json"}
    if api_key:
        headers["x-api-key"] = api_key
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{API_BASE}/predictions", params=params, headers=headers)
        r.raise_for_status()
        return r.json()


def _rel_id(rel, name):
    data = (rel.get(name) or {}).get("data") or {}
    return data.get("id")


def parse_payload(payload):
    """Return (observations, occupancy).

    observations: list of dicts, one per North Station CR prediction joined with its vehicle.
    occupancy:    dict track -> vehicle_id for tracks with a train currently STOPPED_AT.
    """
    included = payload.get("included") or []
    vehicles = {}
    for inc in included:
        if inc.get("type") != "vehicle":
            continue
        a = inc.get("attributes") or {}
        rel = inc.get("relationships") or {}
        vehicles[inc.get("id")] = {
            "current_status": a.get("current_status"),
            "current_stop_sequence": a.get("current_stop_sequence"),
            "latitude": a.get("latitude"),
            "longitude": a.get("longitude"),
            "speed": a.get("speed"),
            "bearing": a.get("bearing"),
            "stop_id": _rel_id(rel, "stop"),
        }

    observations = []
    for p in payload.get("data") or []:
        a = p.get("attributes") or {}
        rel = p.get("relationships") or {}
        vehicle_id = _rel_id(rel, "vehicle")
        v = vehicles.get(vehicle_id, {})
        observations.append({
            "trip_id": _rel_id(rel, "trip"),
            "vehicle_id": vehicle_id,
            "route_id": _rel_id(rel, "route"),
            "direction_id": a.get("direction_id"),
            "current_status": v.get("current_status"),
            "current_stop_sequence": v.get("current_stop_sequence"),
            "vehicle_stop_id": v.get("stop_id"),
            "latitude": v.get("latitude"),
            "longitude": v.get("longitude"),
            "speed": v.get("speed"),
            "bearing": v.get("bearing"),
            "pred_stop_id": _rel_id(rel, "stop"),
            "arrival_time": a.get("arrival_time"),
            "departure_time": a.get("departure_time"),
            "status_text": a.get("status"),
        })

    occupancy = {}
    for vid, v in vehicles.items():
        if v.get("current_status") == "STOPPED_AT":
            t = track_from_stop(v.get("stop_id"))
            if t:
                occupancy[t] = vid

    return observations, occupancy


def known_track(obs):
    """(track, via) for an observation, or (None, None) if the track isn't knowable yet.

    Prefer the assigned prediction stop; fall back to a vehicle physically STOPPED_AT a track.
    """
    t = track_from_stop(obs.get("pred_stop_id"))
    if t:
        return t, "prediction_stop"
    if obs.get("current_status") == "STOPPED_AT":
        t = track_from_stop(obs.get("vehicle_stop_id"))
        if t:
            return t, "vehicle_stopped_at"
    return None, None
