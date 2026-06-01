-- North Station arrival-platform collector schema (SQLite dialect; runs on Cloudflare D1).

-- One row per poll cycle.
CREATE TABLE IF NOT EXISTS polls (
  poll_id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts      TEXT NOT NULL                 -- ISO8601 UTC poll timestamp
);

-- Raw per-trip snapshot for each poll (prediction joined with its vehicle).
CREATE TABLE IF NOT EXISTS observations (
  poll_id               INTEGER NOT NULL,
  station               TEXT NOT NULL,  -- north | south | backbay
  trip_id               TEXT,
  vehicle_id            TEXT,
  route_id              TEXT,
  direction_id          INTEGER,
  current_status        TEXT,           -- INCOMING_AT / STOPPED_AT / IN_TRANSIT_TO
  current_stop_sequence INTEGER,
  vehicle_stop_id       TEXT,           -- the vehicle's current stop (may be a BNT-0000-0x track)
  latitude              REAL,
  longitude             REAL,
  speed                 REAL,
  bearing               REAL,
  pred_stop_id          TEXT,           -- prediction stop (BNT-0000 generic, or BNT-0000-0x once assigned)
  arrival_time          TEXT,
  departure_time        TEXT,
  status_text           TEXT,           -- e.g. "All aboard", "Now boarding"
  route_pattern_id      TEXT,           -- branch within a line, e.g. CR-Newburyport-...-1
  trip_name             TEXT            -- train number, e.g. "1246"
);
-- Only index poll_id: the board reads observations by poll_id. trip/station indexes were
-- dropped to cut write amplification (each index counts toward D1 rows-written). Add them
-- back for the analysis phase if needed.
CREATE INDEX IF NOT EXISTS idx_obs_poll ON observations(poll_id);

-- First moment we learned a trip's track on a given service day (ground truth + lead time).
CREATE TABLE IF NOT EXISTS track_events (
  trip_id             TEXT NOT NULL,
  station             TEXT NOT NULL,    -- north | south | backbay
  vehicle_id          TEXT,
  route_id            TEXT,
  service_date        TEXT NOT NULL,    -- America/New_York date, ~3am rollover
  resolved_track      TEXT,             -- platform_code, e.g. "3"
  resolved_via        TEXT,             -- prediction_stop | vehicle_stopped_at
  resolved_ts         TEXT,             -- ISO8601 UTC when we first knew
  predicted_arrival   TEXT,
  scheduled_departure TEXT,
  lead_to_arrival_s   INTEGER,          -- predicted_arrival - resolved_ts (often ~0/negative)
  lead_to_departure_s INTEGER,          -- departure - resolved_ts
  route_pattern_id    TEXT,             -- branch within a line
  trip_name           TEXT,             -- train number
  PRIMARY KEY (trip_id, service_date)
);
CREATE INDEX IF NOT EXISTS idx_te_route ON track_events(route_id);
CREATE INDEX IF NOT EXISTS idx_te_station ON track_events(station);
