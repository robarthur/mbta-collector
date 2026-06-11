# estimated-platform — Architecture & Data Reference

An MBTA Commuter Rail webapp + data collector running entirely on Cloudflare. It does three
things:

1. **Live** — station departure/arrival boards, system-wide positions and delays, alerts.
2. **Historical performance** — line reliability (OTP ranking, daily trends) + delay curves.
3. **Predicted platforms** — which track a departure will use, before the board posts it
   (calibrated confidence; honest accuracy via a leave-one-out backtest).

App **https://estimated-platform.pages.dev** (React PWA on Pages) · API
**https://estimated-platform.robarthur1.workers.dev/api/v1** (Worker root 302s to the app) ·
repo `robarthur/mbta-collector` (branch `main`).

---

## 1. Stack & runtime

- **Cloudflare Python Workers** (open beta, Pyodide = CPython→WASM). Entry `src/entry.py`.
  Driven via **`pywrangler`** (the `workers-py` wrapper) — *not* bare `npx wrangler` (that
  fails to bundle deps). Only dependency: `httpx`.
- **Durable Object** `Collector` (Python) — owns the poll loop via the Alarms API.
- **D1** (serverless SQLite) — durable store, bound as `env.DB`.
- **Cron trigger** (`*/1 * * * *`) — backstop that re-arms the DO alarm if it stalls.
- **Frontend** — React + Vite PWA (`web/`) on **Cloudflare Pages**; talks to the Worker
  cross-origin via `VITE_API_BASE`. Silent auto-update SW; installable (icons set).

```
Pages (web/ React PWA) ──fetch /api/v1/*──▶ Default (WorkerEntrypoint, src/entry.py)
                                              ├─ GET / /ui → 302 to the Pages app   Cron (1/min)
                                              ├─ live MBTA proxies: /station /stops /alerts
                                              ├─ D1 reads: /health /trains /delays /history …
                                              └─ arms Collector alarm on each request │ scheduled()
                                                              │ DO RPC                ▼
                                            Collector (DurableObject) ── alarm() every ~15s:
                                              fetch MBTA V3 (httpx) → parse → write D1 → reschedule
```

### Files
| File | Role |
|---|---|
| `src/entry.py` | `Collector` DO (poll loop, status) + `Default` worker (all HTTP routes, backtest) |
| `src/mbta.py` | MBTA V3 client + parsing (boards, schedules, alerts, vehicles, delay reduction) |
| `src/predictor.py` | hierarchical-shrinkage platform predictor (pure Python, unit-tested) |
| `src/sql.py` | All SQL statements (inserts + read queries) |
| `src/timeutil.py` | `service_date` (America/NY, 3am rollover), `lead_seconds`, Eastern helpers |
| `web/src/` | React app: `views/` (Map, Stations, Lines, Platforms), `watches.js` (notify), `api.js` |
| `tests/` | pytest suite: captured-payload parser fixtures + predictor/timeutil units |

`schema.sql` = full DDL (local dev). `migrations/00N_*.sql` = additive migrations applied to
the live D1 in order (001→006). `wrangler.jsonc` = Worker/D1/DO/cron config.
`scripts/backup-d1.sh` = weekly D1 export (the dataset is irreplaceable).

---

## 2. Data feeds (all MBTA V3 API, `https://api-v3.mbta.com`)

`MBTA_API_KEY` is a Worker secret (raises rate limit to ~1000/min); works without it too.

