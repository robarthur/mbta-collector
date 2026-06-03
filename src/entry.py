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
                        s.get("current_status"), s.get("latitude"), s.get("longitude"),
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
        parts = urlparse(request.url)
        path = parts.path
        query = parse_qs(parts.query)
        station = (query.get("station") or ["north"])[0]

        # Best-effort: make sure the poll loop is running.
        try:
            await self._collector().arm()
        except Exception:
            pass

        if path in ("/", "", "/ui"):
            return Response(ui.PAGE, headers={"content-type": "text/html;charset=UTF-8"})

        db = self.env.DB

        if path == "/health":
            row = (_rows(await db.prepare(sql.HEALTH).all()) or [{}])[0]
            by_station = _rows(await db.prepare(sql.EVENTS_BY_STATION).all())
            return Response.json({"status": "ok", "events_by_station": by_station, **row})

        if path == "/poll-once":
            result = await self._collector().poll_now()
            return Response.json(result)

        if path == "/board":
            return Response.json(await self._board(db, station))

        if path == "/analyze":
            return Response.json(await self._analyze(db))

        if path == "/events":
            return Response.json(_rows(await db.prepare(sql.RECENT_EVENTS).all()))

        if path == "/turn-lead":
            return Response.json({
                "true_lead": {  # physical arrival (by vehicle+track, pre-flip) vs board posting
                    "by_station": _rows(await db.prepare(sql.TRUE_LEAD).all()),
                    "recent": _rows(await db.prepare(sql.TRUE_LEAD_RECENT).all()),
                },
                "arrive_vs_board_by_station": _rows(await db.prepare(sql.TURN_LEAD_ARRIVE).all()),
                "berth_vs_board_by_station": _rows(await db.prepare(sql.TURN_LEAD).all()),
            })

        if path == "/turn":
            return Response.json(await self._turn(db, station))

        if path == "/delays":
            return Response.json({
                "by_line": _rows(await db.prepare(sql.DELAYS_BY_LINE).all()),
            })

        if path == "/trains":
            route = (query.get("route") or [None])[0]
            if route:
                rows = _rows(await _bound(db, sql.TRAINS_LATEST_BY_ROUTE, [route]).all())
            else:
                rows = _rows(await db.prepare(sql.TRAINS_LATEST).all())
            return Response.json({"trains": rows})

        if path == "/history":
            return Response.json({
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

    async def _analyze(self, db):
        return {
            "route_track_distribution": _rows(await db.prepare(sql.ROUTE_TRACK_DIST).all()),
            "branch_track_distribution": _rows(await db.prepare(sql.BRANCH_TRACK_DIST).all()),
            "resolved_via": _rows(await db.prepare(sql.RESOLVED_VIA_DIST).all()),
            "lead_time_summary_by_station": _rows(await db.prepare(sql.LEAD_SUMMARY).all()),
        }
