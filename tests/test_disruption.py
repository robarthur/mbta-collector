"""Unit tests for line disruption-risk scoring (src/disruption.py)."""

from disruption import score_line


def test_calm_line_is_ok():
    r = score_line({"trains": 6, "late_count": 0, "avg_delay_min": 1, "max_delay_min": 3}, [])
    assert r["level"] == "ok" and r["reasons"] == []


def test_suspension_alert_is_disrupted_even_when_running_fine():
    r = score_line({"trains": 5, "late_count": 0, "avg_delay_min": 0, "max_delay_min": 1},
                   [{"effect": "SUSPENSION"}])
    assert r["level"] == "disrupted"
    assert any("suspension" in x for x in r["reasons"])


def test_big_single_delay_is_disrupted():
    r = score_line({"trains": 8, "late_count": 1, "avg_delay_min": 4, "max_delay_min": 24}, [])
    assert r["level"] == "disrupted"


def test_widespread_lateness_is_disrupted():
    # 3 of 6 trains >10 min late = 50% share
    r = score_line({"trains": 6, "late_count": 3, "avg_delay_min": 9, "max_delay_min": 14}, [])
    assert r["level"] == "disrupted"


def test_delay_alert_is_minor():
    r = score_line({"trains": 6, "late_count": 0, "avg_delay_min": 2, "max_delay_min": 6},
                   [{"effect": "DELAY"}])
    assert r["level"] == "minor"


def test_elevated_average_is_minor():
    r = score_line({"trains": 6, "late_count": 1, "avg_delay_min": 6, "max_delay_min": 12}, [])
    assert r["level"] == "minor"


def test_info_alert_alone_does_not_raise_level():
    r = score_line({"trains": 6, "late_count": 0, "avg_delay_min": 1, "max_delay_min": 2},
                   [{"effect": "SCHEDULE_CHANGE"}])
    assert r["level"] == "ok"


def test_one_late_train_at_night_not_disrupted_by_share():
    # 1 of 2 running late is a small-sample artifact, not a disrupted line
    r = score_line({"trains": 2, "late_count": 1, "avg_delay_min": 4, "max_delay_min": 12}, [])
    assert r["level"] != "disrupted"


def test_empty_line_is_ok():
    assert score_line({"trains": 0, "late_count": 0, "avg_delay_min": 0, "max_delay_min": 0}, [])["level"] == "ok"
