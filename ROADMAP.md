# estimated-platform — PoC → App roadmap

Turning the working PoC into a real web/mobile product. See `ARCHITECTURE.md` for the
current system.

## Product thesis
- **Commodity** (must-have, not differentiating): timetables, live status, live train tracking
  — MBTA already publishes this; we re-serve it cleanly.
- **Moat / USP**: the **predictive layer** — platform prediction, real (estimated) delay,
  berth-before-board — built on historical data MBTA doesn't publish, which only our collector
  has. It compounds the longer the collector runs.
- One-liner: *"A clean MBTA Commuter Rail app — that also tells you your platform and how late
  your train will actually be."*

## Decisions (locked)
- **Mobile:** PWA-first — one installable web app, web push; defer native (Expo) until proven.
- **Frontend:** React + Vite, hosted on **Cloudflare Pages**.
- **Keep** the collector (Worker + Durable Object + D1) as the data engine — do not rewrite.

## Target architecture
```
Cloudflare Pages (web/)            Cloudflare Worker (Python)
  React + Vite PWA      ── HTTPS ─▶   /api/v1/*  (CORS + cache)   ──▶  D1
  - map / tracking                    + Collector Durable Object  ◀──  (poll loop)
  - line status                              (the moat)
  - timetables
  - platform predictions
```
Two deploys: the **web app** (Pages) and the **API+collector Worker**. Single source of truth
for data = the Worker API; the app is a pure client.

## Repo layout (monorepo)
```
estimated-platform/
  src/  schema.sql  migrations/  wrangler.jsonc   # the Worker (API + collector) — stays
  web/                                            # NEW: React + Vite PWA (deploys to Pages)
    src/  index.html  package.json  vite.config.ts
  ARCHITECTURE.md  ROADMAP.md
```
(Worker stays at root to minimize churn; `web/` is its own npm project.)

## API formalization (P0)
- Move data routes under **`/api/v1/...`** (keep old paths as temporary aliases).
- Add **CORS** (allow the Pages origin) and **`Cache-Control`** on cacheable reads.
- Group: **reference** (`/routes`, `/stops`, `/timetable`), **live** (`/trains`, `/delays`,
  `/alerts`), **predict** (`/board`, `/predict`, `/turn-lead`), **analytics** (`/history`, `/analyze`).
- Worker stops serving the inline HTML SPA; `/` redirects to the app (or a small landing).

## Phased roadmap

**P0 — Foundations (clean seams).**
- `/api/v1` + CORS + cache headers on the Worker; retire `ui.py` HTML serving.
- Scaffold `web/` (React + Vite + PWA plugin) on Cloudflare Pages.
- Port the 3 existing views to React: Map (react-leaflet/MapLibre via `/trains`), Lines
  (`/delays` + `/history`), Platforms (`/board` + `/predict`). Reach parity with today, in a
  real app shell. Installable PWA.

**P1 — Standard features.**
- **Timetables**: ingest GTFS schedules (routes/stops/stop_times) → `/api/v1/timetable`;
  station & line detail pages with scheduled + live + predicted side by side.
- **Search/nav**: pick a station or line; "next trains" board.
- **Alerts/cancellations**: pull `/alerts`; surface disruptions (a cancelled train currently
  just vanishes from our data).

**P2 — Deepen the USP.**
- **Branch-level + modeled platform prediction** (map inbound→outbound branch; replace simple
  priors with a model) + **published accuracy** (leave-one-day-out backtest endpoint).
- **Downstream delay prediction** (not just current delay — predicted delay at your stop).
- **Web push notifications** (PWA): "your 5:40 will likely board Track 7" / "running ~8 min late."

**P3 — Scale & polish.**
- Custom domain, monitoring/alerting on the collector, data retention (archive old `observations`
  to R2 as D1 grows), accessibility, maybe a native wrapper (Expo) if push/app-store matters.

## Risks / watch-items
- **D1 write budget** (100k/day free) — fine now (~62k); revisit if features add writes; R2 archival in P3.
- **Predicted ≠ actual delay** — consider capturing true arrival actuals (or MBTA LAMP) for honest OTP.
- **North platform exact-track is not predictable** — present North as a *zone* prediction; lead with South where confidence is real.
- **Beta Python Workers runtime** — stable so far; the API layer could move to a TS Worker later if needed (the collector is the part that benefits from staying put).
