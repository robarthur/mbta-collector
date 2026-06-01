-- Add branch (route_pattern_id) and train number (trip_name) to existing tables.
-- Safe on populated DBs: ADD COLUMN appends nullable columns; existing rows stay NULL.
ALTER TABLE observations ADD COLUMN route_pattern_id TEXT;
ALTER TABLE observations ADD COLUMN trip_name TEXT;
ALTER TABLE track_events ADD COLUMN route_pattern_id TEXT;
ALTER TABLE track_events ADD COLUMN trip_name TEXT;
