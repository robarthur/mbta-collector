"""SQL statements shared by the Collector DO (writes) and the entry Worker (reads)."""

INSERT_POLL = "INSERT INTO polls (ts) VALUES (?) RETURNING poll_id"

INSERT_OBS = (
    "INSERT INTO observations ("
    "poll_id, trip_id, vehicle_id, route_id, direction_id, current_status, "
    "current_stop_sequence, vehicle_stop_id, latitude, longitude, speed, bearing, "
    "pred_stop_id, arrival_time, departure_time, status_text"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

# PK (trip_id, service_date) + OR IGNORE = record each resolution exactly once, no extra state.
INSERT_EVENT = (
    "INSERT OR IGNORE INTO track_events ("
    "trip_id, vehicle_id, route_id, service_date, resolved_track, resolved_via, "
    "resolved_ts, predicted_arrival, scheduled_departure, lead_to_arrival_s, lead_to_departure_s"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

LATEST_POLL = "SELECT poll_id, ts FROM polls ORDER BY poll_id DESC LIMIT 1"

OBS_FOR_POLL = "SELECT * FROM observations WHERE poll_id = ?"

HEALTH = (
    "SELECT "
    "(SELECT COUNT(*) FROM polls) AS polls, "
    "(SELECT COUNT(*) FROM observations) AS observations, "
    "(SELECT COUNT(*) FROM track_events) AS track_events, "
    "(SELECT MAX(ts) FROM polls) AS last_poll_ts"
)

ROUTE_TRACK_DIST = (
    "SELECT route_id, resolved_track, COUNT(*) AS n "
    "FROM track_events GROUP BY route_id, resolved_track "
    "ORDER BY route_id, n DESC"
)

LEAD_SUMMARY = (
    "SELECT COUNT(*) AS events, "
    "AVG(lead_to_arrival_s) AS avg_lead_arrival_s, "
    "MIN(lead_to_arrival_s) AS min_lead_arrival_s, "
    "MAX(lead_to_arrival_s) AS max_lead_arrival_s, "
    "AVG(lead_to_departure_s) AS avg_lead_departure_s "
    "FROM track_events"
)

RESOLVED_VIA_DIST = (
    "SELECT resolved_via, COUNT(*) AS n FROM track_events GROUP BY resolved_via ORDER BY n DESC"
)
