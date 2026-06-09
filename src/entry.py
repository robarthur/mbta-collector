"""Entry Worker + Collector Durable Object for the CR platform collector.

Collects multiple multi-platform Commuter Rail stations (North, South, Back Bay).

- Collector (DurableObject): owns the ~15s poll loop via its alarm(); polls every
  station each cycle and writes to D1.
- Default (WorkerEntrypoint): serves /health, /board, /analyze, /poll-once (reads D1),
  and keeps the DO alarm armed (on request + via the 1-min cron backstop).

Both Cloudflare classes live here so they register cleanly; pure logic is in
mbta.py / sql.py / timeutil.py.
"""

from workers import WorkerEntrypoint, Response, DurableObject
from js import JSON
from urllib.parse import urlparse, parse_qs
import json

import mbta
import sql
import timeutil
import ui

POLL_INTERVAL_MS = 15_000        # how often we poll MBTA + detect track resolutions
SNAPSHOT_INTERVAL_MS = 120_000   # how often we persist a full observations snapshot
DEPARTURE_BOARD_N = 12           # how many upcoming departures the station board shows
# Service-affecting alert effects worth a board banner (excludes elevator/parking/access noise).
ALERT_BANNER_EFFECTS = {"CANCELLATION", "DELAY", "SUSPENSION", "TRACK_CHANGE", "DETOUR",
                        "SERVICE_CHANGE", "SCHEDULE_CHANGE", "SHUTTLE", "STATION_CLOSURE",
                        "SNOW_ROUTE", "NO_SERVICE", "STOP_CLOSURE", "STATION_ISSUE"}
DO_NAME = "collector"


def env_get(env, name):
    """Read an optional binding/var off env; None if absent."""
    try:
        v = getattr(env, name)
    except Exception:
        return None
    if v is None:
        return None
    s = str(v)
    return s if s and s != "undefined" else None


def _bound(db, query, params):
    """Prepare + bind a D1 statement with correct NULL handling.

    D1 rejects `undefined`, which is what any Python None -> JS conversion produces.
    So we build the args as a real JS array via JSON.parse (Python None -> JSON null
    -> JS null) and spread it through Function.apply, keeping nulls entirely in JS.
    """
    stmt = db.prepare(query)
    js_args = JSON.parse(json.dumps(params))
    return stmt.bind.apply(stmt, js_args)


def _rows(res):
    """Normalize a D1 .all() result into a list of plain Python dicts."""
    out = []
    try:
        arr = res.results
    except Exception:
        return out
    for item in arr:
        out.append(item.to_py() if hasattr(item, "to_py") else item)
    return out


CORS = {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET, OPTIONS",
    "access-control-allow-headers": "*",
}


def _json(obj, max_age=15):
    """JSON response with CORS (the app is served from a different origin / Pages) + cache."""
    headers = {"content-type": "application/json; charset=UTF-8",
               "cache-control": f"public, max-age={max_age}", **CORS}
    return Response(json.dumps(obj), headers=headers)


PREDICT_SINGLE_MIN = 60     # at/above this modal confidence we show a single platform
PREDICT_RANGE_COVERAGE = 80  # else widen to the platforms covering this cumulative share


def _track_key(t):
    return (int(t) if t.isdigit() else 9999, t)


def _predict_from(train, branch, line, tn, rp, rid):
    """Predicted track from historical priors, backoff: train# -> branch -> line.

    Returns the modal track + confidence, and -- when the modal confidence is below
    PREDICT_SINGLE_MIN -- a contiguous platform `range` spanning the most-likely tracks that
    together cover ~PREDICT_RANGE_COVERAGE% of history (so a low-confidence single guess is
    presented honestly as e.g. "Plat 1-5 ~78%").
    """
    def _from(dist, basis):
        total = sum(dist.values())
        ranked = sorted(dist.items(), key=lambda kv: -kv[1])
        modal_pct = 100 * ranked[0][1] / total
        out = {"predicted_track": ranked[0][0], "confidence": round(modal_pct),
               "alternatives": [{"track": t, "pct": round(100 * n / total)} for t, n in ranked[:5]],
               "basis": basis, "n_samples": total}
        if modal_pct < PREDICT_SINGLE_MIN:
            chosen, acc = [], 0
            for t, n in ranked:
                chosen.append(t)
                acc += n
                if 100 * acc / total >= PREDICT_RANGE_COVERAGE:
                    break
            nums = sorted(chosen, key=_track_key)
            out["range"] = {"low": nums[0], "high": nums[-1], "tracks": chosen,
                            "confidence": round(100 * acc / total)}
        return out
    if tn and train.get(tn) and sum(train[tn].values()) >= 3:
        return _from(train[tn], "train")
    if rp and branch.get(rp) and sum(branch[rp].values()) >= 5:
        return _from(branch[rp], "branch")
    if rid and line.get(rid):
        return _from(line[rid], "line")
    return None


