"""MBTA V3 API client + parsing for Commuter Rail terminals.

One predictions request per station per poll: predictions at the station (route_type=2)
with the related vehicle included, so we get each train's live position/status/stop in the
same payload.

Tracks are resolved via a per-station child-stop -> platform_code map fetched from the API
(see fetch_track_map). This avoids assuming a single stop-id prefix per station -- Back Bay,
for example, spans two stop families (NEC-2276-* and WML-0012-*).
"""

import httpx

API_BASE = "https://api-v3.mbta.com"
ROUTE_TYPE_CR = "2"

# All 13 Commuter Rail routes (V3 rejects filter[route_type] alone; filter[route] is allowed).
CR_ROUTES = (
    "CR-Fairmount,CR-NewBedford,CR-Fitchburg,CR-Worcester,CR-Franklin,CR-Greenbush,"
    "CR-Haverhill,CR-Kingston,CR-Lowell,CR-Needham,CR-Newburyport,CR-Providence,CR-Foxboro"
)

# Multi-platform CR terminals/stations we collect. North & South are stub-end terminals
# that assign tracks dynamically/late (the interesting case); Back Bay is a through-station
# that largely resolves from the schedule (useful contrast).
STATIONS = {
    "north":   {"name": "North Station", "station_id": "place-north"},
    "south":   {"name": "South Station", "station_id": "place-sstat"},
    "backbay": {"name": "Back Bay",      "station_id": "place-bbsta"},
}


def _headers(api_key):
    h = {"accept": "application/vnd.api+json"}
    if api_key:
        h["x-api-key"] = api_key
    return h


