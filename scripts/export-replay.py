#!/usr/bin/env python3
"""Bake a service day of train_status into static replay JSON for the web app.

The replay view scrubs these files from Pages directly — no D1 queries at demo time
(scrubbing would otherwise full-scan train_status per seek, and an index would push the
free-tier write budget too close to the cap).

Usage:
  # from a local D1 backup (fast, no network):
  uv run python scripts/export-replay.py --backup backups/full-20260610.sql.gz 2026-06-09 2026-06-05
  # from the live database:
  uv run python scripts/export-replay.py --remote 2026-06-12

Output: web/public/replay/<date>.json (+ updates web/public/replay/index.json).
"""
import argparse
import gzip
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "web" / "public" / "replay"
STATUS_CODE = {"IN_TRANSIT_TO": "T", "STOPPED_AT": "S", "INCOMING_AT": "I"}
QUERY = ("SELECT snapshot_ts, trip_id, trip_name, route_id, direction_id, delay_s, "
         "current_status, latitude, longitude FROM train_status WHERE service_date='{d}' "
         "AND latitude IS NOT NULL ORDER BY snapshot_ts")


def rows_from_backup(backup_path, date):
    """Load train_status INSERTs from a D1 .sql.gz export into sqlite, then query."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db = sqlite3.connect(tmp.name)
        db.execute("""CREATE TABLE train_status (snapshot_ts TEXT, service_date TEXT,
            trip_id TEXT, trip_name TEXT, route_id TEXT, route_pattern_id TEXT,
            vehicle_id TEXT, direction_id INTEGER, next_stop_id TEXT, next_stop_seq INTEGER,
            predicted_time TEXT, scheduled_time TEXT, delay_s INTEGER, current_status TEXT,
            reported_status TEXT, latitude REAL, longitude REAL)""")
        pat = re.compile(rb'^INSERT INTO "?train_status')
        cur = db.cursor()
        with gzip.open(backup_path, "rb") as f:
            for line in f:
                if pat.match(line):
                    cur.execute(line.decode("utf-8").rstrip().rstrip(";"))
        db.commit()
        cur = db.execute(QUERY.format(d=date))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def rows_from_remote(date):
    out = subprocess.run(
        ["npx", "wrangler", "d1", "execute", "estimated-platform", "--remote", "--json",
         "--command", QUERY.format(d=date)],
        capture_output=True, text=True, cwd=ROOT, check=True)
    data = json.loads(out.stdout)
    return (data[0] if isinstance(data, list) else data)["results"]


def bake(rows, date):
    times = sorted({r["snapshot_ts"] for r in rows})
    t_idx = {t: i for i, t in enumerate(times)}
    trains = defaultdict(lambda: {"name": None, "route": None, "dir": None, "pts": []})
    for r in rows:
        t = trains[r["trip_id"]]
        t["name"], t["route"], t["dir"] = r["trip_name"], r["route_id"], r["direction_id"]
        t["pts"].append([t_idx[r["snapshot_ts"]],
                         round(r["latitude"], 5), round(r["longitude"], 5),
                         r["delay_s"], STATUS_CODE.get(r["current_status"], "?")])
    # summary label for the day picker
    finals = [t["pts"][-1][3] for t in trains.values() if t["pts"] and t["pts"][-1][3] is not None]
    by_line = defaultdict(list)
    for t in trains.values():
        if t["pts"] and t["pts"][-1][3] is not None:
            by_line[t["route"]].append(t["pts"][-1][3])
    worst = max(by_line.items(), key=lambda kv: sum(kv[1]) / len(kv[1])) if by_line else (None, [0])
    label = (f"{len(trains)} trains · avg final delay "
             f"{sum(finals)/len(finals)/60:+.1f}m · worst: {worst[0][3:] if worst[0] else '?'} "
             f"{sum(worst[1])/len(worst[1])/60:+.1f}m" if finals else f"{len(trains)} trains")
    return {"date": date, "times": times,
            "trains": {k: dict(v) for k, v in trains.items()}}, label


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--backup", help="path to a D1 .sql.gz export")
    src.add_argument("--remote", action="store_true", help="query the live D1")
    ap.add_argument("dates", nargs="+", help="service dates (YYYY-MM-DD)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index_path = OUT_DIR / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"days": []}

    for date in args.dates:
        rows = rows_from_backup(args.backup, date) if args.backup else rows_from_remote(date)
        if not rows:
            print(f"{date}: no rows, skipped", file=sys.stderr)
            continue
        day, label = bake(rows, date)
        out = OUT_DIR / f"{date}.json"
        out.write_text(json.dumps(day, separators=(",", ":")))
        index["days"] = [d for d in index["days"] if d["date"] != date]
        index["days"].append({"date": date, "label": label,
                              "trains": len(day["trains"]), "snapshots": len(day["times"])})
        print(f"{date}: {len(rows)} rows -> {out.name} "
              f"({out.stat().st_size // 1024}KB, {len(day['trains'])} trains, "
              f"{len(day['times'])} snapshots) — {label}")

    index["days"].sort(key=lambda d: d["date"], reverse=True)
    index_path.write_text(json.dumps(index, indent=1))


if __name__ == "__main__":
    main()