class Collector(DurableObject):
    # --- alarm lifecycle ---------------------------------------------------
    async def arm(self):
        """Ensure the self-sustaining alarm loop is running.

        Re-arm if there's no alarm OR the scheduled alarm is overdue (stuck / not firing).
        A healthy loop's next alarm is always in the near future; an alarm whose time is
        well in the past means the chain stalled, so reset it. getAlarm() returns JS null
        (falsy) when unset.
        """
        current = await self.ctx.storage.getAlarm()
        now = timeutil.now_ms()
        overdue = False
        if current:
            try:
                overdue = int(current) < now - 30_000
            except Exception:
                overdue = True
        if (not current) or overdue:
            await self.ctx.storage.setAlarm(now + POLL_INTERVAL_MS)
            return "armed"
        return "already-armed"

    async def alarm(self, alarm_info=None):
        try:
            await self._poll()
        finally:
            # Always reschedule so a single failed poll never kills the loop.
            await self.ctx.storage.setAlarm(timeutil.now_ms() + POLL_INTERVAL_MS)

    async def poll_now(self):
        """Run one poll synchronously (used by /poll-once for fast feedback)."""
        return await self._poll()

    async def _track_map(self, station_id, api_key):
        """Lazily fetch + cache each station's child-stop -> platform_code map."""
        cache = getattr(self, "_tmaps", None)
        if cache is None:
            cache = {}
            self._tmaps = cache
        if station_id not in cache:
            cache[station_id] = await mbta.fetch_track_map(station_id, api_key)
        return cache[station_id]

    # --- the actual work ---------------------------------------------------
    async def _poll(self):
        api_key = env_get(self.env, "MBTA_API_KEY")
        ts = timeutil.now_iso()
        service_date = timeutil.service_date()
        db = self.env.DB

        # Decoupled cadence to stay within D1's free daily write budget:
        # - track_events (the resolution moments) are written every poll (~15s) for precise
        #   lead times; they're tiny + deduped by (trip_id, service_date).
        # - the full observations snapshot is only written every SNAPSHOT_INTERVAL_MS.
        # The snapshot clock lives in DO storage (free; not a D1 write).
        now = timeutil.now_ms()
        last = await self.ctx.storage.get("last_snapshot_ms")
        last_ms = int(last) if last else 0
        do_snapshot = (now - last_ms) >= SNAPSHOT_INTERVAL_MS

        poll_id = None
        if do_snapshot:
            res = await _bound(db, sql.INSERT_POLL, [ts]).all()
            poll_id = _rows(res)[0]["poll_id"]

        obs_stmts = []
        event_stmts = []
        milestone_stmts = []
        summary = {}
        for key, spec in mbta.STATIONS.items():
            track_map = await self._track_map(spec["station_id"], api_key)
            payload = await mbta.fetch_predictions(spec["station_id"], api_key)
            observations, occupancy = mbta.parse_payload(payload, track_map)

            events = 0
            for o in observations:
                if do_snapshot:
                    obs_stmts.append(_bound(db, sql.INSERT_OBS, [
                        poll_id, key, o["trip_id"], o["vehicle_id"], o["route_id"],
                        o["direction_id"], o["current_status"], o["current_stop_sequence"],
                        o["vehicle_stop_id"], o["latitude"], o["longitude"], o["speed"],
                        o["bearing"], o["pred_stop_id"], o["arrival_time"],
                        o["departure_time"], o["status_text"],
                        o.get("route_pattern_id"), o.get("trip_name"),
                    ]))

                # Milestones (every poll, 15s precision): record the first time we learn the
                # track via the departure prediction (board) and via the berthed trainset (berth).
                board_track = mbta.track_from_stop(o.get("pred_stop_id"), track_map)
                berth_track = (mbta.track_from_stop(o.get("vehicle_stop_id"), track_map)
                               if o.get("current_status") == "STOPPED_AT" else None)
                for kind, mtrack in (("board", board_track), ("berth", berth_track)):
                    if mtrack:
                        milestone_stmts.append(_bound(db, sql.INSERT_MILESTONE, [
                            o["trip_id"], service_date, kind, ts, mtrack, key,
                            o["route_id"], o.get("route_pattern_id"), o.get("trip_name"),
                            o.get("vehicle_id"),
                        ]))

                track, via = mbta.known_track(o, track_map)
                if track:
                    event_stmts.append(_bound(db, sql.INSERT_EVENT, [
                        o["trip_id"], key, o["vehicle_id"], o["route_id"], service_date,
                        track, via, ts, o.get("arrival_time"), o.get("departure_time"),
                        timeutil.lead_seconds(o.get("arrival_time"), ts),
                        timeutil.lead_seconds(o.get("departure_time"), ts),
                        o.get("route_pattern_id"), o.get("trip_name"),
                    ]))
                    events += 1
            summary[key] = {
                "observations": len(observations),
                "events_seen": events,
                "occupancy": occupancy,
            }

        # True arrival from VehiclePositions: this feed shows every train continuously, so it
        # catches a trainset STOPPED_AT a platform during layover — before its outbound
        # prediction exists. Record an 'arrive' milestone (the real berth time), keyed by the
        # vehicle's current trip (the outbound service once the turn is assigned).
        stop_to_station = {}
        for skey, spec in mbta.STATIONS.items():
            for sid, code in (await self._track_map(spec["station_id"], api_key)).items():
                stop_to_station[sid] = (skey, code)
        try:
            for v in mbta.parse_vehicles(await mbta.fetch_vehicles(api_key)):
                if v.get("current_status") != "STOPPED_AT":
                    continue
                hit = stop_to_station.get(v.get("stop_id"))
                if not hit:
                    continue
                skey, track = hit
                # True physical arrival, keyed by trainset+track — captures the train even as
                # its inbound service, before the turn flips it to the outbound trip.
                if v.get("vehicle_id"):
                    milestone_stmts.append(_bound(db, sql.INSERT_VEHICLE_ARRIVAL, [
                        v["vehicle_id"], service_date, track, skey, ts,
                        v.get("trip_name"), v.get("route_id"), v.get("direction_id"),
                    ]))
                # Also keep the trip-keyed 'arrive' milestone (fires once flipped to a trip).
                if v.get("trip_id"):
                    milestone_stmts.append(_bound(db, sql.INSERT_MILESTONE, [
                        v["trip_id"], service_date, "arrive", ts, track, skey,
                        v.get("route_id"), v.get("route_pattern_id"), v.get("trip_name"),
                        v.get("vehicle_id"),
                    ]))
        except Exception:
            pass

        # System-wide per-train delay snapshot (every ~2 min, on snapshot polls only).
        status_stmts = []
        if do_snapshot:
            try:
                for s in mbta.parse_system_predictions(await mbta.fetch_system_predictions(api_key)):
                    delay_s = timeutil.lead_seconds(s.get("predicted_time"), s.get("scheduled_time"))
                    status_stmts.append(_bound(db, sql.INSERT_TRAIN_STATUS, [
                        ts, service_date, s["trip_id"], s.get("trip_name"), s.get("route_id"),
                        s.get("route_pattern_id"), s.get("vehicle_id"), s.get("direction_id"),
                        s.get("next_stop_id"), s.get("next_stop_seq"),
                        s.get("predicted_time"), s.get("scheduled_time"), delay_s,
                        s.get("current_status"), s.get("reported_status"),
                        s.get("latitude"), s.get("longitude"),
                    ]))
            except Exception:
                pass

        if obs_stmts:
            await db.batch(obs_stmts)
        if event_stmts:
            await db.batch(event_stmts)
        if milestone_stmts:
            await db.batch(milestone_stmts)
        if status_stmts:
            await db.batch(status_stmts)
        if do_snapshot:
            await self.ctx.storage.put("last_snapshot_ms", now)

        return {"poll_id": poll_id, "ts": ts, "snapshot": do_snapshot, "stations": summary}


