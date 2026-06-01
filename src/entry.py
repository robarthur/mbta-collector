"""Entry Worker + Collector Durable Object for the North Station platform collector.

- Collector (DurableObject): owns the ~15s poll loop via its alarm(); writes to D1.
- Default (WorkerEntrypoint): serves /health, /board, /analyze, /poll-once (reads D1),
  and keeps the DO alarm armed (on request + via the 1-min cron backstop).

Both Cloudflare classes live here so they register cleanly; pure logic is in
mbta.py / sql.py / timeutil.py.
"""

from workers import WorkerEntrypoint, Response, DurableObject
from urllib.parse import urlparse

import mbta
import sql
import timeutil

POLL_INTERVAL_MS = 15_000
DO_NAME = "north-station"


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
        """Ensure the self-sustaining alarm loop is running."""
        current = await self.ctx.storage.getAlarm()
        if current is None:
            self.ctx.storage.setAlarm(timeutil.now_ms() + POLL_INTERVAL_MS)
            return "armed"
        return "already-armed"

    async def alarm(self, alarm_info=None):
        try:
            await self._poll()
        finally:
            # Always reschedule so a single failed poll never kills the loop.
            self.ctx.storage.setAlarm(timeutil.now_ms() + POLL_INTERVAL_MS)

    async def poll_now(self):
        """Run one poll synchronously (used by /poll-once for fast feedback)."""
        return await self._poll()

    # --- the actual work ---------------------------------------------------
    async def _poll(self):
        api_key = env_get(self.env, "MBTA_API_KEY")
        payload = await mbta.fetch_predictions(api_key)
        observations, occupancy = mbta.parse_payload(payload)

        ts = timeutil.now_iso()
        db = self.env.DB

        res = await db.prepare(sql.INSERT_POLL).bind(ts).run()
        poll_id = res.meta.last_row_id

        if observations:
            obs_stmts = [
                db.prepare(sql.INSERT_OBS).bind(
                    poll_id, o["trip_id"], o["vehicle_id"], o["route_id"],
                    o["direction_id"], o["current_status"], o["current_stop_sequence"],
                    o["vehicle_stop_id"], o["latitude"], o["longitude"], o["speed"],
                    o["bearing"], o["pred_stop_id"], o["arrival_time"],
                    o["departure_time"], o["status_text"],
                )
                for o in observations
            ]
            await db.batch(obs_stmts)

        service_date = timeutil.service_date()
        event_count = 0
        event_stmts = []
        for o in observations:
            track, via = mbta.known_track(o)
            if not track:
                continue
            event_stmts.append(
                db.prepare(sql.INSERT_EVENT).bind(
                    o["trip_id"], o["vehicle_id"], o["route_id"], service_date,
                    track, via, ts, o.get("arrival_time"), o.get("departure_time"),
                    timeutil.lead_seconds(o.get("arrival_time"), ts),
                    timeutil.lead_seconds(o.get("departure_time"), ts),
                )
            )
            event_count += 1
        if event_stmts:
            await db.batch(event_stmts)

        return {
            "poll_id": poll_id,
            "ts": ts,
            "observations": len(observations),
            "events_seen": event_count,
            "occupancy": occupancy,
        }


class Default(WorkerEntrypoint):
    def _collector(self):
        ns = self.env.COLLECTOR
        return ns.get(ns.idFromName(DO_NAME))

    async def scheduled(self, controller):
        # Cron backstop: keep the alarm loop alive if it ever stops.
        await self._collector().arm()

    async def fetch(self, request):
        path = urlparse(request.url).path

        # Best-effort: make sure the poll loop is running.
        try:
            await self._collector().arm()
        except Exception:
            pass

        if path in ("/", ""):
            return Response(
                "estimated-platform collector\n"
                "  GET /health      counts + last poll time\n"
                "  GET /board       live 10-track occupancy + inbound trains\n"
                "  GET /analyze     per-route track bias + lead-time stats\n"
                "  GET /poll-once   force one poll now (debug)\n"
            )

        db = self.env.DB

        if path == "/health":
            row = (_rows(await db.prepare(sql.HEALTH).all()) or [{}])[0]
            return Response.json({"status": "ok", **row})

        if path == "/poll-once":
            result = await self._collector().poll_now()
            return Response.json(result)

        if path == "/board":
            return Response.json(await self._board(db))

        if path == "/analyze":
            return Response.json(await self._analyze(db))

        return Response("Not Found", status=404)

    async def _board(self, db):
        latest = _rows(await db.prepare(sql.LATEST_POLL).all())
        if not latest:
            return {"status": "no data yet"}
        poll = latest[0]
        obs = _rows(await db.prepare(sql.OBS_FOR_POLL).bind(poll["poll_id"]).all())

        tracks = {str(i): None for i in range(1, 11)}
        for o in obs:
            if o.get("current_status") == "STOPPED_AT":
                t = mbta.track_from_stop(o.get("vehicle_stop_id"))
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
            track, via = mbta.known_track(o)
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

        return {"poll": poll, "occupancy": tracks, "inbound": inbound}

    async def _analyze(self, db):
        return {
            "route_track_distribution": _rows(await db.prepare(sql.ROUTE_TRACK_DIST).all()),
            "resolved_via": _rows(await db.prepare(sql.RESOLVED_VIA_DIST).all()),
            "lead_time_summary": (_rows(await db.prepare(sql.LEAD_SUMMARY).all()) or [{}])[0],
        }
