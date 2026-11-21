"""End-to-end simulation of a rib cook."""

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed, async_mock_service

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.smoke_session.const import DOMAIN
from custom_components.smoke_session.profile import load_profiles

PIT = "sensor.smoker_temperature"
MEAT = "sensor.smoker_thermometer_temperature_probe_2"
ATTRS = {"unit_of_measurement": "°C", "device_class": "temperature"}


def set_temps(hass, pit=None, meat=None):
    if pit is not None:
        hass.states.async_set(PIT, str(pit), ATTRS)
    if meat is not None:
        hass.states.async_set(MEAT, str(meat), ATTRS)


async def advance(hass, freezer, minutes, pit=None, meat=None, step_s=30):
    """Move time forward, re-publishing probe readings like the Inkbird does."""
    steps = int(minutes * 60 / step_s)
    for i in range(steps):
        freezer.tick(timedelta(seconds=step_s))
        p = pit(i * step_s / 60) if callable(pit) else pit
        m = meat(i * step_s / 60) if callable(meat) else meat
        set_temps(hass, p, m)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


@pytest.fixture
async def setup(hass: HomeAssistant, freezer):
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to("2026-11-22 09:00:00+00:00")
    set_temps(hass, 12, 11)
    calls = async_mock_service(hass, "script", "send_notification")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WSM",
        data={
            "name": "WSM",
            "pit_sensor": PIT,
            "meat_sensors": [MEAT],
            "notify_script": "script.send_notification",
            "important_destinations": ["aaron", "tv"],
            "info_destinations": ["aaron"],
        },
        unique_id=PIT,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, calls


def titles(calls):
    return [c.data["title"] for c in calls]


def status(hass):
    return hass.states.get("sensor.wsm_smoke_session_status")


async def press(hass, key):
    await hass.services.async_call("button", "press", {"entity_id": f"button.wsm_smoke_session_{key}"}, blocking=True)
    await hass.async_block_till_done()


def test_profiles_load():
    profiles = load_profiles()
    assert set(profiles) == {"st_louis_ribs", "dry_run"}
    ribs = profiles["st_louis_ribs"]
    assert sum(ribs.phase_duration(i, 1.4) for i in range(len(ribs.phases))) == 405


async def test_entities_created(hass, setup):
    st = status(hass)
    assert st is not None and st.state == "idle"
    assert hass.states.get("select.wsm_smoke_session_cook").state == "St Louis Ribs"
    assert hass.states.get("select.wsm_smoke_session_bottom_vents").state == "Fully open"
    assert hass.states.get("time.wsm_smoke_session_planned_start").state == "11:00:00"
    ents = st.attributes["entities"]
    assert ents["next_step"] == "button.wsm_smoke_session_next_step"


