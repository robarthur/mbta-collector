"""Unit tests for the hierarchical-shrinkage platform predictor (src/predictor.py)."""

import math

from predictor import (PREDICT_RANGE_COVERAGE, PREDICT_SINGLE_MIN,
                       dist_to_prediction, predict_from, smoothed_dist)


def test_no_data_returns_none():
    assert smoothed_dist({}, {}, {}) is None
    assert predict_from({}, {}, {}, "123", "rp", "rid") is None


def test_probabilities_sum_to_one_and_rank():
    ranked = smoothed_dist({"9": 3, "6": 1}, {"9": 10, "6": 5}, {"9": 20, "6": 10, "1": 5})
    assert math.isclose(sum(p for _, p in ranked), 1.0)
    assert ranked[0][0] == "9"
    assert all(ranked[i][1] >= ranked[i + 1][1] for i in range(len(ranked) - 1))


def test_shrinkage_pulls_small_samples_toward_prior():
    # A train seen 3-for-3 on track 5 must NOT claim 100% when the line spreads evenly.
    line = {"5": 10, "1": 10, "2": 10}
    ranked = smoothed_dist({"5": 3}, {}, line)
    modal = dict(ranked)["5"]
    assert 1 / 3 < modal < 1.0
    # With k=0 (no shrinkage) the raw counts win outright.
    raw = smoothed_dist({"5": 3}, {}, line, k=0)
    assert dict(raw)["5"] == 1.0


def test_more_evidence_increases_confidence():
    line = {"5": 10, "1": 10}
    weak = dict(smoothed_dist({"5": 3}, {}, line))["5"]
    strong = dict(smoothed_dist({"5": 30}, {}, line))["5"]
    assert strong > weak


def test_single_platform_above_threshold_has_no_range():
    p = dist_to_prediction([("9", 0.9), ("6", 0.1)], "train", 20)
    assert p["predicted_track"] == "9" and p["confidence"] == 90
    assert "range" not in p


def test_low_confidence_adds_contiguous_range():
    ranked = [("3", 0.3), ("1", 0.25), ("5", 0.25), ("2", 0.1), ("4", 0.1)]
    p = dist_to_prediction(ranked, "line", 100)
    assert p["confidence"] < PREDICT_SINGLE_MIN
    rng = p["range"]
    assert int(rng["low"]) <= int(rng["high"])
    assert rng["confidence"] >= PREDICT_RANGE_COVERAGE - 1  # rounding slack
    assert set(rng["tracks"]).issubset({t for t, _ in ranked})


def test_basis_reflects_strongest_available_level():
    line = {"1": 10}
    assert predict_from({"42": {"1": 3}}, {}, {"r": line}, "42", None, "r")["basis"] == "train"
    assert predict_from({}, {"b": {"1": 5}}, {"r": line}, "42", "b", "r")["basis"] == "branch"
    assert predict_from({}, {}, {"r": line}, "42", "b", "r")["basis"] == "line"