| Call | When | Purpose |
|---|---|---|
| `/stops/{station}?include=child_stops` | once/station, cached in DO | build track map: child stop id → `platform_code` (handles Back Bay's two stop families) |
| `/predictions?filter[stop]={station}&filter[route_type]=2&include=vehicle,trip` | every ~15s, per station (north/south/backbay) | platform board: arrivals/departures + vehicle position/status + trip (name, branch) |
| `/vehicles?filter[route_type]=2&include=trip` | every ~15s | all CR train positions continuously (catches berthing the predictions feed misses) |
| `/predictions?filter[route]={13 CR routes}&include=schedule,vehicle,trip` | every ~2 min (snapshot) | system-wide delay: predicted vs **scheduled** times + position, all lines |
| `/predictions?filter[stop]=X&include=schedule,trip,route,stop` | on `/station` request | live board: predicted times + **confirmed platform** (`platform_code` of the prediction's stop) |
| `/schedules?filter[stop]=X&include=trip,route,stop` | on `/station` request | timetable spine (boards never go blank) + `pickup_type` classification + **scheduled track** at outlying stations |
| `/alerts?filter[route_type]=2&datetime=now` | on `/station` & `/alerts` requests | service alerts: banner (route/stop match) + per-train tags (trip-id suffix = train number) |
| `/stops?filter[route_type]=2&include=parent_station` | on `/stops` request (cached 1h) | the 148-station picker |

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

All JSON routes are served at both `/api/v1/<x>` (canonical) and `/<x>` (legacy alias),
with CORS for the Pages app.

| Route | Returns |
|---|---|
| `/` , `/ui` | **302 redirect** to the Pages app |
| `/health` | `{status: ok\|stale, seconds_since_poll, loop:{last_poll_ms,next_alarm_ms,last_error}, snapshots, track_events, events_by_station[]}` — honest staleness (>120s = stale) |
| `/station?stop=` | the station board: `{departures[], arrivals[], alerts[]}` — schedule spine merged with live predictions; per-row `confirmed_track` / `scheduled_track` / `prediction{}` / `delay_s` / `alert_effect`. 3 concurrent MBTA calls |
| `/stops` | the 148 CR parent stations (picker), cached 1h |
| `/alerts` | active CR alerts, tier-tagged (`urgent`/`info`) |
| `/backtest` | leave-one-out predictor evaluation: LOO vs in-sample hit-rate, calibration table, range coverage, per-train consistency |
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
- **Platform prediction** (`src/predictor.py`): **hierarchical shrinkage** — the train
  number's track counts are smoothed toward its branch distribution, which is smoothed
  toward the line (k=4 pseudocounts each). Confidence = smoothed modal probability
  (calibrated: a displayed ~60% really hits ~60% out-of-sample). Below 60% modal, returns a
  contiguous platform `range` covering ~80% of history ("Plat 1–5 ~83%"). `/backtest`
  validates the exact same code leave-one-out.
- **Departures vs arrivals** (`/station`): a train **terminates** at a stop when its
  schedule row has `pickup_type == 1` (time-presence is unusable — see Pyodide caveats);
  predictions self-classify by departure-time presence, schedule overrides by trip-id with
  a train-number fallback for late/added trips.
- **Berth-vs-board lead** (`/turn-lead` + per-trip join): the berthed set is tagged with its
  outbound trip and sits on the correct track (100% match), but the public feed attaches the
  track only **~8 min before departure** — same time as the board. Measured: no early lead
  exists in public data at the terminals; the track is "born with the departure."

---

## 7. Frontend (`web/`, React + Vite PWA on Cloudflare Pages)

Views (react-router; station deep-linkable via `/stations?stop=`):
- **Stations** — the flagship board: Departures (schedule-backed, both directions at
  through-stations) + Arrivals (terminating trains). Platform cell: green confirmed →
  grey timetabled (`scheduled_track`) → grey prediction (confidence · n, or a range).
  Alert banner (urgent inline, info collapsed) + per-row alert tags. **Watch bell** per
  departure → one-shot OS notifications via the SW (`watches.js`, localStorage,
  self-expiring; app-level 30s loop so watches fire from any view).
- **Lines** — reliability ranking (OTP color bars best→worst), expandable per-line daily
  trend sparkline + the line's active alerts; system delay-by-hour.
- **Map** — react-leaflet, markers colored by delay (~2-min fresh from `train_status`;
  a real-time `/live-trains` proxy remains a noted enhancement).
- **Platforms** — occupancy grid (`/board`), predictions (`/predict`), recent resolutions.

PWA: `vite-plugin-pwa`, `registerType: autoUpdate` + 60s SW update poll (silent updates);
icons in `web/public/`. Deploys to Pages (`_redirects` SPA fallback); `VITE_API_BASE` per env.

---

## 8. Dev & deploy

```bash
npm install                                   # wrangler CLI
uv sync                                        # python deps + pywrangler

# LOCAL
npx wrangler d1 execute estimated-platform --local --file schema.sql
uv run pywrangler dev                          # http://localhost:8787

# TESTS
uv run --group test pytest                     # parser fixtures + predictor/timeutil units

# DEPLOY
wrangler d1 execute estimated-platform --remote --file migrations/00N_*.sql   # new migration
rm -rf .wrangler && uv run pywrangler deploy   # Worker (clear cache to avoid stale bundles)
cd web && npm run build && cd .. && \
  npx wrangler pages deploy web/dist --project-name=estimated-platform --branch=main  # app

# BACKUP (weekly — the collected data exists nowhere else)
./scripts/backup-d1.sh
```

**Footguns:**
- `rm -rf .wrangler` wipes the **local** dev D1 (re-apply `schema.sql --local`); remote is safe.
- Use `uv run pywrangler`, not `npx wrangler`, for dev/deploy (Python bundling).
- Pyodide `None` → JS `undefined`, which D1 rejects; we bind params via `JSON.parse` so `null`
  survives (`_bound` in `entry.py`). `run_js`/`eval` is forbidden by workerd CSP.
- The worker's vendored httpx leaves JSON `null` as a **JsNull proxy** (`is None` is False)
  and fills schedule `departure_time` even at termini. Use `isinstance(x, str)` for presence
  and `pickup_type` for terminus classification. CPython tests pass where Pyodide differs —
  always verify behaviour against the deployed Worker.

---

## 9. Constraints & honest caveats

- **D1 free tier**: 100k rows written/day. Current ~62k/day (obs + train_status snapshots +
  events/milestones). Decoupled cadence (2-min snapshots) keeps us under; watch if adding writes.
- **Beta runtime**: Python Workers + Pyodide; package subset (httpx ok, no pandas/native).
- **Delay is predicted, not actual** (no recorded arrival times; could add, or use MBTA LAMP).
- **Predicted platforms — measured (leave-one-out, ~10 days of priors)**: Back Bay ~99%
  (scheduled, trivial), South ~40%, **North ~25%** — North's assignment is genuinely
  dynamic (1 of 93 trains is ≥80% track-consistent); only the east/west *zone* is reliable
  there (Eastern Route → 1–5, Fitchburg/Lowell → 6–10), which the range display captures.
  Displayed confidence is calibrated (shrinkage), and `/backtest` re-measures as data grows.
- **The track is assigned ~8 min before departure** at North/South and enters the public
  feed only then (board, prediction stop, and vehicle stop all at once). The schedule
  deliberately excludes track ids for these terminals (outlying multi-track stations carry
  them since May 2023). There is **no public historical CR track dataset** — ours (D1,
  backed up weekly) is the unique asset.
- **Switch/interlocking/yard state is not public** — nothing in any feed reveals the
  platform earlier; that's the structural limit the whole project mapped out.
