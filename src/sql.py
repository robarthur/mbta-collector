"""SQL statements shared by the Collector DO (writes) and the entry Worker (reads)."""

INSERT_POLL = "INSERT INTO polls (ts) VALUES (?) RETURNING poll_id"

INSERT_OBS = (
    "INSERT INTO observations ("
    "poll_id, station, trip_id, vehicle_id, route_id, direction_id, current_status, "
    "current_stop_sequence, vehicle_stop_id, latitude, longitude, speed, bearing, "
    "pred_stop_id, arrival_time, departure_time, status_text, route_pattern_id, trip_name"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

# PK (trip_id, service_date) + OR IGNORE = record each resolution exactly once, no extra state.
INSERT_EVENT = (
    "INSERT OR IGNORE INTO track_events ("
    "trip_id, station, vehicle_id, route_id, service_date, resolved_track, resolved_via, "
    "resolved_ts, predicted_arrival, scheduled_departure, lead_to_arrival_s, lead_to_departure_s, "
    "route_pattern_id, trip_name"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

LATEST_POLL = "SELECT poll_id, ts FROM polls ORDER BY poll_id DESC LIMIT 1"

OBS_FOR_POLL = "SELECT * FROM observations WHERE poll_id = ? AND station = ?"

# Note: no COUNT(*) on observations here — it's the largest table and a full scan would
# burn read quota on every /health (which the board polls). polls/track_events are small.
HEALTH = (
    "SELECT "
    "(SELECT COUNT(*) FROM polls) AS snapshots, "
    "(SELECT COUNT(*) FROM track_events) AS track_events, "
    "(SELECT MAX(ts) FROM polls) AS last_poll_ts"
)

EVENTS_BY_STATION = (
    "SELECT station, COUNT(*) AS n FROM track_events GROUP BY station ORDER BY station"
)

ROUTE_TRACK_DIST = (
    "SELECT station, route_id, resolved_track, COUNT(*) AS n "
    "FROM track_events GROUP BY station, route_id, resolved_track "
    "ORDER BY station, route_id, n DESC"
)

LEAD_SUMMARY = (
    "SELECT station, COUNT(*) AS events, "
    "AVG(lead_to_arrival_s) AS avg_lead_arrival_s, "
    "MIN(lead_to_arrival_s) AS min_lead_arrival_s, "
    "MAX(lead_to_arrival_s) AS max_lead_arrival_s, "
    "AVG(lead_to_departure_s) AS avg_lead_departure_s "
    "FROM track_events GROUP BY station ORDER BY station"
)

RESOLVED_VIA_DIST = (
    "SELECT station, resolved_via, COUNT(*) AS n "
    "FROM track_events GROUP BY station, resolved_via ORDER BY station, n DESC"
)

BRANCH_TRACK_DIST = (
    "SELECT station, route_pattern_id, resolved_track, COUNT(*) AS n "
    "FROM track_events WHERE route_pattern_id IS NOT NULL "
    "GROUP BY station, route_pattern_id, resolved_track "
    "ORDER BY station, route_pattern_id, n DESC"
)

INSERT_MILESTONE = (
    "INSERT OR IGNORE INTO milestones ("
    "trip_id, service_date, kind, ts, track, station, route_id, route_pattern_id, trip_name, vehicle_id"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

INSERT_VEHICLE_ARRIVAL = (
    "INSERT OR IGNORE INTO vehicle_arrivals ("
    "vehicle_id, service_date, track, station, arrive_ts, trip_name, route_id, direction_id"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)

# TRUE lead: board posting vs the trainset's physical arrival at that track (any trip).
# lead_s > 0 => the trainset was on the platform before the board posted the track.
TRUE_LEAD = (
    "SELECT bo.station, COUNT(*) AS turns, "
    "SUM(CASE WHEN va.arrive_ts < bo.ts THEN 1 ELSE 0 END) AS arrive_first, "
    "SUM(CASE WHEN va.direction_id = 1 THEN 1 ELSE 0 END) AS caught_inbound, "
    "CAST(AVG((julianday(bo.ts)-julianday(va.arrive_ts))*86400) AS INT) AS avg_lead_s, "
    "MAX(CAST((julianday(bo.ts)-julianday(va.arrive_ts))*86400 AS INT)) AS max_lead_s "
    "FROM (SELECT vehicle_id, service_date, station, track, ts FROM milestones "
    "WHERE kind='board' AND vehicle_id IS NOT NULL) bo "
    "JOIN vehicle_arrivals va ON va.vehicle_id=bo.vehicle_id "
    "AND va.service_date=bo.service_date AND va.track=bo.track "
    "GROUP BY bo.station ORDER BY bo.station"
)

TRUE_LEAD_RECENT = (
    "SELECT bo.station, bo.trip_name, bo.route_id, bo.track, va.direction_id AS arr_dir, "
    "CAST((julianday(bo.ts)-julianday(va.arrive_ts))*86400 AS INT) AS lead_s, "
    "va.arrive_ts, bo.ts AS board_ts "
    "FROM (SELECT vehicle_id, service_date, station, track, ts, trip_name, route_id "
    "FROM milestones WHERE kind='board' AND vehicle_id IS NOT NULL) bo "
    "JOIN vehicle_arrivals va ON va.vehicle_id=bo.vehicle_id "
    "AND va.service_date=bo.service_date AND va.track=bo.track "
    "ORDER BY bo.ts DESC LIMIT 25"
)

# Per (trip, service_date): how much earlier the berth was known vs the board posting.
# lead_s > 0 => the berthed trainset revealed the platform before the departure board.
TURN_LEAD = (
    "SELECT b.station, COUNT(*) AS turns, "
    "SUM(CASE WHEN b.ts < bo.ts THEN 1 ELSE 0 END) AS berth_first, "
    "SUM(CASE WHEN b.track = bo.track THEN 1 ELSE 0 END) AS track_match, "
    "CAST(AVG((julianday(bo.ts)-julianday(b.ts))*86400) AS INT) AS avg_lead_s, "
    "CAST(MAX((julianday(bo.ts)-julianday(b.ts))*86400) AS INT) AS max_lead_s "
    "FROM (SELECT trip_id, service_date, station, ts, track FROM milestones WHERE kind='berth') b "
    "JOIN (SELECT trip_id, service_date, ts, track FROM milestones WHERE kind='board') bo "
    "USING (trip_id, service_date) GROUP BY b.station ORDER BY b.station"
)

TURN_LEAD_RECENT = (
    "SELECT b.station, b.trip_name, b.route_id, b.route_pattern_id, "
    "b.track AS berth_track, bo.track AS board_track, "
    "CAST((julianday(bo.ts)-julianday(b.ts))*86400 AS INT) AS lead_s, b.ts AS berth_ts "
    "FROM (SELECT * FROM milestones WHERE kind='berth') b "
    "JOIN (SELECT trip_id, service_date, ts, track FROM milestones WHERE kind='board') bo "
    "USING (trip_id, service_date) ORDER BY bo.ts DESC LIMIT 25"
)

# True lead: trainset physically arrived (VehiclePositions) vs board posting the track.
# lead_s > 0 => the trainset was on the platform before the board announced it.
TURN_LEAD_ARRIVE = (
    "SELECT a.station, COUNT(*) AS turns, "
    "SUM(CASE WHEN a.ts < bo.ts THEN 1 ELSE 0 END) AS arrive_first, "
    "SUM(CASE WHEN a.track = bo.track THEN 1 ELSE 0 END) AS track_match, "
    "CAST(AVG((julianday(bo.ts)-julianday(a.ts))*86400) AS INT) AS avg_lead_s, "
    "CAST(MAX((julianday(bo.ts)-julianday(a.ts))*86400) AS INT) AS max_lead_s "
    "FROM (SELECT trip_id, service_date, station, ts, track FROM milestones WHERE kind='arrive') a "
    "JOIN (SELECT trip_id, service_date, ts, track FROM milestones WHERE kind='board') bo "
    "USING (trip_id, service_date) GROUP BY a.station ORDER BY a.station"
)

TURN_LEAD_ARRIVE_RECENT = (
    "SELECT a.station, a.trip_name, a.route_id, a.track AS arrive_track, bo.track AS board_track, "
    "CAST((julianday(bo.ts)-julianday(a.ts))*86400 AS INT) AS lead_s, a.ts AS arrive_ts, bo.ts AS board_ts "
    "FROM (SELECT * FROM milestones WHERE kind='arrive') a "
    "JOIN (SELECT trip_id, service_date, ts, track FROM milestones WHERE kind='board') bo "
    "USING (trip_id, service_date) ORDER BY bo.ts DESC LIMIT 25"
)

# Live: trains physically on a platform now whose board track hasn't posted yet
# (we know the platform from the trainset; the board doesn't yet).
LIVE_TURN = (
    "SELECT m.trip_name, m.route_id, m.route_pattern_id, m.track, m.ts AS arrive_ts "
    "FROM milestones m "
    "WHERE m.kind='arrive' AND m.station=? AND m.service_date=? AND m.ts > ? "
    "AND NOT EXISTS (SELECT 1 FROM milestones b WHERE b.trip_id=m.trip_id "
    "AND b.service_date=m.service_date AND b.kind='board') "
    "ORDER BY m.ts DESC"
)

RECENT_EVENTS = (
    "SELECT station, route_id, resolved_track, resolved_via, resolved_ts, "
    "lead_to_arrival_s, lead_to_departure_s "
    "FROM track_events ORDER BY resolved_ts DESC LIMIT 25"
)
