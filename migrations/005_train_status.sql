-- System-wide per-train status + delay snapshots. Additive; safe to re-run.
CREATE TABLE IF NOT EXISTS train_status (
  snapshot_ts      TEXT NOT NULL,
  service_date     TEXT,
  trip_id          TEXT NOT NULL,
  trip_name        TEXT,
  route_id         TEXT,
  route_pattern_id TEXT,
  vehicle_id       TEXT,
  direction_id     INTEGER,
  next_stop_id     TEXT,
  next_stop_seq    INTEGER,
  predicted_time   TEXT,
  scheduled_time   TEXT,
  delay_s          INTEGER,
  current_status   TEXT,
  latitude         REAL,
  longitude        REAL,
  PRIMARY KEY (trip_id, snapshot_ts)
);