async def test_full_rib_cook(hass, setup, freezer):
    entry, calls = setup
    # Arm at 09:00 UTC (= 09:00 London in November) for an 11:00 start.
    await press(hass, "start_session")
    st = status(hass)
    assert st.state == "active"
    tl = st.attributes["phases"]
    assert tl[0]["planned_start"].startswith("2026-11-22T11:00")
    assert dt_util.parse_datetime(tl[-1]["planned_end"]) == dt_util.parse_datetime("2026-11-22T17:45:00+00:00")
    assert hass.states.get("sensor.wsm_smoke_session_current_step").state == "Load the charcoal ring"

    # Nothing fires overnight-style before the start; the 15-minute warning fires at 10:45.
    await advance(hass, freezer, 105)
    assert titles(calls) == ["St Louis Ribs starts in 15 minutes"]
    await advance(hass, freezer, 15)
    assert titles(calls)[-1] == "Time to start: Light the chimney"

    # Can't change the cook mid-session
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("select", "select_option", {"entity_id": "select.wsm_smoke_session_cook", "option": "Dry Run (indoors test)"}, blocking=True)

    await press(hass, "next_step")  # ring loaded
    await press(hass, "next_step")  # chimney lit -> cook starts
    assert status(hass).attributes["cook_started"] is not None
    await press(hass, "next_step")  # assemble
    await press(hass, "next_step")  # vents
    await press(hass, "next_step")  # pit probe
    assert hass.states.get("sensor.wsm_smoke_session_current_step").state.startswith("Let the pit stabilise")

    # Pit climbs 12 -> 125 over 30 min. No pit alerts during fire-up.
    await advance(hass, freezer, 30, pit=lambda m: min(125, 12 + m * 4))
    assert not any("Pit too" in t for t in titles(calls))
    rec = hass.states.get("sensor.wsm_smoke_session_recommendation").state
    assert rec.startswith("In the band")
    # Holds 125 for 10 minutes -> auto-completes, alerts armed
    await advance(hass, freezer, 11, pit=125)
    assert "Pit is stable" in titles(calls)
    assert status(hass).attributes["pit_alerts_armed"] is True
    assert hass.states.get("sensor.wsm_smoke_session_phase").state == "Smoke (unwrapped)"

    # Ribs on: lid opens, pit dips to 110 for 8 minutes -> suppressed (12 min recovery), no alert
    await press(hass, "next_step")
    await advance(hass, freezer, 8, pit=110, meat=8)
    assert not any("Pit too cold" in t for t in titles(calls))
    assert hass.states.get("binary_sensor.wsm_smoke_session_lid_recovery").state == "on"
    # Recovery window ends at 12 min, still 110 -> alert 5 min after that
    await advance(hass, freezer, 4, pit=110, meat=10)
    assert not any("Pit too cold" in t for t in titles(calls))
    await advance(hass, freezer, 6, pit=110, meat=12)
    cold = [c for c in calls if c.data["title"].startswith("Pit too cold")]
    assert len(cold) == 1 and cold[0].data["is_important"] is True
    assert cold[0].data["destination"] == ["aaron", "tv"]
    assert "open the bottom vents" in cold[0].data["message"].lower() or "fully open" in cold[0].data["message"]
    assert hass.states.get("binary_sensor.wsm_smoke_session_pit_alert").state == "on"
    # Back in range
    await advance(hass, freezer, 2, pit=124, meat=14)
    assert titles(calls)[-1] == "Pit back in range"

    # Spritz reminder 90 min after ribs on (ribs on was ~20 min ago)
    before = len(calls)
    await advance(hass, freezer, 75, pit=124, meat=lambda m: 14 + m * 0.6)
    assert "Spritz due" in titles(calls)[before:]
    # Log a spritz: next reminder moves to spritz + 45
    await press(hass, "log_spritz")
    nxt = hass.states.get("sensor.wsm_smoke_session_next_reminder")
    spritz_ts = status(hass).attributes["events"][-1]["ts"]
    assert dt_util.parse_datetime(nxt.state) in (
        dt_util.parse_datetime(spritz_ts) + timedelta(minutes=45),
        dt_util.parse_datetime(status(hass).attributes["phases"][1]["actual_start"]) + timedelta(minutes=180),
    )

    # Meat reaches 70 -> wrap check alert (once)
    await advance(hass, freezer, 30, pit=124, meat=lambda m: min(72, 60 + m))
    assert titles(calls).count("Wrap check") == 1

    # Wrap and move on
    await press(hass, "next_step")  # smoke_hold done -> wrapped phase, step wrap
    await press(hass, "next_step")  # wrap logged
    assert hass.states.get("sensor.wsm_smoke_session_current_step").state == "Hold 120–130°C, wrapped"
    before = len(calls)
    await advance(hass, freezer, 91, pit=126, meat=lambda m: min(92, 72 + m * 0.25))
    t = titles(calls)[before:]
    assert "Hold 120–130°C, wrapped" in t  # 90-minute probing reminder
    assert "Start probing" in t           # 90°C
    assert "Spritz due" not in t          # stops after wrap

    # Probe offline for 3+ minutes -> important alert
    hass.states.async_set(MEAT, "unavailable")
    await advance(hass, freezer, 4, pit=126)
    assert "Meat probe offline" in titles(calls)
    await advance(hass, freezer, 1, pit=126, meat=94)
    assert "Meat probe back" in titles(calls)

    await hass.services.async_call(DOMAIN, "log_event", {"event_type": "probe_check", "note": "Still a bit tight"}, blocking=True)
    for _ in range(6):  # wrapped_hold, probe_tender, unwrap, set_bark, off_smoker, rest
        await press(hass, "next_step")
    st = status(hass)
    assert st.state == "finished"
    summary = st.attributes["summary"]
    assert summary["minutes_to_stable"] is not None
    assert summary["pit_in_target_pct"] is not None and summary["pit_in_target_pct"] > 50
    assert summary["lid_openings"] >= 3
    assert summary["key_events"]["wrap"]["meat"] is not None

    # Full log available as a response
    resp = await hass.services.async_call(DOMAIN, "get_session", {}, blocking=True, return_response=True)
    types = [e["type"] for e in resp["session"]["events"]]
    for needed in ["session_start", "chimney_lit", "pit_stable", "ribs_on", "spritz", "wrap", "probe_check", "probe_tender", "unwrap", "off_smoker", "session_end"]:
        assert needed in types, needed
    # Every notification went through the notification script with a tag
    assert all(c.data.get("tag", "").startswith("smoke_session_") for c in calls)