async def fetch_track_map(station_id, api_key=None):
    """Return {child_stop_id: platform_code} for the station's CR track platforms."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(
            f"{API_BASE}/stops/{station_id}",
            params={"include": "child_stops"},
            headers=_headers(api_key),
        )
        r.raise_for_status()
        payload = r.json()
    out = {}
    for s in payload.get("included") or []:
        a = s.get("attributes") or {}
        if a.get("vehicle_type") == 2 and a.get("platform_code"):
            out[s.get("id")] = str(a.get("platform_code"))
    return out


def tracks_of(track_map):
    """Sorted list of platform codes for a station (numeric-aware)."""
    return sorted(set(track_map.values()), key=lambda t: (int(t) if t.isdigit() else 9999, t))


def track_from_stop(stop_id, track_map):
    """Platform code for a stop id, or None for the generic (track-less) station stop."""
    return track_map.get(stop_id) if stop_id else None


async def fetch_predictions(station_id, api_key=None):
    params = {
        "filter[stop]": station_id,
        "filter[route_type]": ROUTE_TYPE_CR,
        "include": "vehicle,trip",
        "sort": "arrival_time",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{API_BASE}/predictions", params=params, headers=_headers(api_key))
        r.raise_for_status()
        return r.json()


def _rel_id(rel, name):
    data = (rel.get(name) or {}).get("data") or {}
    return data.get("id")


async def fetch_vehicles(api_key=None):
    """All CR vehicles from VehiclePositions — seen continuously, even during layover when
    a train has no active station prediction (which the predictions feed misses)."""
    params = {"filter[route_type]": ROUTE_TYPE_CR, "include": "trip"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{API_BASE}/vehicles", params=params, headers=_headers(api_key))
        r.raise_for_status()
        return r.json()


def parse_vehicles(payload):
    """Return list of {vehicle_id, current_status, stop_id, trip_id, trip_name,
    route_id, route_pattern_id, direction_id}."""
    trips = {}
    for inc in payload.get("included") or []:
        if inc.get("type") == "trip":
            a = inc.get("attributes") or {}
            rel = inc.get("relationships") or {}
            trips[inc.get("id")] = {
                "name": a.get("name"),
                "route_pattern_id": _rel_id(rel, "route_pattern"),
                "direction_id": a.get("direction_id"),
            }
    out = []
    for v in payload.get("data") or []:
        a = v.get("attributes") or {}
        rel = v.get("relationships") or {}
        tid = _rel_id(rel, "trip")
        ti = trips.get(tid, {})
        out.append({
            "vehicle_id": v.get("id"),
            "current_status": a.get("current_status"),
            "stop_id": _rel_id(rel, "stop"),
            "trip_id": tid,
            "trip_name": ti.get("name"),
            "route_pattern_id": ti.get("route_pattern_id"),
            "route_id": _rel_id(rel, "route"),
            "direction_id": ti.get("direction_id"),
            "latitude": a.get("latitude"),
            "longitude": a.get("longitude"),
            "bearing": a.get("bearing"),
            "updated_at": a.get("updated_at"),
        })
    return out


def parse_payload(payload, track_map):
    """Return (observations, occupancy).

    observations: list of dicts, one per station CR prediction joined with its vehicle.
    occupancy:    dict track -> vehicle_id for tracks with a train currently STOPPED_AT.
    """
    included = payload.get("included") or []
    vehicles = {}
    trips = {}
    for inc in included:
        t = inc.get("type")
        a = inc.get("attributes") or {}
        rel = inc.get("relationships") or {}
        if t == "vehicle":
            vehicles[inc.get("id")] = {
                "current_status": a.get("current_status"),
                "current_stop_sequence": a.get("current_stop_sequence"),
                "latitude": a.get("latitude"),
                "longitude": a.get("longitude"),
                "speed": a.get("speed"),
                "bearing": a.get("bearing"),
                "stop_id": _rel_id(rel, "stop"),
            }
        elif t == "trip":
            trips[inc.get("id")] = {
                "name": a.get("name"),                       # train number, e.g. "1246"
                "route_pattern_id": _rel_id(rel, "route_pattern"),  # branch, e.g. CR-Newburyport-...-1
            }

    observations = []
    for p in payload.get("data") or []:
        a = p.get("attributes") or {}
        rel = p.get("relationships") or {}
        vehicle_id = _rel_id(rel, "vehicle")
        trip_id = _rel_id(rel, "trip")
        v = vehicles.get(vehicle_id, {})
        ti = trips.get(trip_id, {})
        observations.append({
            "trip_id": trip_id,
            "trip_name": ti.get("name"),
            "route_pattern_id": ti.get("route_pattern_id"),
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
            t = track_from_stop(v.get("stop_id"), track_map)
            if t:
                occupancy[t] = vid

    return observations, occupancy


async def fetch_system_predictions(api_key=None):
    """All CR predictions system-wide with their scheduled times + vehicle/trip."""
    params = {"filter[route]": CR_ROUTES, "include": "schedule,vehicle,trip"}
    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.get(f"{API_BASE}/predictions", params=params, headers=_headers(api_key))
        r.raise_for_status()
        return r.json()


def parse_system_predictions(payload):
    """Reduce system-wide predictions to one 'current status' row per active trip — the
    train's next upcoming stop (min stop_sequence) — with predicted vs scheduled times and
    the vehicle's position/status. Caller computes delay_s = predicted - scheduled."""
    included = payload.get("included") or []
    schedules, vehicles, trips = {}, {}, {}
    for inc in included:
        t = inc.get("type")
        a = inc.get("attributes") or {}
        rel = inc.get("relationships") or {}
        if t == "schedule":
            schedules[inc.get("id")] = {"arrival_time": a.get("arrival_time"),
                                        "departure_time": a.get("departure_time")}
        elif t == "vehicle":
            vehicles[inc.get("id")] = {
                "current_status": a.get("current_status"),
                "latitude": a.get("latitude"), "longitude": a.get("longitude"),
            }
        elif t == "trip":
            trips[inc.get("id")] = {"name": a.get("name"),
                                    "route_pattern_id": _rel_id(rel, "route_pattern"),
                                    "direction_id": a.get("direction_id")}

    best = {}  # trip_id -> chosen next-stop record
    for p in payload.get("data") or []:
        a = p.get("attributes") or {}
        rel = p.get("relationships") or {}
        trip_id = _rel_id(rel, "trip")
        if not trip_id:
            continue
        seq = a.get("stop_sequence")
        prev = best.get(trip_id)
        if prev is not None and seq is not None and prev["next_stop_seq"] is not None \
                and prev["next_stop_seq"] <= seq:
            continue  # keep the earliest upcoming stop

        # align predicted/scheduled on the same event (arrival preferred, else departure)
        sched = schedules.get(_rel_id(rel, "schedule"), {})
        if a.get("arrival_time"):
            pred_t, sched_t = a.get("arrival_time"), sched.get("arrival_time")
        else:
            pred_t, sched_t = a.get("departure_time"), sched.get("departure_time")
        v = vehicles.get(_rel_id(rel, "vehicle"), {})
        ti = trips.get(trip_id, {})
        best[trip_id] = {
            "trip_id": trip_id,
            "trip_name": ti.get("name"),
            "route_id": _rel_id(rel, "route"),
            "route_pattern_id": ti.get("route_pattern_id"),
            "vehicle_id": _rel_id(rel, "vehicle"),
            "direction_id": ti.get("direction_id"),
            "next_stop_id": _rel_id(rel, "stop"),
            "next_stop_seq": seq,
            "predicted_time": pred_t,
            "scheduled_time": sched_t,
            "current_status": v.get("current_status"),
            "reported_status": a.get("status"),   # feed's words: "Delayed"/"On time"/...
            "latitude": v.get("latitude"),
            "longitude": v.get("longitude"),
        }
    return list(best.values())