class Default(WorkerEntrypoint):
    def _collector(self):
        ns = self.env.COLLECTOR
        return ns.get(ns.idFromName(DO_NAME))

    async def scheduled(self, *args):
        # Cron backstop (every 1 min): revive the alarm loop if it has stalled.
        # Signature uses *args because the runtime passes (controller, env, ctx).
        await self._collector().arm()

    async def fetch(self, request):
        if getattr(request, "method", "GET") == "OPTIONS":
            return Response("", headers=CORS)

        parts = urlparse(request.url)
        path = parts.path
        # Versioned API: /api/v1/<x> routes the same as /<x> (legacy paths kept as aliases).
        if path.startswith("/api/v1"):
            path = path[len("/api/v1"):] or "/"
        query = parse_qs(parts.query)
        station = (query.get("station") or ["north"])[0]

        # Best-effort: make sure the poll loop is running.
        try:
            await self._collector().arm()
        except Exception:
            pass

        # Legacy inline SPA (served during the React/Pages transition).
        if path in ("/", "", "/ui"):
            return Response(ui.PAGE, headers={"content-type": "text/html;charset=UTF-8"})

        db = self.env.DB

        if path == "/health":
            row = (_rows(await db.prepare(sql.HEALTH).all()) or [{}])[0]
            by_station = _rows(await db.prepare(sql.EVENTS_BY_STATION).all())
            return _json({"status": "ok", "events_by_station": by_station, **row})

        if path == "/poll-once":
            result = await self._collector().poll_now()
            return _json(result)

        if path == "/board":
            return _json(await self._board(db, station))

        if path == "/analyze":
            return _json(await self._analyze(db))

        if path == "/events":
            return _json(_rows(await db.prepare(sql.RECENT_EVENTS).all()))

        if path == "/turn-lead":
            return _json({
                "true_lead": {  # physical arrival (by vehicle+track, pre-flip) vs board posting
                    "by_station": _rows(await db.prepare(sql.TRUE_LEAD).all()),
                    "recent": _rows(await db.prepare(sql.TRUE_LEAD_RECENT).all()),
                },
                "arrive_vs_board_by_station": _rows(await db.prepare(sql.TURN_LEAD_ARRIVE).all()),
                "berth_vs_board_by_station": _rows(await db.prepare(sql.TURN_LEAD).all()),
            })

        if path == "/turn":
            return _json(await self._turn(db, station))

        if path == "/predict":
            return _json(await self._predict(db, station))

        if path == "/delays":
            return _json({
                "by_line": _rows(await db.prepare(sql.DELAYS_BY_LINE).all()),
            })

        if path == "/trains":
            route = (query.get("route") or [None])[0]
            if route:
                rows = _rows(await _bound(db, sql.TRAINS_LATEST_BY_ROUTE, [route]).all())
            else:
                rows = _rows(await db.prepare(sql.TRAINS_LATEST).all())
            return _json({"trains": rows})

        if path == "/stops":
            api_key = env_get(self.env, "MBTA_API_KEY")
            stops = mbta.parse_cr_stops(await mbta.fetch_cr_stops(api_key))
            return _json({"stops": stops}, max_age=3600)

        if path == "/station":
            stop = (query.get("stop") or [None])[0]
            if not stop:
                return _json({"error": "stop required"})
            api_key = env_get(self.env, "MBTA_API_KEY")
            board = mbta.parse_station_board(await mbta.fetch_station_predictions(stop, api_key))
            preds = {r["trip_id"]: r for r in board if r.get("trip_id")}

            # Arrivals: live predictions only (inbound trains are predicted well ahead).
            arrivals = [r for r in board if r.get("direction_id") == 1]

            # Departures: the booked timetable (next N) as the spine, with each row enriched
            # by its live prediction (time/status/confirmed platform) when one has posted.
            # MBTA only predicts a departure once a set is assigned, so the schedule keeps the
            # board populated in the gaps; the union also picks up late trains still predicting.
            sched = mbta.parse_station_schedules(
                await mbta.fetch_station_schedules(stop, api_key, timeutil.eastern_hhmm(), DEPARTURE_BOARD_N))
            departures, seen = [], set()
            for s in sched:
                p = preds.get(s["trip_id"])
                departures.append({**s, **{k: p[k] for k in
                                  ("predicted_time", "status", "confirmed_track")} } if p else s)
                seen.add(s["trip_id"])
            for r in board:  # live departure predictions not in the upcoming schedule (e.g. late)
                if r.get("direction_id") == 0 and r.get("trip_id") not in seen:
                    departures.append(r)
            departures.sort(key=lambda d: d.get("predicted_time") or d.get("scheduled_time") or "")
            departures = departures[:DEPARTURE_BOARD_N]

            # Per-train platform prediction for the stations we track history at.
            key = next((k for k, s in mbta.STATIONS.items() if s["station_id"] == stop), None)
            priors = await self._load_priors(db, key) if key else None
            for d in departures + arrivals:
                d["delay_s"] = timeutil.lead_seconds(d.get("predicted_time"), d.get("scheduled_time"))
                d["prediction"] = (_predict_from(*priors, d.get("trip_name"),
                                                 d.get("route_pattern_id"), d.get("route_id"))
                                   if priors else None)

            # Alerts: tag each train named by an alert (cancelled/delayed/track change), and
            # surface a banner of service-affecting alerts relevant to this station.
            alerts = mbta.parse_alerts(await mbta.fetch_alerts(api_key))
            for d in departures + arrivals:
                al = alerts["by_train"].get(d.get("trip_name"))
                if al:
                    d["alert_effect"] = al["effect"]
                    d["alert_header"] = al["header"]
            board_routes = {d.get("route_id") for d in departures + arrivals if d.get("route_id")}
            banner, seen_hdr = [], set()
            for it in alerts["items"]:
                if it["effect"] not in ALERT_BANNER_EFFECTS:
                    continue
                if not (stop in it["stops"] or (board_routes & set(it["routes"]))):
                    continue
                if it["header"] in seen_hdr:
                    continue
                seen_hdr.add(it["header"])
                banner.append({"effect": it["effect"], "severity": it["severity"],
                               "header": it["header"]})
            return _json({"stop": stop, "departures": departures, "arrivals": arrivals[:40],
                          "alerts": banner[:6]}, max_age=20)

        if path == "/history":
            return _json({
                "by_route": _rows(await db.prepare(sql.HISTORY_BY_ROUTE).all()),
                "by_day": _rows(await db.prepare(sql.HISTORY_BY_DAY).all()),
                "by_hour_et": _rows(await db.prepare(sql.HISTORY_BY_HOUR).all()),
            })

        return Response("Not Found", status=404)

    async def _board(self, db, station):
        spec = mbta.STATIONS.get(station)
        if spec is None:
            return {"error": "unknown station", "valid": list(mbta.STATIONS.keys())}

        api_key = env_get(self.env, "MBTA_API_KEY")
        track_map = await mbta.fetch_track_map(spec["station_id"], api_key)

        latest = _rows(await db.prepare(sql.LATEST_POLL).all())
        if not latest:
            return {"status": "no data yet"}
        poll = latest[0]
        obs = _rows(await _bound(db, sql.OBS_FOR_POLL, [poll["poll_id"], station]).all())

        tracks = {t: None for t in mbta.tracks_of(track_map)}
        for o in obs:
            if o.get("current_status") == "STOPPED_AT":
                t = mbta.track_from_stop(o.get("vehicle_stop_id"), track_map)
                if t:
                    tracks[t] = {
                        "vehicle": o.get("vehicle_id"),
                        "trip": o.get("trip_id"),
                        "route": o.get("route_id"),
                    }

        inbound = []
        for o in obs:
            if not o.get("arrival_time"):
                continue
            track, via = mbta.known_track(o, track_map)
            inbound.append({
                "trip": o.get("trip_id"),
                "route": o.get("route_id"),
                "vehicle": o.get("vehicle_id"),
                "arrival_time": o.get("arrival_time"),
                "status": o.get("current_status"),
                "track": track,
                "track_known": track is not None,
                "via": via,
            })

        return {
            "station": station,
            "name": spec["name"],
            "poll": poll,
            "occupancy": tracks,
            "inbound": inbound,
        }

    async def _turn(self, db, station):
        spec = mbta.STATIONS.get(station)
        if spec is None:
            return {"error": "unknown station", "valid": list(mbta.STATIONS.keys())}
        sd = timeutil.service_date()
        cutoff = timeutil.seconds_ago_iso(1800)  # only "currently" berthed (last 30 min)
        rows = _rows(await _bound(db, sql.LIVE_TURN, [station, sd, cutoff]).all())
        return {
            "station": station,
            "name": spec["name"],
            "service_date": sd,
            "berthed_board_not_posted": rows,
        }

    async def _load_priors(self, db, station):
        """(train, branch, line) track-distribution priors for a platform station."""
        train, branch, line = {}, {}, {}
        for r in _rows(await _bound(db, sql.PRIORS_TRAIN, [station]).all()):
            train.setdefault(r.get("trip_name"), {})[str(r.get("resolved_track"))] = r.get("n")
        for r in _rows(await _bound(db, sql.PRIORS_BRANCH, [station]).all()):
            branch.setdefault(r.get("route_pattern_id"), {})[str(r.get("resolved_track"))] = r.get("n")
        for r in _rows(await _bound(db, sql.PRIORS_LINE, [station]).all()):
            line.setdefault(r.get("route_id"), {})[str(r.get("resolved_track"))] = r.get("n")
        return train, branch, line

    async def _predict(self, db, station):
        spec = mbta.STATIONS.get(station)
        if spec is None:
            return {"error": "unknown station", "valid": list(mbta.STATIONS.keys())}
        api_key = env_get(self.env, "MBTA_API_KEY")
        track_map = await mbta.fetch_track_map(spec["station_id"], api_key)

        # Priors from history: per-train (trip_name), branch (route_pattern_id), line (route_id).
        train, branch, line = {}, {}, {}
        for r in _rows(await _bound(db, sql.PRIORS_TRAIN, [station]).all()):
            train.setdefault(r.get("trip_name"), {})[str(r.get("resolved_track"))] = r.get("n")
        for r in _rows(await _bound(db, sql.PRIORS_BRANCH, [station]).all()):
            branch.setdefault(r.get("route_pattern_id"), {})[str(r.get("resolved_track"))] = r.get("n")
        for r in _rows(await _bound(db, sql.PRIORS_LINE, [station]).all()):
            line.setdefault(r.get("route_id"), {})[str(r.get("resolved_track"))] = r.get("n")

        def _from(dist, basis):
            total = sum(dist.values())
            ranked = sorted(dist.items(), key=lambda kv: -kv[1])
            return {
                "predicted_track": ranked[0][0],
                "confidence": round(100 * ranked[0][1] / total),
                "alternatives": [{"track": t, "pct": round(100 * n / total)} for t, n in ranked[:3]],
                "basis": basis, "n_samples": total,
            }

        def predict(tn, rp, rid):
            # Backoff: train number (best — works for departures) -> branch -> line.
            if tn and train.get(tn) and sum(train[tn].values()) >= 3:
                return _from(train[tn], "train")
            if rp and branch.get(rp) and sum(branch[rp].values()) >= 5:
                return _from(branch[rp], "branch")
            if rid and line.get(rid):
                return _from(line[rid], "line")
            return None

        trains = []
        latest = _rows(await db.prepare(sql.LATEST_POLL).all())
        if latest:
            obs = _rows(await _bound(db, sql.OBS_FOR_POLL, [latest[0]["poll_id"], station]).all())
            for o in obs:
                if not (o.get("arrival_time") or o.get("departure_time")):
                    continue
                track, via = mbta.known_track(o, track_map)
                trains.append({
                    "trip_name": o.get("trip_name"), "route": o.get("route_id"),
                    "branch": o.get("route_pattern_id"), "direction_id": o.get("direction_id"),
                    "arrival_time": o.get("arrival_time"), "departure_time": o.get("departure_time"),
                    "status": o.get("current_status"),
                    "actual_track": track, "track_known": track is not None,
                    "prediction": predict(o.get("trip_name"), o.get("route_pattern_id"), o.get("route_id")),
                })
        # "inbound" kept as an alias for backward-compat with the current UI.
        return {"station": station, "name": spec["name"], "trains": trains, "inbound": trains}

    async def _analyze(self, db):
        return {
            "route_track_distribution": _rows(await db.prepare(sql.ROUTE_TRACK_DIST).all()),
            "branch_track_distribution": _rows(await db.prepare(sql.BRANCH_TRACK_DIST).all()),
            "resolved_via": _rows(await db.prepare(sql.RESOLVED_VIA_DIST).all()),
            "lead_time_summary_by_station": _rows(await db.prepare(sql.LEAD_SUMMARY).all()),
        }