async def test_vents_logged_and_recommendation(hass, setup, freezer):
    entry, calls = setup
    await hass.services.async_call(DOMAIN, "start_session", {"profile": "st_louis_ribs", "planned_start": "09:00:00"}, blocking=True)
    for _ in range(5):
        await press(hass, "next_step")
    await advance(hass, freezer, 12, pit=125)
    assert status(hass).attributes["pit_alerts_armed"]
    await hass.services.async_call("select", "select_option", {"entity_id": "select.wsm_smoke_session_bottom_vents", "option": "25% open"}, blocking=True)
    await hass.async_block_till_done()
    assert status(hass).attributes["events"][-1]["type"] == "vent_adjust"
    # Slow steady fall below the band: recommendation is to open up one notch
    await advance(hass, freezer, 15, pit=lambda m: 125 - m * 0.8)
    rec = hass.states.get("sensor.wsm_smoke_session_recommendation").state
    assert "50% open" in rec, rec


async def test_restart_resumes(hass, setup, freezer):
    entry, calls = setup
    await hass.services.async_call(DOMAIN, "start_session", {"planned_start": "09:00:00"}, blocking=True)
    await press(hass, "next_step")
    await press(hass, "next_step")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    st = status(hass)
    assert st.state == "active"
    assert hass.states.get("sensor.wsm_smoke_session_current_step").state == "Pour the coals and assemble"
    assert st.attributes["cook_started"] is not None


async def test_bad_weight_rejected(hass, setup):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "start_session", {"weight_kg": 9}, blocking=True)


async def test_drift_warning_and_attr_size(hass, setup, freezer):
    import json

    entry, calls = setup
    await hass.services.async_call(DOMAIN, "start_session", {"planned_start": "09:00:00"}, blocking=True)
    for _ in range(5):
        await press(hass, "next_step")
    await advance(hass, freezer, 12, pit=128)
    # Rising 4°C per 10 min from 128: heads over 135 within 15 minutes
    await advance(hass, freezer, 11, pit=lambda m: 128 + m * 0.4)
    drift = [c for c in calls if c.data["title"] == "Pit drifting up"]
    assert len(drift) == 1 and drift[0].data["is_important"] is False
    assert "close the bottom vents" in drift[0].data["message"].lower()
    size = len(json.dumps(dict(status(hass).attributes), default=str))
    assert size < 16000, size


async def test_dry_run_profile(hass, setup, freezer):
    entry, calls = setup
    await hass.services.async_call(DOMAIN, "start_session", {"profile": "dry_run", "planned_start": "09:00:00"}, blocking=True)
    await press(hass, "next_step")  # begin
    await advance(hass, freezer, 2, pit=21)
    assert "Pit is stable" in titles(calls)
    await press(hass, "next_step")  # meat in
    await advance(hass, freezer, 3, pit=21, meat=31)
    assert "Dry run meat alert" in titles(calls)
    await advance(hass, freezer, 4, pit=40, meat=31)
    assert any(t.startswith("Pit too hot") for t in titles(calls))
    await press(hass, "next_step")
    assert status(hass).state == "finished"
