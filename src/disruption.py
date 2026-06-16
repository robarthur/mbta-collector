"""Line disruption-risk scoring: an honest read of what is *already happening* on a line
right now (current delays + active alerts), framed as risk — not a prediction. Pure Python
so it's unit-testable under CPython (see predictor.py for the same rationale)."""

# Alerts that on their own mean the line is disrupted (service not running normally).
URGENT_EFFECTS = {"SUSPENSION", "CANCELLATION", "NO_SERVICE"}
# Alerts that signal minor trouble. SHUTTLE is here, not urgent: it's usually planned
# maintenance with a bus replacement (a real heads-up, but not "your line is down").
MINOR_EFFECTS = {"DELAY", "TRACK_CHANGE", "DETOUR", "SHUTTLE"}

LATE_S = 600          # a train is "late" for the share metric at >10 min
DISRUPTED_MAX_MIN = 20    # any train this late => disrupted
DISRUPTED_SHARE = 0.4     # this share of running trains >10 min late => disrupted
MINOR_AVG_MIN = 5         # average delay this high => minor
MINOR_SHARE = 0.2
MIN_TRAINS_FOR_SHARE = 3  # share-of-late needs a real denominator (avoid "1 of 2" at night)


def score_line(stats, alerts):
    """stats: {trains, late_count, avg_delay_min, max_delay_min} for the latest snapshot of
    one line. alerts: list of that line's active alert dicts (need an 'effect' key).
    Returns {level: ok|minor|disrupted, reasons: [str, ...]}."""
    trains = stats.get("trains") or 0
    late = stats.get("late_count") or 0
    avg = stats.get("avg_delay_min") or 0
    mx = stats.get("max_delay_min") or 0
    share = (late / trains) if trains else 0
    effects = {a.get("effect") for a in (alerts or [])}

    reasons = []
    urgent_alert = effects & URGENT_EFFECTS
    if urgent_alert:
        reasons.append("active " + sorted(urgent_alert)[0].replace("_", " ").lower())
    if mx >= DISRUPTED_MAX_MIN:
        reasons.append(f"a train {round(mx)} min late")
    if trains >= MIN_TRAINS_FOR_SHARE and share >= DISRUPTED_SHARE:
        reasons.append(f"{late} of {trains} trains >10 min late")

    if reasons:
        return {"level": "disrupted", "reasons": reasons}

    minor = []
    minor_alert = effects & MINOR_EFFECTS
    if minor_alert:
        minor.append("active " + sorted(minor_alert)[0].replace("_", " ").lower())
    if avg >= MINOR_AVG_MIN:
        minor.append(f"avg delay {round(avg)} min")
    if trains >= MIN_TRAINS_FOR_SHARE and share >= MINOR_SHARE:
        minor.append(f"{late} of {trains} trains >10 min late")
    if minor:
        return {"level": "minor", "reasons": minor}

    return {"level": "ok", "reasons": []}
