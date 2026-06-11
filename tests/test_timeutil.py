"""Unit tests for timeutil (Eastern offset without zoneinfo, service-day rollover)."""

import re
from datetime import datetime, timezone

import timeutil


def test_lead_seconds():
    a = "2026-06-11T10:00:00-04:00"
    b = "2026-06-11T10:05:30-04:00"
    assert timeutil.lead_seconds(b, a) == 330
    assert timeutil.lead_seconds(a, b) == -330
    assert timeutil.lead_seconds(None, a) is None
    assert timeutil.lead_seconds("garbage", a) is None


def test_eastern_dst_offset():
    july = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    january = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    assert timeutil.eastern_now(july).hour == 8    # EDT = UTC-4
    assert timeutil.eastern_now(january).hour == 7  # EST = UTC-5


def test_service_date_rollover_at_3am_eastern():
    # 06:00 UTC in June = 02:00 EDT -> still the previous service day.
    before = datetime(2026, 6, 10, 6, 0, tzinfo=timezone.utc)
    after = datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)   # 04:00 EDT
    assert timeutil.service_date(before) == "2026-06-09"
    assert timeutil.service_date(after) == "2026-06-10"


def test_eastern_hhmm_format():
    assert re.fullmatch(r"\d{2}:\d{2}", timeutil.eastern_hhmm())
