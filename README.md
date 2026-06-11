# estimated-platform

An MBTA Commuter Rail web app with a predictive edge: live departure boards that show the
**platform before the official board posts it**, plus system-wide delays, line reliability,
and train-watch notifications. Runs entirely on Cloudflare (free tier).

**App:** https://estimated-platform.pages.dev · **API:** https://estimated-platform.robarthur1.workers.dev/api/v1

## What it does

- **Station boards** (`/stations`) — Realtime-Trains-style departures + arrivals for all
  148 CR stations (search picker). Platform column: **green = confirmed** by the official
  feed, grey = **timetabled** (outlying multi-track stations carry the track in the
  schedule) or **our prediction** (with honest confidence and sample size; widens to a
  platform *range* like "Plat 1–5 ~83%" when no single track is likely enough).
- **Watch a train** — tap the bell on a departure; get an OS notification the moment its
  platform posts (or it goes >5 min late / is cancelled) while the app is open.
- **Alerts** — service alerts on the board: urgent (delay/cancellation/track change) inline,
  long-running notices collapsed; train-specific alerts tag their row only.
- **Line reliability** (`/lines`) — lines ranked by on-time %, per-day trend, and the active
  alerts that explain the numbers (e.g. Newburyport's 57% next to its trackwork notice).
- **Live map** (`/map`) — positions colored by delay (~2 min freshness).

## Why the platform prediction exists (the interesting part)

At North/South Station the track is assigned by dispatch only **~8 minutes before
departure** — it exists in *no* public feed before that (the schedule deliberately excludes
track ids for these two terminals; we verified the vehicle feed reveals nothing earlier).
There is also **no public historical record** of CR track assignments. So this project runs
its own collector (every 15s since June 2026) and predicts platforms from the accumulated
history with a train→branch→line hierarchical-shrinkage model.

Honest accuracy (leave-one-day-out, `/api/v1/backtest`): **Back Bay ~99%** (scheduled),
**South ~40%**, **North ~25%** (its assignments are genuinely dynamic — the displayed
confidence is calibrated, so a "~60%" call really hits ~60%). The collected dataset itself
is the moat: it exists nowhere else.

## Architecture

```
Pages (React PWA, web/)  ──fetch──▶  Worker /api/v1/* (Python, src/entry.py)
                                       ├─ live proxies: /station /stops /alerts (MBTA V3)
                                       ├─ D1 reads: /trains /delays /history /predict /backtest …
                                       └─ Collector DurableObject: 15s alarm loop
                                            fetch MBTA → detect track resolutions → D1
                                          (cron 1/min re-arms; /health reports staleness)
```

- **Worker** (Python Workers beta / Pyodide, driven via `pywrangler` — bare `wrangler dev`
  fails to bundle `httpx`). Modules: `entry.py` (DO + routes), `mbta.py` (V3 client +
  parsers), `predictor.py` (pure, tested), `sql.py`, `timeutil.py`.
- **D1** stores polls, track-resolution events, berth/board milestones, vehicle arrivals,
  and 2-minute system-wide train status snapshots (~62k rows/day, inside the free tier).
- **Web** (`web/`): React + Vite PWA on Cloudflare Pages; silent auto-update; installable.

See `ARCHITECTURE.md` for the full reference (schema, feeds, endpoints, caveats).

## Development

```bash
# Worker
uv sync
npx wrangler d1 execute estimated-platform --local --file schema.sql
uv run pywrangler dev                 # localhost:8787

# Tests (parsers against captured payloads + predictor math)
uv run --group test pytest

# Web app
cd web && npm install && npm run dev  # talks to prod API via .env.development
```

## Deploy

```bash
rm -rf .wrangler && uv run pywrangler deploy            # Worker (clear stale build cache)
cd web && npm run build && cd ..
npx wrangler pages deploy web/dist --project-name=estimated-platform --branch=main
./scripts/backup-d1.sh                                  # weekly: the data is irreplaceable
```

## Pyodide gotchas (hard-won, do not relearn)

- Python `None` → JS `undefined`, which D1 rejects: params are JSON-round-tripped
  (`_bound()` in `entry.py`).
- The worker's vendored httpx leaves JSON `null` as a **JsNull proxy** (`is None` is False,
  falsy-but-not-None) and **fills `departure_time` even at termini** — terminus/through
  classification must use GTFS `pickup_type`, and presence checks must be
  `isinstance(x, str)`. CPython tests can't catch this class; verify in the deployed Worker.
- `getAlarm()` returns falsy JS null; `scheduled()` must take `*args`; always `await setAlarm`.
