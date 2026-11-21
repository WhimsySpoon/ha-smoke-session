"""The cook session engine: steps, timeline, alerts, recommendations and the log."""

from __future__ import annotations

from collections import deque
from datetime import datetime, time, timedelta
import logging
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_IMPORTANT_DESTINATIONS,
    CONF_INFO_DESTINATIONS,
    CONF_MEAT_SENSORS,
    CONF_NOTIFY_SCRIPT,
    CONF_PIT_SENSOR,
    DEFAULT_VENT,
    DOMAIN,
    LATE_REMINDER_GRACE_MIN,
    LID_DROP_C,
    LID_DROP_WINDOW_MIN,
    MEAT_RATE_WINDOW_MIN,
    PIT_TREND_WINDOW_MIN,
    PROBE_OFFLINE_MIN,
    SAMPLE_KEEP_MIN,
    SIGNAL_UPDATE,
    STALL_MAX_C,
    STALL_MIN_C,
    STALL_RATE_C_PER_H,
    STATE_ACTIVE,
    STATE_FINISHED,
    STATE_IDLE,
    STORAGE_VERSION,
    TAG_MEAT,
    TAG_PIT,
    TAG_PROBE,
    TAG_REMINDER,
    TAG_STEP,
    TICK_SECONDS,
    VENT_OPTIONS,
)
from .profile import Profile

_LOGGER = logging.getLogger(__name__)

LID_EVENT_TYPES = {"lid_open", "spritz", "probe_check"}
USER_EVENT_TYPES = ["lid_open", "spritz", "probe_check", "note"]
HISTORY_KEEP = 20
ATTR_EVENTS_KEEP = 40


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return dt_util.parse_datetime(value) if value else None


def _slope_per_min(samples: deque[tuple[datetime, float]], now: datetime, window_min: float) -> float | None:
    """Least-squares slope in °C per minute over the window, or None if too little data."""
    start = now - timedelta(minutes=window_min)
    pts = [(ts, v) for ts, v in samples if ts >= start]
    if len(pts) < 3:
        return None
    span = (pts[-1][0] - pts[0][0]).total_seconds() / 60
    if span < window_min * 0.5:
        return None
    xs = [(ts - pts[0][0]).total_seconds() / 60 for ts, _ in pts]
    ys = [v for _, v in pts]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


