# estimated-platform — Architecture & Data Reference

An MBTA Commuter Rail webapp + data collector running entirely on Cloudflare. It does three
things:

1. **Live** — system-wide train positions and delays, by line.
2. **Historical performance** — on-time performance and delay trends over time.
3. **Predicted platforms** — which track an arriving train will use, before the board posts it.

Live at **https://estimated-platform.robarthur1.workers.dev/** · repo `robarthur/mbta-collector`
(branch `poc-collector`).

---

## 1. Stack & runtime

- **Cloudflare Python Workers** (open beta, Pyodide = CPython→WASM). Entry `src/entry.py`.
  Driven via **`pywrangler`** (the `workers-py` wrapper) — *not* bare `npx wrangler` (that
  fails to bundle deps). Only dependency: `httpx`.
- **Durable Object** `Collector` (Python) — owns the poll loop via the Alarms API.
- **D1** (serverless SQLite) — durable store, bound as `env.DB`.
- **Cron trigger** (`*/1 * * * *`) — backstop that re-arms the DO alarm if it stalls.
- **Frontend** — one self-contained HTML/CSS/JS string (`src/ui.py`), Leaflet via CDN, no build.

```
Internet ─▶ Default (WorkerEntrypoint, src/entry.py)         Cron (1/min)
              ├─ GET / /ui            → HTML SPA (ui.PAGE)      └─ scheduled() → Collector.arm()
              ├─ GET /health /board /trains /delays …→ read env.DB (D1)
              └─ arms Collector alarm on each request
                              │ DO RPC
                              ▼
            Collector (DurableObject)  ── alarm() every ~15s:
              fetch MBTA V3 (httpx) → parse → write D1 (batched) → reschedule alarm
```

### Files (`src/`)
| File | Lines | Role |
|---|---|---|
| `entry.py` | ~446 | `Collector` DO (poll loop) + `Default` worker (all HTTP routes) |
| `mbta.py` | ~279 | MBTA V3 client + parsing (feeds, track resolution, delay reduction) |
| `sql.py` | ~238 | All SQL statements (inserts + read queries) |
| `timeutil.py` | ~60 | `service_date` (America/NY, 3am rollover), `lead_seconds`, ms/iso helpers |
| `ui.py` | ~266 | `PAGE` — the 3-view SPA |

`schema.sql` = full DDL (local dev). `migrations/00N_*.sql` = additive migrations applied to
the live D1 in order (001→006). `wrangler.jsonc` = Worker/D1/DO/cron config.

---

## 2. Data feeds (all MBTA V3 API, `https://api-v3.mbta.com`)

`MBTA_API_KEY` is a Worker secret (raises rate limit to ~1000/min); works without it too.

