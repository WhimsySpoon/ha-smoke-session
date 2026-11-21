"""Constants for Smoke Session."""

from __future__ import annotations

DOMAIN = "smoke_session"

CONF_PIT_SENSOR = "pit_sensor"
CONF_MEAT_SENSORS = "meat_sensors"
CONF_NOTIFY_SCRIPT = "notify_script"
CONF_IMPORTANT_DESTINATIONS = "important_destinations"
CONF_INFO_DESTINATIONS = "info_destinations"

DEFAULT_NOTIFY_SCRIPT = "script.send_notification"
DESTINATION_OPTIONS = ["aaron", "cogger", "phones", "tv"]
DEFAULT_IMPORTANT_DESTINATIONS = ["aaron", "tv"]
DEFAULT_INFO_DESTINATIONS = ["aaron"]

STORAGE_VERSION = 1

# Session states
STATE_IDLE = "idle"
STATE_ACTIVE = "active"
STATE_FINISHED = "finished"

# Bottom vent positions, in order (index matters for recommendations)
VENT_OPTIONS = ["Closed", "25% open", "50% open", "75% open", "Fully open"]
DEFAULT_VENT = "Fully open"

# Engine timings
TICK_SECONDS = 30
PIT_TREND_WINDOW_MIN = 10
MEAT_RATE_WINDOW_MIN = 30
SAMPLE_KEEP_MIN = 45
PROBE_OFFLINE_MIN = 3
LID_DROP_C = 8.0
LID_DROP_WINDOW_MIN = 3
LATE_REMINDER_GRACE_MIN = 10
STALL_RATE_C_PER_H = 2.0
STALL_MIN_C = 60.0
STALL_MAX_C = 82.0

# Notification tags (phone notifications with the same tag replace each other)
TAG_PIT = "smoke_session_pit"
TAG_PROBE = "smoke_session_probe"
TAG_MEAT = "smoke_session_meat"
TAG_REMINDER = "smoke_session_reminder"
TAG_STEP = "smoke_session_step"

SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"
