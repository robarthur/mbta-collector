-- True physical-arrival linkage. Additive; safe to re-run.
ALTER TABLE milestones ADD COLUMN vehicle_id TEXT;

CREATE TABLE IF NOT EXISTS vehicle_arrivals (
  vehicle_id   TEXT NOT NULL,
  service_date TEXT NOT NULL,
  track        TEXT NOT NULL,
  station      TEXT,
  arrive_ts    TEXT NOT NULL,
  trip_name    TEXT,
  route_id     TEXT,
  direction_id INTEGER,
  PRIMARY KEY (vehicle_id, service_date, track)
);