class SessionManager:
    """Owns one smoker's session state. All methods run in the event loop."""

    def __init__(self, hass: HomeAssistant, entry_id: str, options: dict[str, Any], profiles: dict[str, Profile]) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.options = options
        self.profiles = profiles
        self.pit_entity: str = options[CONF_PIT_SENSOR]
        self.meat_entities: list[str] = list(options.get(CONF_MEAT_SENSORS) or [])
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
        self.entity_ids: dict[str, str] = {}
        self._unsubs: list[Any] = []
        self._pit_samples: deque[tuple[datetime, float]] = deque()
        self._meat_samples: deque[tuple[datetime, float]] = deque()
        self._pit_out_since: datetime | None = None
        self._pit_offline_since: datetime | None = None
        self._meat_offline_since: datetime | None = None
        self._drift: str | None = None
        self._last_tick: datetime | None = None
        first = next(iter(profiles.values()))
        self.settings: dict[str, Any] = {
            "profile_id": first.id,
            "weight_kg": first.weight["default_kg"],
            "planned_start": "11:00:00",
            "vent": DEFAULT_VENT,
            "meat_probe": self.meat_entities[0] if self.meat_entities else None,
        }
        self.session: dict[str, Any] = self._blank_session()
        self.history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ setup

    @staticmethod
    def _blank_session() -> dict[str, Any]:
        return {"state": STATE_IDLE, "events": [], "fired": []}

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data:
            self.settings.update(data.get("settings", {}))
            self.session = data.get("session") or self._blank_session()
            self.history = data.get("history", [])
        if self.settings["profile_id"] not in self.profiles:
            self.settings["profile_id"] = next(iter(self.profiles))
        if self.settings.get("meat_probe") not in self.meat_entities:
            self.settings["meat_probe"] = self.meat_entities[0] if self.meat_entities else None
        if self.session["state"] == STATE_ACTIVE and self.session.get("profile_id") not in self.profiles:
            _LOGGER.error("Active session uses profile '%s', which no longer exists; ending it", self.session.get("profile_id"))
            self.session["state"] = STATE_FINISHED

    @callback
    def async_start(self) -> None:
        sensors = [self.pit_entity, *self.meat_entities]
        self._unsubs.append(async_track_state_change_event(self.hass, sensors, self._on_probe_change))
        self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, timedelta(seconds=TICK_SECONDS)))
        now = dt_util.utcnow()
        for entity_id in sensors:
            self._record_sample(entity_id, now)
        self._last_tick = now
        self._changed()  # all entities exist now, so the status sensor can list them

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        return {"settings": self.settings, "session": self.session, "history": self.history}

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(self._data, 2)

    @callback
    def _changed(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self.entry_id))

    # ------------------------------------------------------------- accessors

    @property
    def active(self) -> bool:
        return self.session["state"] == STATE_ACTIVE

    @property
    def profile(self) -> Profile:
        pid = self.session["profile_id"] if self.session["state"] != STATE_IDLE else self.settings["profile_id"]
        return self.profiles[pid]

    @property
    def weight(self) -> float:
        return float(self.session.get("weight_kg") or self.settings["weight_kg"]) if self.active else float(self.settings["weight_kg"])

    def logged(self, event_type: str) -> bool:
        return any(e["type"] == event_type for e in self.session["events"])

    def last_event(self, event_type: str) -> dict[str, Any] | None:
        for e in reversed(self.session["events"]):
            if e["type"] == event_type:
                return e
        return None

    def _read(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        unit = state.attributes.get("unit_of_measurement")
        if unit == UnitOfTemperature.FAHRENHEIT:
            value = TemperatureConverter.convert(value, UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS)
        return round(value, 1)

    @property
    def pit_temp(self) -> float | None:
        return self._read(self.pit_entity)

    @property
    def meat_temp(self) -> float | None:
        return self._read(self.settings.get("meat_probe"))

    @property
    def pit_trend(self) -> float | None:
        """°C per 10 minutes."""
        slope = _slope_per_min(self._pit_samples, dt_util.utcnow(), PIT_TREND_WINDOW_MIN)
        return None if slope is None else round(slope * 10, 1)

    @property
    def meat_rate(self) -> float | None:
        """°C per hour."""
        slope = _slope_per_min(self._meat_samples, dt_util.utcnow(), MEAT_RATE_WINDOW_MIN)
        return None if slope is None else round(slope * 60, 1)

    @property
    def pit_alerts_armed(self) -> bool:
        pit = self.profile.pit
        if not self.active or not self.logged(pit["alerts_from_event"]):
            return False
        until = pit.get("alerts_until_event")
        return not (until and self.logged(until))

    @property
    def meat_alerts_armed(self) -> bool:
        if not self.active or not self.logged(self.profile.meat["alerts_from_event"]):
            return False
        until = self.profile.pit.get("alerts_until_event")
        return not (until and self.logged(until))

    @property
    def suppressed(self) -> bool:
        until = _dt(self.session.get("suppress_until"))
        return bool(until and dt_util.utcnow() < until)

    @property
    def pit_status(self) -> str:
        t = self.pit_temp
        if t is None:
            return "offline"
        p = self.profile.pit
        if t < p["alert_low"]:
            return "below"
        if t < p["target_low"]:
            return "low"
        if t <= p["target_high"]:
            return "in_band"
        if t <= p["alert_high"]:
            return "high"
        return "above"

    @property
    def stall(self) -> bool:
        if not self.meat_alerts_armed:
            return False
        t, rate = self.meat_temp, self.meat_rate
        return t is not None and rate is not None and STALL_MIN_C <= t <= STALL_MAX_C and rate < STALL_RATE_C_PER_H

    # ------------------------------------------------------------ steps/plan

    def current_phase(self) -> dict[str, Any] | None:
        if not self.active:
            return None
        return self.profile.phases[self.session["phase_index"]]

    def current_step(self) -> dict[str, Any] | None:
        phase = self.current_phase()
        return phase["steps"][self.session["step_index"]] if phase else None

    def next_step(self) -> dict[str, Any] | None:
        if not self.active:
            return None
        pi, si = self.session["phase_index"], self.session["step_index"] + 1
        phases = self.profile.phases
        if si >= len(phases[pi]["steps"]):
            pi, si = pi + 1, 0
        return phases[pi]["steps"][si] if pi < len(phases) else None

    def planned_start_dt(self, now: datetime | None = None) -> datetime:
        """Next sensible occurrence of the planned start time (local)."""
        now = now or dt_util.now()
        hh, mm, ss = (int(x) for x in str(self.settings["planned_start"]).split(":"))
        local_now = dt_util.as_local(now)
        candidate = local_now.replace(hour=hh, minute=mm, second=ss, microsecond=0)
        if candidate < local_now - timedelta(hours=1):
            candidate += timedelta(days=1)
        return candidate

    def timeline(self) -> list[dict[str, Any]]:
        """Planned and projected start/end for every phase."""
        prof = self.profile
        w = self.weight
        now = dt_util.utcnow()
        planned_anchor = _dt(self.session.get("planned_start")) if self.session["state"] != STATE_IDLE else None
        planned_anchor = planned_anchor or self.planned_start_dt()
        started = self.session.get("phase_started", {})
        ended = self.session.get("phase_ended", {})
        cook_started = _dt(self.session.get("cook_started"))
        out: list[dict[str, Any]] = []
        plan_t = planned_anchor
        proj_t: datetime = cook_started or max(now, planned_anchor)
        for i, phase in enumerate(prof.phases):
            dur = timedelta(minutes=prof.phase_duration(i, w))
            a_start = _dt(started.get(str(i)))
            a_end = _dt(ended.get(str(i)))
            p_start = a_start or proj_t
            if a_end:
                p_end = a_end
            elif a_start:
                p_end = max(now, a_start + dur)
            else:
                p_end = p_start + dur
            out.append(
                {
                    "id": phase["id"],
                    "name": phase["name"],
                    "duration_min": round(dur.total_seconds() / 60),
                    "planned_start": _iso(plan_t),
                    "planned_end": _iso(plan_t + dur),
                    "actual_start": _iso(a_start),
                    "actual_end": _iso(a_end),
                    "projected_start": _iso(p_start),
                    "projected_end": _iso(p_end),
                    "status": "done" if a_end else ("current" if a_start or (self.active and i == self.session["phase_index"]) else "todo"),
                }
            )
            plan_t = plan_t + dur
            proj_t = p_end
        return out

    # --------------------------------------------------------------- actions

    def _require_active(self) -> None:
        if not self.active:
            raise ServiceValidationError("No smoke session is running. Start one first.")

    @callback
    def set_setting(self, key: str, value: Any) -> None:
        if key == "profile_id":
            if self.active:
                raise ServiceValidationError("End the current session before changing the cook.")
            if value not in self.profiles:
                raise ServiceValidationError(f"Unknown cook profile '{value}'")
            self.settings["profile_id"] = value
            self.settings["weight_kg"] = self.profiles[value].weight["default_kg"]
        elif key == "planned_start" and self.active and self.session.get("cook_started"):
            raise ServiceValidationError("The cook has already started.")
        else:
            self.settings[key] = value
        if key == "meat_probe":
            self._meat_samples.clear()
            self._record_sample(value, dt_util.utcnow())
        if key == "weight_kg" and self.active:
            self.session["weight_kg"] = value
        if key == "planned_start" and self.active:
            self.session["planned_start"] = _iso(self.planned_start_dt())
        if key == "vent" and self.active and self.session.get("cook_started"):
            self._log("vent_adjust", note=f"Bottom vents {value}", source="user")
        self._save()
        self._changed()

    @callback
    def start_session(self, profile_id: str | None = None, weight_kg: float | None = None, planned_start: time | None = None) -> None:
        if self.active:
            raise ServiceValidationError("A smoke session is already running. End it first.")
        if profile_id is not None:
            self.set_setting("profile_id", profile_id)
        if weight_kg is not None:
            self.settings["weight_kg"] = weight_kg
        if planned_start is not None:
            self.settings["planned_start"] = planned_start.strftime("%H:%M:%S")
        prof = self.profiles[self.settings["profile_id"]]
        w = float(self.settings["weight_kg"])
        if not prof.weight["min_kg"] <= w <= prof.weight["max_kg"]:
            raise ServiceValidationError(
                f"{prof.name} needs a weight between {prof.weight['min_kg']} and {prof.weight['max_kg']} kg (got {w})."
            )
        now = dt_util.utcnow()
        self.session = {
            "state": STATE_ACTIVE,
            "profile_id": prof.id,
            "weight_kg": w,
            "armed_at": _iso(now),
            "planned_start": _iso(self.planned_start_dt()),
            "cook_started": None,
            "phase_index": 0,
            "step_index": 0,
            "step_started": _iso(now),
            "phase_started": {},
            "phase_ended": {},
            "auto_since": None,
            "suppress_until": None,
            "pit_alerted": None,
            "events": [],
            "fired": [],
            "stats": {"tracked_s": 0, "target_s": 0, "alert_s": 0, "pit_min": None, "pit_max": None},
        }
        self._pit_out_since = None
        self._drift = None
        self._log("session_start", note=f"{prof.name}, {w} kg, planned start {self.settings['planned_start'][:5]}", source="user")
        self._save()
        self._changed()

    @callback
    def complete_step(self, source: str = "user") -> None:
        self._require_active()
        step = self.current_step()
        assert step is not None
        now = dt_util.utcnow()
        s = self.session
        if step["starts_cook"]:
            s["cook_started"] = _iso(now)
            s["phase_started"]["0"] = _iso(now)
        if "log" in step:
            self._log(step["log"], source="auto" if source == "auto" else "step", opens_lid=step["opens_lid"])
        elif step["opens_lid"]:
            self._suppress(now)
        phases = self.profile.phases
        s["step_index"] += 1
        s["auto_since"] = None
        s["step_started"] = _iso(now)
        if s["step_index"] >= len(phases[s["phase_index"]]["steps"]):
            s["phase_ended"][str(s["phase_index"])] = _iso(now)
            s["phase_index"] += 1
            s["step_index"] = 0
            if s["phase_index"] >= len(phases):
                s["phase_index"] = len(phases) - 1
                s["step_index"] = len(phases[-1]["steps"]) - 1
                self._finish(now, None)
                return
            s["phase_started"][str(s["phase_index"])] = _iso(now)
        self._save()
        self._changed()

    @callback
    def log_event(self, event_type: str, note: str | None = None) -> None:
        self._require_active()
        if event_type not in USER_EVENT_TYPES:
            raise ServiceValidationError(f"Event type must be one of {', '.join(USER_EVENT_TYPES)}")
        if event_type == "note" and not (note and note.strip()):
            raise ServiceValidationError("A note needs some text.")
        self._log(event_type, note=note, source="user", opens_lid=event_type in LID_EVENT_TYPES)
        self._save()
        self._changed()

    @callback
    def end_session(self, notes: str | None = None) -> None:
        self._require_active()
        self._finish(dt_util.utcnow(), notes)

    @callback
    def reset(self) -> None:
        if self.active:
            raise ServiceValidationError("End the current session before resetting.")
        self.session = self._blank_session()
        self._save()
        self._changed()

    def _finish(self, now: datetime, notes: str | None) -> None:
        self._log("session_end", note=notes, source="user")
        self.session["state"] = STATE_FINISHED
        self.session["finished_at"] = _iso(now)
        if notes:
            self.session["notes"] = notes
        self.session["summary"] = self.summary()
        self.history.append({k: v for k, v in self.session.items() if k != "fired"})
        self.history = self.history[-HISTORY_KEEP:]
        self._save()
        self._changed()

    def _log(self, event_type: str, note: str | None = None, source: str = "user", opens_lid: bool = False) -> None:
        now = dt_util.utcnow()
        self.session["events"].append(
            {
                "ts": _iso(now),
                "type": event_type,
                "label": self.profile.event_label(event_type),
                "pit": self.pit_temp,
                "meat": self.meat_temp,
                "note": note,
                "source": source,
                "lid": opens_lid,
            }
        )
        if opens_lid:
            self._suppress(now)

    def _suppress(self, now: datetime) -> None:
        self.session["suppress_until"] = _iso(now + timedelta(minutes=self.profile.pit["lid_recovery_min"]))
        self._drift = None

    def summary(self) -> dict[str, Any]:
        """Numbers for post-cook analysis."""
        st = self.session.get("stats", {})
        tracked = st.get("tracked_s") or 0
        events = self.session["events"]

        def at(event_type: str) -> dict[str, Any] | None:
            e = next((x for x in events if x["type"] == event_type), None)
            return {"ts": e["ts"], "pit": e["pit"], "meat": e["meat"]} if e else None

        cook_started = _dt(self.session.get("cook_started"))
        stable = at(self.profile.pit["alerts_from_event"])
        return {
            "profile": self.profile.name,
            "weight_kg": self.session.get("weight_kg"),
            "cook_started": self.session.get("cook_started"),
            "minutes_to_stable": round((_dt(stable["ts"]) - cook_started).total_seconds() / 60) if stable and cook_started else None,
            "pit_in_target_pct": round(100 * st.get("target_s", 0) / tracked, 1) if tracked else None,
            "pit_in_alert_band_pct": round(100 * st.get("alert_s", 0) / tracked, 1) if tracked else None,
            "pit_min": st.get("pit_min"),
            "pit_max": st.get("pit_max"),
            "lid_openings": sum(1 for e in events if e.get("lid")),
            "vent_adjustments": sum(1 for e in events if e["type"] == "vent_adjust"),
            "phases": [
                {"name": p["name"], "start": p["actual_start"], "end": p["actual_end"], "planned_min": p["duration_min"]}
                for p in self.timeline()
            ],
            "key_events": {k: at(k) for k in self.profile.events},
        }

    # ------------------------------------------------------------ evaluation

    @callback
    def _record_sample(self, entity_id: str, now: datetime) -> None:
        value = self._read(entity_id)
        if value is None:
            return
        if entity_id == self.pit_entity:
            buf = self._pit_samples
        elif entity_id == self.settings.get("meat_probe"):
            buf = self._meat_samples
        else:
            return
        buf.append((now, value))
        cutoff = now - timedelta(minutes=SAMPLE_KEEP_MIN)
        while buf and buf[0][0] < cutoff:
            buf.popleft()

    @callback
    def _on_probe_change(self, event: Event[EventStateChangedData]) -> None:
        now = dt_util.utcnow()
        entity_id = event.data["entity_id"]
        self._record_sample(entity_id, now)
        if entity_id == self.pit_entity:
            self._check_lid(now)
        self._evaluate(now)
        self._changed()

    @callback
    def _on_tick(self, now: datetime) -> None:
        now = dt_util.utcnow()
        self._accumulate(now)
        self._evaluate(now)
        self._changed()

    def _accumulate(self, now: datetime) -> None:
        last, self._last_tick = self._last_tick, now
        if not last or not self.pit_alerts_armed:
            return
        t = self.pit_temp
        if t is None:
            return
        dt_s = min((now - last).total_seconds(), TICK_SECONDS * 4)
        st = self.session["stats"]
        p = self.profile.pit
        st["tracked_s"] += dt_s
        if p["target_low"] <= t <= p["target_high"]:
            st["target_s"] += dt_s
        if p["alert_low"] <= t <= p["alert_high"]:
            st["alert_s"] += dt_s
        st["pit_min"] = t if st["pit_min"] is None else min(st["pit_min"], t)
        st["pit_max"] = t if st["pit_max"] is None else max(st["pit_max"], t)
        self._save()

    def _check_lid(self, now: datetime) -> None:
        if not self.pit_alerts_armed or self.suppressed:
            return
        t = self.pit_temp
        if t is None:
            return
        window = now - timedelta(minutes=LID_DROP_WINDOW_MIN)
        recent = [v for ts, v in self._pit_samples if ts >= window]
        if recent and max(recent) - t >= LID_DROP_C:
            self._log("lid_open", note=f"Detected: pit dropped {max(recent) - t:.0f}°C in {LID_DROP_WINDOW_MIN} min", source="detected", opens_lid=True)
            self._save()

    def _evaluate(self, now: datetime) -> None:
        if not self.active:
            return
        try:
            self._eval_auto_step(now)
            if not self.active:
                return
            self._eval_probes_offline(now)
            self._eval_pit(now)
            self._eval_meat()
            self._eval_due(now)
        except HomeAssistantError:
            raise
        except Exception:  # fail loudly, but don't kill the tick loop
            _LOGGER.exception("Smoke Session evaluation failed")

    def _eval_auto_step(self, now: datetime) -> None:
        step = self.current_step()
        if not step or step.get("auto") != "pit_stable" or not self.session.get("cook_started"):
            return
        p = self.profile.pit
        t = self.pit_temp
        if t is not None and p["target_low"] <= t <= p["target_high"]:
            since = _dt(self.session.get("auto_since"))
            if since is None:
                self.session["auto_since"] = _iso(now)
                self._save()
            elif now - since >= timedelta(minutes=step["auto_minutes"]):
                nxt = self.next_step()
                self.complete_step(source="auto")
                self._notify(
                    "Pit is stable",
                    f"The pit has held {p['target_low']:.0f}–{p['target_high']:.0f}°C for {step['auto_minutes']} minutes "
                    f"(now {t:.0f}°C). Pit alerts are on." + (f" Next: {nxt['title']}." if nxt else ""),
                    important=False,
                    tag=TAG_STEP,
                    icon="mdi:grill",
                )
        elif self.session.get("auto_since"):
            self.session["auto_since"] = None
            self._save()

    def _eval_probes_offline(self, now: datetime) -> None:
        checks = []
        if self.session.get("cook_started") and (self.pit_alerts_armed or not self.logged(self.profile.pit["alerts_from_event"])):
            checks.append(("pit", self.pit_entity, "Pit probe"))
        if self.meat_alerts_armed:
            checks.append(("meat", self.settings.get("meat_probe"), "Meat probe"))
        for key, entity_id, label in checks:
            attr = f"_{key}_offline_since"
            offline = self._read(entity_id) is None
            since = getattr(self, attr)
            fired_key = f"offline:{key}"
            if offline:
                if since is None:
                    setattr(self, attr, now)
                elif now - since >= timedelta(minutes=PROBE_OFFLINE_MIN) and fired_key not in self.session["fired"]:
                    self.session["fired"].append(fired_key)
                    self._notify(
                        f"{label} offline",
                        f"No reading from the {label.lower()} for {PROBE_OFFLINE_MIN} minutes. Check the Inkbird is on, "
                        "the probe is plugged in and the unit is in Bluetooth range.",
                        important=True,
                        tag=TAG_PROBE,
                        icon="mdi:thermometer-off",
                    )
                    self._save()
            else:
                setattr(self, attr, None)
                if fired_key in self.session["fired"]:
                    self.session["fired"].remove(fired_key)
                    self._notify(f"{label} back", f"The {label.lower()} is reading again.", important=False, tag=TAG_PROBE, icon="mdi:thermometer")
                    self._save()

    def _eval_pit(self, now: datetime) -> None:
        p = self.profile.pit
        t = self.pit_temp
        if not self.pit_alerts_armed or t is None:
            self._pit_out_since = None
            return
        out = "low" if t < p["alert_low"] else "high" if t > p["alert_high"] else None
        if out:
            if self._pit_out_since is None:
                self._pit_out_since = now
            since = self._pit_out_since
            sup = _dt(self.session.get("suppress_until"))
            if sup and sup > since:
                since = sup
            if now >= since + timedelta(minutes=p["sustain_min"]) and self.session.get("pit_alerted") != out:
                self.session["pit_alerted"] = out
                word = "too cold" if out == "low" else "too hot"
                limit = p["alert_low"] if out == "low" else p["alert_high"]
                self._notify(
                    f"Pit {word}: {t:.0f}°C",
                    f"The pit has been {'below' if out == 'low' else 'above'} {limit:.0f}°C for {p['sustain_min']} minutes. "
                    f"{self.recommendation()}",
                    important=True,
                    tag=TAG_PIT,
                    icon="mdi:thermometer-alert",
                )
                self._save()
            return
        self._pit_out_since = None
        if self.session.get("pit_alerted"):
            self.session["pit_alerted"] = None
            self._notify("Pit back in range", f"The pit is back at {t:.0f}°C.", important=False, tag=TAG_PIT, icon="mdi:thermometer-check")
            self._save()
        # Early warning: in range now, but heading out within 15 minutes
        trend = self.pit_trend
        drift = None
        if trend is not None and not self.suppressed:
            projected = t + trend * 1.5
            if trend <= -1 and projected < p["alert_low"]:
                drift = "low"
            elif trend >= 1 and projected > p["alert_high"]:
                drift = "high"
        if drift and drift != self._drift:
            self._notify(
                f"Pit drifting {'down' if drift == 'low' else 'up'}",
                f"{t:.0f}°C and {'falling' if drift == 'low' else 'rising'} {abs(trend):.1f}°C every 10 minutes. {self.recommendation()}",
                important=False,
                tag=TAG_PIT,
                icon="mdi:trending-down" if drift == "low" else "mdi:trending-up",
            )
        self._drift = drift

    def _eval_meat(self) -> None:
        if not self.meat_alerts_armed:
            return
        t = self.meat_temp
        if t is None:
            return
        for alert in self.profile.meat["alerts"]:
            key = f"meat:{alert['temp']:g}"
            if t >= alert["temp"] and key not in self.session["fired"]:
                self.session["fired"].append(key)
                self._notify(alert["title"], alert["message"].format(meat=f"{t:.0f}"), important=True, tag=TAG_MEAT, icon="mdi:food-steak")
                self._save()

    def due_items(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Scheduled reminders that are, or will next be, due."""
        now = now or dt_util.utcnow()
        if not self.active:
            return []
        items: list[dict[str, Any]] = []
        prof = self.profile
        s = self.session
        if not s.get("cook_started"):
            start = _dt(s["planned_start"])
            first = next(st for ph in prof.phases for st in ph["steps"] if st["starts_cook"])
            prep = prof.phases[0]["steps"][0]
            items.append({"key": "plan:prep", "due": start - timedelta(minutes=15), "title": f"{prof.name} starts in 15 minutes", "message": f"{prep['title']}: {prep['detail']}"})
            items.append({"key": "plan:start", "due": start, "title": f"Time to start: {first['title']}", "message": first["detail"]})
        for phase in prof.phases:
            for rem in phase["reminders"]:
                anchor = self.last_event(rem["anchor_event"])
                if not anchor or ("until_event" in rem and self.logged(rem["until_event"])):
                    continue
                last = self.last_event(rem["id"])
                if last and last["ts"] > anchor["ts"]:
                    due = _dt(last["ts"]) + timedelta(minutes=rem["every_min"])
                else:
                    due = _dt(anchor["ts"]) + timedelta(minutes=rem["start_after_min"])
                items.append({"key": f"rem:{rem['id']}:{_iso(due)}", "due": due, "title": rem["title"], "message": rem["message"]})
        step = self.current_step()
        if step and "due_after_min" in step:
            due = _dt(s["step_started"]) + timedelta(minutes=step["due_after_min"])
            items.append({"key": f"step:{step['id']}", "due": due, "title": step["title"], "message": step.get("due_message", step["detail"])})
        phase = self.current_phase()
        pstart = _dt(s["phase_started"].get(str(s["phase_index"])))
        if phase and pstart and phase.get("end_prompt"):
            due = pstart + timedelta(minutes=prof.phase_duration(s["phase_index"], self.weight))
            items.append({"key": f"phase_end:{phase['id']}", "due": due, "title": f"{phase['name']}: planned time is up", "message": phase["end_prompt"]})
        return [i for i in items if i["key"] not in s["fired"]]

    def next_reminder(self) -> dict[str, Any] | None:
        items = self.due_items()
        return min(items, key=lambda i: i["due"]) if items else None

    def _eval_due(self, now: datetime) -> None:
        for item in self.due_items(now):
            if item["due"] > now:
                continue
            self.session["fired"].append(item["key"])
            self._save()
            if now - item["due"] > timedelta(minutes=LATE_REMINDER_GRACE_MIN):
                _LOGGER.info("Skipping stale reminder %s (was due %s)", item["key"], item["due"])
                continue
            self._notify(item["title"], item["message"], important=False, tag=TAG_REMINDER, icon="mdi:bell-ring")

    # -------------------------------------------------------- recommendation

    def recommendation(self) -> str:
        if self.session["state"] == STATE_FINISHED:
            return "Cook finished."
        if not self.active:
            return "No cook running."
        if not self.session.get("cook_started"):
            step = self.current_step()
            return f"Getting ready: {step['title'].lower()}." if step else "Getting ready."
        p = self.profile.pit
        until = p.get("alerts_until_event")
        if until and self.logged(until):
            return "The meat is off. Close the bottom vents fully to put the fire out."
        t = self.pit_temp
        if t is None:
            return "No reading from the pit probe. Check the Inkbird is on and in range."
        trend = self.pit_trend or 0.0
        vi = VENT_OPTIONS.index(self.settings["vent"]) if self.settings["vent"] in VENT_OPTIONS else len(VENT_OPTIONS) - 1
        up = VENT_OPTIONS[min(vi + 1, len(VENT_OPTIONS) - 1)]
        down = VENT_OPTIONS[max(vi - 1, 0)]
        tail = " Vent changes take 10–15 minutes to show."
        if not self.logged(p["alerts_from_event"]):
            if t < p["target_low"] - 15:
                return "Let it climb with the bottom vents fully open."
            if t < p["target_low"]:
                return "Nearly there: close the bottom vents to about 25% open now so it doesn't overshoot."
            if t <= p["target_high"]:
                return "In the band. Leave the vents where they are while it settles."
            return f"Overshooting: close the bottom vents to {down}. Leave the top vent fully open." + tail
        if self.suppressed:
            return "The lid was opened recently. Let it recover before touching the vents."
        if t < p["target_low"]:
            if trend >= 1:
                return "Low but recovering. Leave the vents and give it 10 minutes."
            if vi < len(VENT_OPTIONS) - 1:
                return f"Low: open the bottom vents to {up}." + tail
            return (
                "Low with the bottom vents fully open: the fire may be choked with ash or running out of fuel. "
                "Knock the ash through the charcoal grate, or add some lit briquettes."
            )
        if t > p["target_high"]:
            if trend <= -1:
                return "High but coming down. Leave the vents and give it 10 minutes."
            if vi > 0:
                return f"High: close the bottom vents to {down}. Leave the top vent fully open." + tail
            return "High with the bottom vents shut: check the lid and door are seated and the water pan still has water."
        if trend <= -1.5 and t <= p["target_low"] + 3:
            return f"Falling towards the bottom of the band: open the bottom vents to {up}." + tail
        if trend >= 1.5 and t >= p["target_high"] - 3:
            return f"Rising towards the top of the band: close the bottom vents to {down}." + tail
        return "Holding steady. No changes needed."

    # ---------------------------------------------------------- notification

    @callback
    def _notify(self, title: str, message: str, *, important: bool, tag: str, icon: str) -> None:
        script = self.options[CONF_NOTIFY_SCRIPT]
        destinations = self.options[CONF_IMPORTANT_DESTINATIONS if important else CONF_INFO_DESTINATIONS]
        data = {
            "destination": destinations,
            "title": title,
            "message": message,
            "tag": tag,
            "icon": icon,
            "is_important": important,
        }
        sent = self.session.setdefault("notifications", [])
        sent.append({"ts": _iso(dt_util.utcnow()), "title": title, "important": important})
        del sent[:-100]
        self.hass.async_create_task(self._async_call_script(script, data), f"{DOMAIN} notify")

    async def _async_call_script(self, script: str, data: dict[str, Any]) -> None:
        domain, _, object_id = script.partition(".")
        try:
            await self.hass.services.async_call(domain, object_id, data, blocking=True)
        except Exception:  # fail loudly: log it, don't swallow it
            _LOGGER.exception("Smoke Session couldn't send notification '%s' via %s", data["title"], script)
