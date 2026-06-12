"""Departure-platform predictor: hierarchical shrinkage over historical track counts.

Pure Python (no workers/js imports) so it is unit-testable under CPython. NB: passing
CPython tests does not guarantee Pyodide-runtime behaviour (see the JsNull notes in
mbta.py) -- treat tests as covering logic, not runtime quirks.
"""

PREDICT_SINGLE_MIN = 60     # at/above this modal confidence we show a single platform
PREDICT_RANGE_COVERAGE = 80  # else widen to the platforms covering this cumulative share
# Pseudocount strength for hierarchical shrinkage train<-branch<-line. Chosen by LOO sweep
# (2026-06-12, n=2718): k=12 beat k=4 on hit-rate (53.8 vs 52.4), range coverage (82.7 vs
# 75.3 against the 80 target) and mid-band calibration error (3.2 vs 10.2) simultaneously.
SHRINK_K = 12.0


def _track_key(t):
    return (int(t) if t.isdigit() else 9999, t)


def smoothed_dist(train_d, branch_d, line_d, k=SHRINK_K):
    """Hierarchical-shrinkage track probability distribution: the train-level counts are
    smoothed toward the branch distribution, which is smoothed toward the line distribution
    (each via k pseudocounts). Small samples are pulled toward the broader prior, so a train
    seen 3-of-6 on a track no longer claims 50% -- the confidence reflects the real evidence.
    Returns a ranked list of (track, probability) summing to 1, or None if there's no data."""
    tracks = set(train_d) | set(branch_d) | set(line_d)
    if not tracks:
        return None
    line_tot = sum(line_d.values())
    p = ({t: line_d.get(t, 0) / line_tot for t in tracks} if line_tot
         else {t: 1.0 / len(tracks) for t in tracks})
    b_tot = sum(branch_d.values())
    if b_tot + k > 0:  # skip a level with no counts when k=0 (would divide by zero)
        p = {t: (branch_d.get(t, 0) + k * p[t]) / (b_tot + k) for t in tracks}
    t_tot = sum(train_d.values())
    if t_tot + k > 0:
        p = {t: (train_d.get(t, 0) + k * p[t]) / (t_tot + k) for t in tracks}
    return sorted(p.items(), key=lambda kv: -kv[1])


def dist_to_prediction(ranked, basis, n):
    """Shape a ranked (track, prob) distribution into the prediction payload, adding a
    contiguous platform `range` when the modal probability is below PREDICT_SINGLE_MIN."""
    if not ranked:
        return None
    modal_pct = 100 * ranked[0][1]
    out = {"predicted_track": ranked[0][0], "confidence": round(modal_pct),
           "alternatives": [{"track": t, "pct": round(100 * pr)} for t, pr in ranked[:5]],
           "basis": basis, "n_samples": n}
    if modal_pct < PREDICT_SINGLE_MIN:
        chosen, acc = [], 0.0
        for t, pr in ranked:
            chosen.append(t)
            acc += pr
            if 100 * acc >= PREDICT_RANGE_COVERAGE:
                break
        nums = sorted(chosen, key=_track_key)
        out["range"] = {"low": nums[0], "high": nums[-1], "tracks": chosen,
                        "confidence": round(100 * acc)}
    return out


def predict_from(train, branch, line, tn, rp, rid):
    """Predicted departure track from historical priors via hierarchical shrinkage
    (train <- branch <- line). Confidence is the smoothed modal probability, so it is honest
    at low sample sizes; a `range` is added when that probability is below PREDICT_SINGLE_MIN."""
    train_d = (train.get(tn) or {}) if tn else {}
    branch_d = (branch.get(rp) or {}) if rp else {}
    line_d = (line.get(rid) or {}) if rid else {}
    ranked = smoothed_dist(train_d, branch_d, line_d)
    t_tot, b_tot = sum(train_d.values()), sum(branch_d.values())
    basis = "train" if t_tot else "branch" if b_tot else "line"
    return dist_to_prediction(ranked, basis, t_tot or b_tot or sum(line_d.values()))
