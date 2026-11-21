# Smoke Session

A Home Assistant integration for guided smoker cooks. It reads probe sensors you already have (e.g. an Inkbird
xBBQ-4 via the native Inkbird integration), walks you through a cook step by step from a preset profile, and sends
alerts and reminders through your own notification script.

- **Profiles** (`custom_components/smoke_session/profiles/*.yaml`): phases, steps, pit band and alert limits, meat
  alert temperatures, recurring reminders (e.g. spritz every 45 min until wrap). Invalid profiles are logged and
  skipped.
- **Pit alerts**: out of the alert band for `sustain_min` minutes (important), an early "drifting" warning when
  the 10-minute trend will leave the band within 15 minutes, and a back-in-range notice. Off during fire-up and after
  the meat comes off; paused for `lid_recovery_min` after any lid opening (logged, or detected from a fast drop).
- **Recommendations**: vent advice for a Weber Smokey Mountain based on temperature, trend and the bottom vent
  position you record.
- **Log**: every step, lid opening, spritz, probe check, vent change and note, with pit and meat temperatures.
  A summary (time to stable, % time in band, pit range, lid openings, key events) is saved when the cook ends.
  `smoke_session.get_session` returns everything.
- Survives a Home Assistant restart mid-cook.

Notifications call the configured script with `destination`, `title`, `message`, `tag`, `icon` and `is_important`.

The dashboard card is in `card/smoke-session-card.js`; `card/view.yaml` is an example view.

Tests: `pytest` (uses `pytest-homeassistant-custom-component`).
