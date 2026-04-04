"""Classify activities into running / cycling categories."""

import logging

log = logging.getLogger("favtracks.classify")

_RUNNING_KEYWORDS = {"running", "lauf", "run", "trail_running", "trail"}
_CYCLING_KEYWORDS = {"cycling", "fahrrad", "radfahrt", "bike", "biking",
                     "mountain_biking", "gravel", "road_biking", "road_cycling",
                     "mountain_bike", "gravel_cycling", "e_bike", "e-bike"}
_EXCLUDE_KEYWORDS = {"indoor", "virtuell", "virtual"}


def classify_activity(activity_type: str | None) -> str | None:
    """Return 'running', 'cycling', or None (excluded / unknown)."""
    if not activity_type:
        return None

    lower = activity_type.lower().strip()

    for kw in _EXCLUDE_KEYWORDS:
        if kw in lower:
            log.debug("Excluding activity type '%s' (matched indoor keyword)", activity_type)
            return None

    for kw in _RUNNING_KEYWORDS:
        if kw in lower:
            return "running"

    for kw in _CYCLING_KEYWORDS:
        if kw in lower:
            return "cycling"

    log.debug("Unknown activity type '%s', skipping", activity_type)
    return None
