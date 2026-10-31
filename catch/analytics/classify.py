from __future__ import annotations

# Garmin activityType typeKeys for rowing. Session 2's ROWING_TYPE_KEYS = {"rowing_v2",
# "indoor_rowing"} (used to match a Concept2 result to its Garmin counterpart within a
# 2-minute window) was written when the live Concept2 account had 0 results, so it was never
# actually exercised against real data. Querying the live DB this session
# (SELECT type, SUM(raw_json LIKE '%startLatitude%') FROM activities GROUP BY type) shows
# every real "rowing_v2" row (29/29) carries GPS fields -> on-water, while "indoor_rowing"
# (2/2) carries none -> erg. Fixed here; sync/concept2_client.py now imports GARMIN_ERG_TYPES
# instead of defining its own (wrong) set.
GARMIN_ERG_TYPES = {"indoor_rowing"}
GARMIN_ON_WATER_TYPES = {"rowing_v2"}

# Concept2 result `type` (docs/concept2-endpoints.md): rower/skierg/bike/dynamic/slides/
# multierg are all indoor ergometers; water/paddle are on-water (SpeedCoach); snow/rollerski
# are outdoor but not on water.
CONCEPT2_ON_WATER_TYPES = {"water", "paddle"}
CONCEPT2_OTHER_TYPES = {"snow", "rollerski"}

WORKOUT_CATEGORIES = ("erg", "on_water", "other")


def workout_category(source: str | None, type_: str | None) -> str:
    """One of "erg" / "on_water" / "other" for the Workouts list filter. A documented
    heuristic, not an invented API field — grounded in the live-verified type sets above."""
    if source == "concept2":
        if type_ in CONCEPT2_ON_WATER_TYPES:
            return "on_water"
        if type_ in CONCEPT2_OTHER_TYPES:
            return "other"
        return "erg"
    if source == "garmin":
        if type_ in GARMIN_ERG_TYPES:
            return "erg"
        if type_ in GARMIN_ON_WATER_TYPES:
            return "on_water"
        return "other"
    return "other"