| Call | When | Purpose |
|---|---|---|
| `/stops/{station}?include=child_stops` | once/station, cached in DO | build track map: child stop id → `platform_code` (handles Back Bay's two stop families) |
| `/predictions?filter[stop]={station}&filter[route_type]=2&include=vehicle,trip` | every ~15s, per station (north/south/backbay) | platform board: arrivals/departures + vehicle position/status + trip (name, branch) |
| `/vehicles?filter[route_type]=2&include=trip` | every ~15s | all CR train positions continuously (catches berthing the predictions feed misses) |
| `/predictions?filter[route]={13 CR routes}&include=schedule,vehicle,trip` | every ~2 min (snapshot) | system-wide delay: predicted vs **scheduled** times + position, all lines |

**V3 vs GTFS-realtime:** V3 is MBTA's JSON:API layer over the same source as GTFS-rt
(`/predictions` ≈ TripUpdates, `/vehicles` ≈ VehiclePositions). We use V3 for its filtering +
`include`. The track rides in the `stop_id` (`BNT-0000-0x` etc.); `platform_code` = track number.

### Stations & lines
- **Platform stations** (3, terminal/multi-platform): `north` (`place-north`, `BNT-0000-01..10`),
  `south` (`place-sstat`, `NEC-2287-01..13`), `backbay` (`place-bbsta`, mixed `NEC-2276`/`WML-0012`).
- **Delay coverage** (13 lines): CR-Fairmount, NewBedford, Fitchburg, Worcester, Franklin,
  Greenbush, Haverhill, Kingston, Lowell, Needham, Newburyport, Providence, Foxboro.

---

## 3. Data collection (the poll loop)

`Collector.alarm()` runs ~every **15s** and reschedules itself (`ctx.storage.setAlarm`,
must be `await`ed). Two cadences keep D1 writes within the free tier (100k rows/day):

**Every poll (~15s)** — low-volume, high-precision:
- For each platform station: fetch predictions+vehicle+trip, then:
  - **`track_events`** — first time a trip's track becomes known (per trip/service_date):
    via the departure prediction stop (`resolved_via=prediction_stop`) or the vehicle
    `STOPPED_AT` a track (`vehicle_stopped_at`). `INSERT OR IGNORE` (dedup = free).
  - **`milestones`** — `board` (prediction posted track) and `berth` (vehicle stopped at track),
    each first-seen, for berth-vs-board lead.
- From `/vehicles`: **`vehicle_arrivals`** (true physical arrival by vehicle+track, pre-flip) +
  a trip-keyed `arrive` milestone.

**Every ~2 min (snapshot, gated by `last_snapshot_ms` in DO storage)** — bulky:
- **`polls`** row (the snapshot clock).
- **`observations`** — full per-trip snapshot at the 3 stations.
- **`train_status`** — system-wide per-train delay (next stop: predicted−scheduled) + position.

Resilience: `arm()` re-arms if the alarm is missing **or overdue (>30s)**; the cron re-arms
every minute as a backstop. (A past bug: a missing `await` on `setAlarm` + a wrong `scheduled`
signature let the loop die silently overnight — both fixed.)

---

## 4. Database schema (D1 / SQLite)

Seven tables. (`station` ∈ `north|south|backbay`; times are ISO8601 UTC unless noted.)

- **`polls`** `(poll_id PK, ts)` — one row per snapshot cycle.
- **`observations`** `(poll_id, station, trip_id, vehicle_id, route_id, direction_id,
  current_status, current_stop_sequence, vehicle_stop_id, latitude, longitude, speed, bearing,
  pred_stop_id, arrival_time, departure_time, status_text, route_pattern_id, trip_name)` —
  raw 2-min snapshot at the platform stations. Index: `poll_id`.
- **`track_events`** `(trip_id, station, vehicle_id, route_id, service_date, resolved_track,
  resolved_via, resolved_ts, predicted_arrival, scheduled_departure, lead_to_arrival_s,
  lead_to_departure_s, route_pattern_id, trip_name)` PK `(trip_id, service_date)` — **the
  platform ground-truth + lead dataset.** Indexes: route_id, station. (Note:
  `scheduled_departure` is actually the *predicted* departure — historical misnomer.)
- **`milestones`** `(trip_id, service_date, kind, ts, track, station, route_id,
  route_pattern_id, trip_name, vehicle_id)` PK `(trip_id, service_date, kind)`,
  `kind ∈ berth|board|arrive`. For berth/arrive-vs-board lead.
- **`vehicle_arrivals`** `(vehicle_id, service_date, track, station, arrive_ts, trip_name,
  route_id, direction_id)` PK `(vehicle_id, service_date, track)` — true physical arrival,
  trip-independent (`direction_id=1` = caught inbound).
- **`train_status`** `(snapshot_ts, service_date, trip_id, trip_name, route_id,
  route_pattern_id, vehicle_id, direction_id, next_stop_id, next_stop_seq, predicted_time,
  scheduled_time, delay_s, current_status, reported_status, latitude, longitude)` PK
  `(trip_id, snapshot_ts)` — **system-wide live/historical delay backbone.**
  `delay_s = predicted − scheduled` at the next stop (+late). `reported_status` = feed's status text.

Migrations applied (live D1): 001 branch+trainnum on obs/track_events · 002 drop obs trip/station
indexes · 003 milestones · 004 vehicle_arrivals (+`vehicle_id` on milestones) · 005 train_status
· 006 `reported_status`.

---

## 5. HTTP endpoints (all `GET`, JSON unless noted)

| Route | Returns |
|---|---|
| `/` , `/ui` | the HTML SPA (`text/html`) |
| `/health` | `{status, snapshots, track_events, last_poll_ts, events_by_station[]}` |
| `/poll-once` | forces one poll (debug); `{poll_id, ts, snapshot, stations:{key:{observations,events_seen,occupancy}}}` |
| `/board?station=` | `{station, name, poll, occupancy:{track:occupant|null}, inbound:[{trip,route,vehicle,arrival_time,status,track,track_known,via}]}` |
| `/predict?station=` | `{station, name, inbound:[{trip_name,route,branch,arrival_time,status,actual_track,track_known, prediction:{predicted_track,confidence,alternatives[],basis,n_samples}}]}` |
| `/trains?route=` | `{trains:[{route_id,route_pattern_id,trip_name,direction_id,next_stop_id,delay_s,current_status,reported_status,latitude,longitude,predicted_time}]}` (latest snapshot; optional route filter) |
| `/delays` | `{by_line:[{route_id,trains,avg_delay_min,max_delay_min,pct_on_time}]}` (latest snapshot) |
| `/history` | `{by_route[], by_day[], by_hour_et[]}` — per-trip final delay → per-line/day OTP + hourly delay curve |
| `/analyze` | `{route_track_distribution[], branch_track_distribution[], resolved_via[], lead_time_summary_by_station[]}` |
| `/events` | last 25 `track_events` (recent platform resolutions) |
| `/turn-lead` | `{true_lead:{by_station[],recent[]}, arrive_vs_board_by_station[], berth_vs_board_by_station[]}` — berth/arrival vs board lead |
| `/turn?station=` | `{station,name,service_date, berthed_board_not_posted[]}` — trains on a platform now whose board track isn't posted |

Param `station` defaults to `north`. Endpoints read D1 directly (no DO call) except
`/poll-once` and `/predict`/`/board`/`/turn` (which fetch the live track map from the API).

---

## 6. Key derivations

- **Track resolution** (`mbta.known_track`): prediction stop is a numbered track →
  `prediction_stop`; else vehicle `STOPPED_AT` a numbered track → `vehicle_stopped_at`.
- **Delay** (`train_status.delay_s`): `predicted − scheduled` at the train's next stop, from
  `/predictions?…&include=schedule`. **Forecast, not measured actual.** `reported_status` is
  the feed's qualitative status ("Delayed"/"On time"); we show Estimated vs Reported.
- **Platform prediction** (`/predict`): historical distribution of `resolved_track` for the
  train's **branch** (`route_pattern_id`, if ≥5 samples) else **line** (`route_id`); returns
  top track + confidence + alternatives. *Currently line-level in practice* — inbound trains
  carry the `-1` branch variant while history is keyed to the outbound `-0` branch, so it backs
  off to line. Branch-level needs an inbound→outbound mapping (planned).
- **Berth-vs-board lead** (`/turn-lead`): how much earlier the trainset reveals the platform
  than the board. Finding so far: ~0 at North (trains aren't seen on a numbered platform as the
  inbound service; the track is born with the departure).

---

## 7. Frontend (`src/ui.py`, served at `/`)

One `PAGE` string, vanilla JS, Leaflet (CDN), dark theme. Top-level views:
- **Map** — Leaflet + OSM; markers from `/trains` colored by delay; per-line filter chips;
  popups show **Est delay** vs **Reported** status + next stop. Auto-refresh ~30s.
- **Lines** — `/delays` (current) + `/history` (`by_route` OTP bars, `by_hour_et` delay curve).
- **Platforms** — station tabs; occupancy grid (`/board`); inbound table with **Predicted**
  column (`/predict`); recent resolutions (`/events`); a static zone hint per station.

Positions are ~2-min fresh (from D1 `train_status`). A real-time `/live-trains` proxy of the
vehicles feed is a noted future enhancement.

---

## 8. Dev & deploy

```bash
npm install                                   # wrangler CLI
uv sync                                        # python deps + pywrangler

# LOCAL
npx wrangler d1 execute estimated-platform --local --file schema.sql
uv run pywrangler dev                          # http://localhost:8787

# DEPLOY
wrangler d1 execute estimated-platform --remote --file migrations/00N_*.sql   # new migration
rm -rf .wrangler && uv run pywrangler deploy   # clear cache to avoid stale bundles
```

**Footguns:**
- `rm -rf .wrangler` wipes the **local** dev D1 (re-apply `schema.sql --local`); remote is safe.
- Use `uv run pywrangler`, not `npx wrangler`, for dev/deploy (Python bundling).
- Pyodide `None` → JS `undefined`, which D1 rejects; we bind params via `JSON.parse` so `null`
  survives (`_bound` in `entry.py`). `run_js`/`eval` is forbidden by workerd CSP.

---

## 9. Constraints & honest caveats

- **D1 free tier**: 100k rows written/day. Current ~62k/day (obs + train_status snapshots +
  events/milestones). Decoupled cadence (2-min snapshots) keeps us under; watch if adding writes.
- **Beta runtime**: Python Workers + Pyodide; package subset (httpx ok, no pandas/native).
- **Delay is predicted, not actual** (no recorded arrival times; could add, or use MBTA LAMP).
- **Predicted platforms**: South is genuinely predictable (e.g. Fairmount→10 ~66–71%); **North
  exact track is not** (dispatcher/yard discretion; only the east/west *zone* is reliable —
  Eastern Route → tracks 1–5, Fitchburg/Lowell → 6–10). ~4 days of priors so far.
- **Switch/interlocking/yard state is not public** — the arrival platform isn't in any feed
  before the departure is set up; that's the core limit the whole project ran into.
