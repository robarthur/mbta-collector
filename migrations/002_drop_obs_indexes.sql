-- Drop the trip/station indexes on observations to cut write amplification.
-- D1 counts every index entry toward "rows written"; these two ~tripled the obs write cost.
-- idx_obs_poll is kept (the board queries observations by poll_id).
DROP INDEX IF EXISTS idx_obs_trip;
DROP INDEX IF EXISTS idx_obs_station;
