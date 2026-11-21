"""Sensors for Smoke Session."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import MATCH_ALL, PERCENTAGE, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import SmokeSessionConfigEntry
from .const import STATE_ACTIVE, STATE_FINISHED, STATE_IDLE
from .engine import ATTR_EVENTS_KEEP, SessionManager, _dt
from .entity import SmokeSessionEntity


def _meat_eta(m: SessionManager) -> tuple[datetime | None, dict[str, Any]]:
    if not m.meat_alerts_armed:
        return None, {}
    t, rate = m.meat_temp, m.meat_rate
    pending = [a for a in m.profile.meat["alerts"] if f"meat:{a['temp']:g}" not in m.session["fired"]]
    if t is None or not pending:
        return None, {}
    target = pending[0]
    attrs = {"target_temp": target["temp"], "target_title": target["title"]}
    if rate is None or rate < 0.5:
        return None, attrs
    return dt_util.utcnow() + timedelta(hours=(target["temp"] - t) / rate), attrs


def _elapsed(m: SessionManager) -> float | None:
    start = _dt(m.session.get("cook_started"))
    if not start or m.session["state"] == STATE_IDLE:
        return None
    end = _dt(m.session.get("finished_at")) or dt_util.utcnow()
    return round((end - start).total_seconds() / 60)


def _finish(m: SessionManager) -> datetime | None:
    if m.session["state"] == STATE_FINISHED:
        return _dt(m.session.get("finished_at"))
    end = m.timeline()[-1]["projected_end"]
    return _dt(end)


def _in_band(m: SessionManager) -> float | None:
    st = m.session.get("stats") or {}
    tracked = st.get("tracked_s") or 0
    return round(100 * st.get("target_s", 0) / tracked, 1) if tracked else None


def _step(m: SessionManager) -> str | None:
    step = m.current_step()
    return step["title"] if step else None


def _step_attrs(m: SessionManager) -> dict[str, Any]:
    step, phase, nxt = m.current_step(), m.current_phase(), m.next_step()
    if not step or not phase:
        return {}
    return {
        "step_id": step["id"],
        "detail": step["detail"],
        "auto": step.get("auto"),
        "step_number": m.session["step_index"] + 1,
        "steps_in_phase": len(phase["steps"]),
        "step_started": m.session.get("step_started"),
        "next_step": nxt["title"] if nxt else None,
    }


def _reminder_attrs(m: SessionManager) -> dict[str, Any]:
    nxt = m.next_reminder()
    return {"title": nxt["title"], "message": nxt["message"]} if nxt else {}


def _status_attrs(m: SessionManager) -> dict[str, Any]:
    """Everything the dashboard card needs, in one place."""
    prof = m.profile
    s = m.session
    phases = []
    for i, (phase, tl) in enumerate(zip(prof.phases, m.timeline())):
        steps = []
        for j, step in enumerate(phase["steps"]):
            if s["state"] == STATE_FINISHED or (s["state"] == STATE_ACTIVE and (i < s["phase_index"] or (i == s["phase_index"] and j < s["step_index"]))):
                status = "done"
            elif s["state"] == STATE_ACTIVE and i == s["phase_index"] and j == s["step_index"]:
                status = "current"
            else:
                status = "todo"
            steps.append({"id": step["id"], "title": step["title"], "status": status})
        phases.append({**tl, "steps": steps})
    nxt = m.next_reminder()
    eta, eta_attrs = _meat_eta(m)
    return {
        "profile_id": prof.id,
        "profile": prof.name,
        "profiles": {p.id: p.name for p in m.profiles.values()},
        "weight_kg": m.weight,
        "pit_entity": m.pit_entity,
        "meat_entity": m.settings.get("meat_probe"),
        "pit": m.pit_temp,
        "meat": m.meat_temp,
        "pit_band": {k: prof.pit[k] for k in ("target_low", "target_high", "alert_low", "alert_high")},
        "pit_status": m.pit_status,
        "pit_trend": m.pit_trend,
        "pit_alerts_armed": m.pit_alerts_armed,
        "lid_recovering": m.suppressed,
        "vent": m.settings["vent"],
        "meat_rate": m.meat_rate,
        "meat_alerts": [{"temp": a["temp"], "title": a["title"], "fired": f"meat:{a['temp']:g}" in s["fired"]} for a in prof.meat["alerts"]],
        "meat_eta": eta.isoformat() if eta else None,
        "meat_eta_target": eta_attrs.get("target_temp"),
        "stall": m.stall,
        "recommendation": m.recommendation(),
        "planned_start": s.get("planned_start") or m.planned_start_dt().isoformat(),
        "cook_started": s.get("cook_started"),
        "finished_at": s.get("finished_at"),
        "elapsed_min": _elapsed(m),
        "phases": phases,
        "current_step": _step_attrs(m) | ({"title": _step(m)} if _step(m) else {}),
        "next_reminder": {"due": nxt["due"].isoformat(), "title": nxt["title"], "message": nxt["message"]} if nxt else None,
        "events": s["events"][-ATTR_EVENTS_KEEP:],
        "summary": s.get("summary"),
        "entities": dict(m.entity_ids),
    }


@dataclass(frozen=True, kw_only=True)
class SmokeSensorDescription(SensorEntityDescription):
    value_fn: Callable[[SessionManager], Any]
    attrs_fn: Callable[[SessionManager], dict[str, Any]] | None = None
    unrecorded: bool = False


SENSORS: tuple[SmokeSensorDescription, ...] = (
    SmokeSensorDescription(
        key="status",
        device_class=SensorDeviceClass.ENUM,
        options=[STATE_IDLE, STATE_ACTIVE, STATE_FINISHED],
        value_fn=lambda m: m.session["state"],
        attrs_fn=_status_attrs,
        unrecorded=True,
    ),
    SmokeSensorDescription(key="phase", value_fn=lambda m: (m.current_phase() or {}).get("name")),
    SmokeSensorDescription(key="current_step", value_fn=_step, attrs_fn=_step_attrs, unrecorded=True),
    SmokeSensorDescription(key="recommendation", value_fn=lambda m: m.recommendation()[:255] if m.active else None),
    SmokeSensorDescription(
        key="pit_status",
        device_class=SensorDeviceClass.ENUM,
        options=["offline", "below", "low", "in_band", "high", "above"],
        value_fn=lambda m: m.pit_status if m.active else None,
    ),
    SmokeSensorDescription(
        key="pit_trend",
        native_unit_of_measurement="°C/10 min",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda m: m.pit_trend if m.active else None,
    ),
    SmokeSensorDescription(
        key="meat_rate",
        native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda m: m.meat_rate if m.meat_alerts_armed else None,
    ),
    SmokeSensorDescription(
        key="meat_eta",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda m: _meat_eta(m)[0],
        attrs_fn=lambda m: _meat_eta(m)[1],
    ),
    SmokeSensorDescription(
        key="next_reminder",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda m: (m.next_reminder() or {}).get("due"),
        attrs_fn=_reminder_attrs,
        unrecorded=True,
    ),
    SmokeSensorDescription(
        key="elapsed",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=_elapsed,
    ),
    SmokeSensorDescription(
        key="projected_finish",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda m: _finish(m) if m.session["state"] != STATE_IDLE else None,
    ),
    SmokeSensorDescription(
        key="pit_in_target",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_in_band,
    ),
    SmokeSensorDescription(
        key="pit_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda m: m.pit_temp,
    ),
    SmokeSensorDescription(
        key="meat_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda m: m.meat_temp,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: SmokeSessionConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities(SmokeSensor(entry.runtime_data, d, entry.title) for d in SENSORS)


class SmokeSensor(SmokeSessionEntity, SensorEntity):
    entity_description: SmokeSensorDescription

    def __init__(self, manager: SessionManager, description: SmokeSensorDescription, title: str) -> None:
        super().__init__(manager, description.key, title)
        self.entity_description = description
        if description.unrecorded:
            self._unrecorded_attributes = frozenset({MATCH_ALL})

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.manager)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        return fn(self.manager) if fn else None
