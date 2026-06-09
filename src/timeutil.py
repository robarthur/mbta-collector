"""Time helpers. Avoids zoneinfo/tzdata (not guaranteed in Pyodide) by computing
US Eastern offset with the standard DST rule."""

from datetime import datetime, timedelta, timezone

SERVICE_DAY_ROLLOVER_HOURS = 3  # trips before ~3am local count as the previous service day


def now_utc():
    return datetime.now(timezone.utc)


def now_iso():
    return now_utc().isoformat()


def now_ms():
    return int(now_utc().timestamp() * 1000)


def _nth_weekday(year, month, weekday, n):
    """Date of the nth `weekday` (Mon=0..Sun=6) in `month`."""
    first = datetime(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _is_eastern_dst(dt_utc):
    """US Eastern DST: 2nd Sunday March 07:00 UTC .. 1st Sunday Nov 06:00 UTC."""
    y = dt_utc.year
    start = _nth_weekday(y, 3, 6, 2).replace(hour=7, tzinfo=timezone.utc)
    end = _nth_weekday(y, 11, 6, 1).replace(hour=6, tzinfo=timezone.utc)
    return start <= dt_utc < end


def eastern_now(dt_utc=None):
    dt_utc = dt_utc or now_utc()
    offset = -4 if _is_eastern_dst(dt_utc) else -5
    return dt_utc + timedelta(hours=offset)


def eastern_hhmm(dt_utc=None):
    """Current Eastern wall-clock time as 'HH:MM' (for MBTA filter[min_time])."""
    return eastern_now(dt_utc).strftime("%H:%M")


def service_date(dt_utc=None):
    e = eastern_now(dt_utc)
    return (e - timedelta(hours=SERVICE_DAY_ROLLOVER_HOURS)).date().isoformat()


def seconds_ago_iso(seconds):
    return (now_utc() - timedelta(seconds=seconds)).isoformat()


def lead_seconds(target_iso, ref_iso):
    """Seconds from ref to target (both ISO8601, tz-aware). None if target missing/unparseable."""
    if not target_iso:
        return None
    try:
        t = datetime.fromisoformat(target_iso)
        r = datetime.fromisoformat(ref_iso)
        return int((t - r).total_seconds())
    except Exception:
        return None
