# estimated-platform

A data collector for studying **which platform (track) Commuter Rail trains arrive at**
at MBTA **North Station**.

## Why this exists

Arriving CR trains carry **no track** in any public MBTA feed — the track only appears
at/just-before departure (verified: arrivals sit on the generic stop `BNT-0000`, only a
departing train shows `BNT-0000-0x`). There is no public switch/signal state and no
published historical CR track-assignment dataset. So predicting the arrival platform
*early* can only be a probabilistic model trained on data we collect ourselves.

This service is that collector. It logs North Station CR predictions + vehicle movement
every ~15s, records the exact moment each train's track becomes known (with lead time),
tracks live platform occupancy, and reports per-route track bias + lead-time stats. Those
numbers tell us whether an early predictor is even worth building.

## Architecture (fully Python on Cloudflare)

- **`Collector` Durable Object** (`src/entry.py`) — owns the ~15s poll loop via its
  `alarm()`: fetch MBTA → parse → write D1 → reschedule itself. Self-sustaining.
- **`Default` Worker** (`src/entry.py`) — HTTP endpoints (read D1) + keeps the alarm armed.
- **D1** — durable SQLite store (`schema.sql`), bound as `DB`.
- **Cron trigger (1/min)** — backstop that re-arms the alarm if the loop ever stops.

Pure logic lives in `src/mbta.py` (API client + parsing), `src/sql.py`, `src/timeutil.py`.

## Endpoints

| Route | What |
|-------|------|
| `GET /health` | row counts + last poll time |
| `GET /board` | live 10-track occupancy grid + inbound trains (track known? yes/no) |
| `GET /analyze` | per-route track distribution + lead-time-to-arrival/departure summary |
| `GET /poll-once` | force one poll now (debug) |

## Local development

Python Workers must be driven through **`pywrangler`** (from the `workers-py` dev
dependency), which vendors the `pyproject.toml` dependencies (`httpx`) into the worker
bundle before proxying to `wrangler`. Plain `npx wrangler dev` will fail with
`ModuleNotFoundError: httpx`.

```bash
npm install                       # gets wrangler (CLI)
uv sync                           # python deps + pywrangler tooling

# create + seed a LOCAL D1 (d1 execute needs no bundling, so npx wrangler is fine)
npx wrangler d1 execute estimated-platform --local --file schema.sql

uv run pywrangler dev             # runs the Python Worker + DO + local D1
# then:  curl localhost:8787/poll-once   and   curl localhost:8787/board
```

Inspect collected data:

```bash
npx wrangler d1 execute estimated-platform --local \
  --command "select * from track_events"
```

## Deploy

```bash
npx wrangler d1 create estimated-platform        # paste the database_id into wrangler.jsonc
npx wrangler d1 execute estimated-platform --remote --file schema.sql
uv run pywrangler deploy                          # bundles httpx, then deploys
npx wrangler secret put MBTA_API_KEY             # optional; raises rate limit to ~1000/min
```

Once deployed, the DO alarm self-sustains the ~15s loop; the cron backstop re-arms it.

## Notes / caveats

- Runs on the **beta** Python Workers runtime (Pyodide = CPython compiled to WASM,
  running inside the JS isolate). Deps: `httpx` only.
- Pyodide gotcha baked into `_bound()` (`src/entry.py`): Python `None` crosses into JS as
  `undefined`, which D1 rejects. Params are JSON-encoded in Python and `JSON.parse`d in JS
  so `null` survives. (`run_js`/`eval` is unavailable — workerd forbids code-gen.)
- An MBTA API key is optional at this volume (15s polling). Without a key the public
  limit (~20 req/min) is still comfortably enough.
- Cost: D1 + Workers + DO alarms are request/alarm-billed (no always-on compute).
- Expected early finding from `/analyze`: lead-to-arrival clusters near zero/negative —
  i.e. the official feed reveals the track only as the train arrives. That's the gap a
  predictor would try to beat.
