"""Cook profiles: loading and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
import yaml

_LOGGER = logging.getLogger(__name__)

PROFILE_DIR = Path(__file__).parent / "profiles"

_STEP = vol.Schema(
    {
        vol.Required("id"): str,
        vol.Required("title"): str,
        vol.Required("detail"): str,
        vol.Optional("log"): str,
        vol.Optional("starts_cook", default=False): bool,
        vol.Optional("opens_lid", default=False): bool,
        vol.Optional("auto"): vol.In(["pit_stable"]),
        vol.Optional("auto_minutes", default=10): vol.All(int, vol.Range(min=1)),
        vol.Optional("due_after_min"): vol.All(int, vol.Range(min=1)),
        vol.Optional("due_message"): str,
    }
)

_REMINDER = vol.Schema(
    {
        vol.Required("id"): str,
        vol.Required("anchor_event"): str,
        vol.Required("start_after_min"): vol.All(int, vol.Range(min=0)),
        vol.Required("every_min"): vol.All(int, vol.Range(min=1)),
        vol.Optional("until_event"): str,
        vol.Required("title"): str,
        vol.Required("message"): str,
    }
)

_PHASE = vol.Schema(
    {
        vol.Required("id"): str,
        vol.Required("name"): str,
        vol.Required("duration_min"): vol.All(int, vol.Range(min=1)),
        vol.Optional("duration_min_per_kg", default=0): vol.Coerce(float),
        vol.Optional("end_prompt"): str,
        vol.Optional("reminders", default=[]): [_REMINDER],
        vol.Required("steps"): vol.All([_STEP], vol.Length(min=1)),
    }
)

PROFILE_SCHEMA = vol.Schema(
    {
        vol.Required("id"): str,
        vol.Required("name"): str,
        vol.Optional("description", default=""): str,
        vol.Optional("sort", default=10): int,
        vol.Required("weight"): {
            vol.Required("default_kg"): vol.Coerce(float),
            vol.Required("min_kg"): vol.Coerce(float),
            vol.Required("max_kg"): vol.Coerce(float),
        },
        vol.Required("pit"): {
            vol.Required("target_low"): vol.Coerce(float),
            vol.Required("target_high"): vol.Coerce(float),
            vol.Required("alert_low"): vol.Coerce(float),
            vol.Required("alert_high"): vol.Coerce(float),
            vol.Required("sustain_min"): vol.All(int, vol.Range(min=1)),
            vol.Required("lid_recovery_min"): vol.All(int, vol.Range(min=0)),
            vol.Required("alerts_from_event"): str,
            vol.Optional("alerts_until_event"): str,
        },
        vol.Required("meat"): {
            vol.Required("alerts_from_event"): str,
            vol.Optional("alerts", default=[]): [
                {
                    vol.Required("temp"): vol.Coerce(float),
                    vol.Required("title"): str,
                    vol.Required("message"): str,
                }
            ],
        },
        vol.Required("phases"): vol.All([_PHASE], vol.Length(min=1)),
        vol.Optional("events", default={}): {str: str},
    }
)


@dataclass
class Profile:
    """A validated cook profile."""

    id: str
    name: str
    description: str
    weight: dict[str, float]
    pit: dict[str, Any]
    meat: dict[str, Any]
    phases: list[dict[str, Any]]
    events: dict[str, str] = field(default_factory=dict)
    sort: int = 10

    def phase_duration(self, index: int, weight_kg: float) -> float:
        """Planned phase duration in minutes for a given weight."""
        phase = self.phases[index]
        return phase["duration_min"] + phase["duration_min_per_kg"] * weight_kg

    def event_label(self, event_type: str) -> str:
        """Human label for an event type."""
        if event_type in self.events:
            return self.events[event_type]
        return BUILTIN_EVENT_LABELS.get(event_type, event_type.replace("_", " ").capitalize())


BUILTIN_EVENT_LABELS = {
    "lid_open": "Lid opened",
    "spritz": "Spritz",
    "probe_check": "Probe check",
    "vent_adjust": "Bottom vents adjusted",
    "note": "Note",
    "session_start": "Session started",
    "session_end": "Session ended",
}


def _check_consistency(data: dict[str, Any]) -> None:
    """Checks the schema can't express. Raises vol.Invalid."""
    pit = data["pit"]
    if not pit["alert_low"] < pit["target_low"] < pit["target_high"] < pit["alert_high"]:
        raise vol.Invalid("pit: need alert_low < target_low < target_high < alert_high")
    step_ids: list[str] = []
    logs: set[str] = set()
    starts = 0
    for phase in data["phases"]:
        for step in phase["steps"]:
            step_ids.append(step["id"])
            if "log" in step:
                logs.add(step["log"])
            if step["starts_cook"]:
                starts += 1
    if len(step_ids) != len(set(step_ids)):
        raise vol.Invalid("step ids must be unique")
    if starts != 1:
        raise vol.Invalid("exactly one step must have starts_cook: true")
    for key, section in (("pit", pit), ("meat", data["meat"])):
        if section["alerts_from_event"] not in logs:
            raise vol.Invalid(f"{key}.alerts_from_event '{section['alerts_from_event']}' is not logged by any step")
    if "alerts_until_event" in pit and pit["alerts_until_event"] not in logs:
        raise vol.Invalid(f"pit.alerts_until_event '{pit['alerts_until_event']}' is not logged by any step")
    for phase in data["phases"]:
        for rem in phase["reminders"]:
            if rem["anchor_event"] not in logs:
                raise vol.Invalid(f"reminder {rem['id']}: anchor_event is not logged by any step")
            if "until_event" in rem and rem["until_event"] not in logs:
                raise vol.Invalid(f"reminder {rem['id']}: until_event is not logged by any step")


def load_profiles(directory: Path = PROFILE_DIR) -> dict[str, Profile]:
    """Load every profile in the directory. Runs in the executor.

    An invalid profile is logged as an error and skipped, so one bad file
    can't take the others down. No valid profiles at all raises.
    """
    profiles: dict[str, Profile] = {}
    for path in sorted(directory.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            data = PROFILE_SCHEMA(raw)
            _check_consistency(data)
        except (OSError, yaml.YAMLError, vol.Invalid) as err:
            _LOGGER.error("Cook profile %s is invalid and was skipped: %s", path.name, err)
            continue
        if data["id"] in profiles:
            _LOGGER.error("Cook profile %s duplicates id '%s' and was skipped", path.name, data["id"])
            continue
        profiles[data["id"]] = Profile(**data)
    if not profiles:
        raise ValueError(f"No valid cook profiles found in {directory}")
    return dict(sorted(profiles.items(), key=lambda kv: (kv[1].sort, kv[1].name)))
