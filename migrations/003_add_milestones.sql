-- Berth/board milestones per outbound service, to measure how much earlier the berthed
-- trainset reveals the platform vs the departure board. Additive; safe to re-run.
CREATE TABLE IF NOT EXISTS milestones (
  trip_id          TEXT NOT NULL,
  service_date     TEXT NOT NULL,
  kind             TEXT NOT NULL,
  ts               TEXT NOT NULL,
  track            TEXT,
  station          TEXT,
  route_id         TEXT,
  route_pattern_id TEXT,
  trip_name        TEXT,
  PRIMARY KEY (trip_id, service_date, kind)
);
CREATE INDEX IF NOT EXISTS idx_ms_station ON milestones(station, service_date);