async def fetch_cr_stops(api_key=None):
    """All CR stops + their parent stations (for the station picker)."""
    params = {"filter[route_type]": ROUTE_TYPE_CR, "page[limit]": "500",
              "include": "parent_station", "fields[stop]": "name"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{API_BASE}/stops", params=params, headers=_headers(api_key))
        r.raise_for_status()
        return r.json()


def parse_cr_stops(payload):
    # Collapse boarding stops to their parent station (the id that filter[stop] wants).
    inc = {i.get("id"): (i.get("attributes") or {}).get("name")
           for i in payload.get("included") or [] if i.get("type") == "stop"}
    stations = {}
    for s in payload.get("data") or []:
        pid = _rel_id(s.get("relationships") or {}, "parent_station")
        if pid:
            stations[pid] = inc.get(pid)
        else:
            stations[s.get("id")] = (s.get("attributes") or {}).get("name")
    out = [{"id": k, "name": v} for k, v in stations.items() if v]
    out.sort(key=lambda x: x["name"])
    return out


async def fetch_station_predictions(stop, api_key=None):
    """Upcoming CR predictions at a stop, with scheduled times + trip + route + stop
    (the stop gives the confirmed platform_code once the board posts it)."""
    params = {"filter[stop]": stop, "filter[route_type]": ROUTE_TYPE_CR,
              "include": "schedule,trip,route,stop", "sort": "departure_time"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{API_BASE}/predictions", params=params, headers=_headers(api_key))
        r.raise_for_status()
        return r.json()


def parse_station_board(payload):
    """Upcoming trains at a station: scheduled vs predicted, destination, status, and the
    confirmed platform (platform_code of the prediction's stop, present once posted)."""
    included = payload.get("included") or []
    schedules, trips, stop_platform = {}, {}, {}
    for inc in included:
        t = inc.get("type")
        a = inc.get("attributes") or {}
        rel = inc.get("relationships") or {}
        if t == "schedule":
            schedules[inc.get("id")] = {"arrival_time": a.get("arrival_time"),
                                        "departure_time": a.get("departure_time")}
        elif t == "trip":
            trips[inc.get("id")] = {"name": a.get("name"), "headsign": a.get("headsign"),
                                    "direction_id": a.get("direction_id"),
                                    "route_pattern_id": _rel_id(rel, "route_pattern")}
        elif t == "stop":
            stop_platform[inc.get("id")] = a.get("platform_code")
    out = []
    for p in payload.get("data") or []:
        a = p.get("attributes") or {}
        rel = p.get("relationships") or {}
        sched = schedules.get(_rel_id(rel, "schedule"), {})
        # The worker's vendored httpx leaves JSON null as a JsNull proxy (not Python None),
        # so test for a real ISO string instead of truthiness/`is None`.
        if isinstance(a.get("departure_time"), str):
            pred_t, sched_t = a.get("departure_time"), sched.get("departure_time")
        else:
            pred_t, sched_t = a.get("arrival_time"), sched.get("arrival_time")
        if not isinstance(pred_t, str):
            continue
        ti = trips.get(_rel_id(rel, "trip"), {})
        out.append({
            "trip_id": _rel_id(rel, "trip"),
            "trip_name": ti.get("name"), "headsign": ti.get("headsign"),
            "direction_id": ti.get("direction_id"), "route_id": _rel_id(rel, "route"),
            "route_pattern_id": ti.get("route_pattern_id"),
            "scheduled_time": sched_t if isinstance(sched_t, str) else None,
            "predicted_time": pred_t, "status": a.get("status"),
            "confirmed_track": stop_platform.get(_rel_id(rel, "stop")),
            # Predictions DO preserve a null departure_time at a terminus (unlike schedules,
            # which the worker fills), so a missing real departure string => terminates here.
            # The /station handler still lets a matching schedule row override this.
            "is_arrival": not isinstance(a.get("departure_time"), str),
        })
    out.sort(key=lambda d: d["predicted_time"])
    return out


async def fetch_station_schedules(stop, api_key=None, min_time=None, limit=50):
    """Upcoming scheduled CR stop-times at a stop, BOTH directions -- the booked timetable
    that keeps the boards populated when no live prediction has posted yet. Every stop-time
    has an arrival_time, so we sort by that; departure_time is absent only at a terminus."""
    params = {"filter[stop]": stop, "filter[route_type]": ROUTE_TYPE_CR,
              "sort": "arrival_time", "page[limit]": str(limit), "include": "trip,route,stop"}
    if min_time:
        params["filter[min_time]"] = min_time
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{API_BASE}/schedules", params=params, headers=_headers(api_key))
        r.raise_for_status()
        return r.json()


def parse_station_schedules(payload):
    """Scheduled stop-times: trip_id, train number, destination, direction, route, time,
    is_arrival (terminates here = no departure_time), and scheduled_track (the timetabled
    platform_code — populated at outlying multi-track stations since May 2023; North and
    South Station are excluded by MBTA because dispatch assigns their tracks dynamically)."""
    trips, stop_platform = {}, {}
    for inc in payload.get("included") or []:
        if inc.get("type") == "trip":
            a = inc.get("attributes") or {}
            rel = inc.get("relationships") or {}
            trips[inc.get("id")] = {"name": a.get("name"), "headsign": a.get("headsign"),
                                    "direction_id": a.get("direction_id"),
                                    "route_pattern_id": _rel_id(rel, "route_pattern")}
        elif inc.get("type") == "stop":
            pc = (inc.get("attributes") or {}).get("platform_code")
            stop_platform[inc.get("id")] = pc if isinstance(pc, str) else None
    out = []
    for s in payload.get("data") or []:
        a = s.get("attributes") or {}
        rel = s.get("relationships") or {}
        arr, dep = a.get("arrival_time"), a.get("departure_time")
        t = dep if isinstance(dep, str) else arr
        if not isinstance(t, str):
            continue
        tid = _rel_id(rel, "trip")
        ti = trips.get(tid, {})
        out.append({
            "trip_id": tid, "trip_name": ti.get("name"), "headsign": ti.get("headsign"),
            "direction_id": ti.get("direction_id"), "route_id": _rel_id(rel, "route"),
            "route_pattern_id": ti.get("route_pattern_id"),
            "scheduled_time": t, "predicted_time": None, "status": None,
            "confirmed_track": None,
            "scheduled_track": stop_platform.get(_rel_id(rel, "stop")),
            # pickup_type == 1 means "no boarding here" i.e. the train terminates -> arrival.
            # (The worker's httpx fills departure_time even at a terminus, so time presence
            # can't be used; pickup_type is the reliable GTFS signal and survives as an int.)
            "is_arrival": a.get("pickup_type") == 1,
        })
    return out


async def fetch_alerts(api_key=None):
    """Currently-active Commuter Rail alerts (cancellations, delays, track changes, etc.)."""
    params = {"filter[route_type]": ROUTE_TYPE_CR, "filter[datetime]": "now"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{API_BASE}/alerts", params=params, headers=_headers(api_key))
        r.raise_for_status()
        return r.json()


def _entity_trip_id(e):
    t = e.get("trip")
    if isinstance(t, dict):
        return t.get("id")
    return t  # V3 flattens trip to its id string


def parse_alerts(payload):
    """Return {by_train: {train_number: {effect, header}}, items: [...]} from the alerts feed.

    Alert trip ids (e.g. 'LowellElevatorWeekday-834458-34') don't share the prediction/schedule
    trip-id scheme, but their trailing segment is the train number, which is unique per service
    day and matches the board's trip_name -- so we key per-train tagging on that.
    """
    by_train, items = {}, []
    for a in payload.get("data") or []:
        at = a.get("attributes") or {}
        effect = at.get("effect")
        header = at.get("short_header") or at.get("header")
        routes, stops, trains = set(), set(), set()
        for e in at.get("informed_entity") or []:
            if e.get("route"):
                routes.add(e["route"])
            if e.get("stop"):
                stops.add(e["stop"])
            tid = _entity_trip_id(e)
            if tid:
                num = tid.rsplit("-", 1)[-1]
                if num.isdigit():
                    trains.add(num)
        for num in trains:
            by_train.setdefault(num, {"effect": effect, "header": header})
        items.append({"effect": effect, "severity": at.get("severity"), "header": header,
                      "lifecycle": at.get("lifecycle"), "routes": sorted(routes),
                      "stops": sorted(stops), "trains": sorted(trains)})
    return {"by_train": by_train, "items": items}


async def fetch_stop_departures_all_modes(stop, api_key=None):
    """Upcoming predictions at a stop across ALL modes (no route_type filter) — used to
    offer alternatives during a disruption (subway/bus/other CR at the same station)."""
    params = {"filter[stop]": stop, "include": "route,trip",
              "sort": "departure_time", "page[limit]": "60"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{API_BASE}/predictions", params=params, headers=_headers(api_key))
        r.raise_for_status()
        return r.json()


ROUTE_TYPE_MODE = {0: "subway", 1: "subway", 2: "cr", 3: "bus", 4: "ferry"}


def parse_alternatives(payload):
    """Rows: {mode, route_id, route_name, color, headsign, time} for upcoming departures."""
    routes, trips = {}, {}
    for inc in payload.get("included") or []:
        a = inc.get("attributes") or {}
        if inc.get("type") == "route":
            routes[inc.get("id")] = {"type": a.get("type"),  # route resource uses `type`
                                     "name": a.get("long_name") or inc.get("id"),
                                     "color": a.get("color")}
        elif inc.get("type") == "trip":
            trips[inc.get("id")] = a.get("headsign")
    out = []
    for p in payload.get("data") or []:
        a = p.get("attributes") or {}
        rel = p.get("relationships") or {}
        t = a.get("departure_time")
        if not isinstance(t, str):  # JsNull-safe; arrivals-only rows can't be boarded
            continue
        rt = routes.get(_rel_id(rel, "route"), {})
        out.append({"mode": ROUTE_TYPE_MODE.get(rt.get("type"), "other"),
                    "route_id": _rel_id(rel, "route"), "route_name": rt.get("name"),
                    "color": rt.get("color"),
                    "headsign": trips.get(_rel_id(rel, "trip")),
                    "time": t})
    out.sort(key=lambda r: r["time"])
    return out


def known_track(obs, track_map):
    """(track, via) for an observation, or (None, None) if the track isn't knowable yet.

    Prefer the assigned prediction stop; fall back to a vehicle physically STOPPED_AT a track.
    """
    t = track_from_stop(obs.get("pred_stop_id"), track_map)
    if t:
        return t, "prediction_stop"
    if obs.get("current_status") == "STOPPED_AT":
        t = track_from_stop(obs.get("vehicle_stop_id"), track_map)
        if t:
            return t, "vehicle_stopped_at"
    return None, None
