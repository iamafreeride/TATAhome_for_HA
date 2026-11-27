# TATAHome for Home Assistant

Custom integration for **TATAHome / Haier 200S** robot vacuums. It talks to the
same vendor cloud as the TATAHome Android app; no Android emulator and no local
MQTT bridge are required.

The integration was rebuilt for **Home Assistant Core 2026.11** using the
current integration rules: config flow, `DataUpdateCoordinator`, `runtime_data`,
device registry, entity translations, diagnostics and a quality-scale manifest.

Reference material used:

- [Integration manifest](https://contributors.home-assistant.io/core/integrations/manifest/)
- [Config flow](https://contributors.home-assistant.io/core/integrations/config-flow/)
- [Fetching data / coordinator](https://contributors.home-assistant.io/core/integrations/fetching-data/)
- [Vacuum entity](https://contributors.home-assistant.io/core/entities/vacuum/)
- [Translations](https://contributors.home-assistant.io/core/integrations/translations/)
- [Integration quality scale](https://contributors.home-assistant.io/core/quality-scale/)

## Features

### Vacuum

- Start, pause, stop (vendor stop is a pause), return to dock
- Live activity: cleaning, paused, docked, returning, error
- Fan speed select (quiet / standard / strong / max)
- `vacuum.send_command`: `edge`, `spot`, `mop`, `area`, `two_pass`

### Sensors

- Battery, cleaned area, cleaning time
- Main brush, side brush, filter and mop-pad life percentage
- Firmware (diagnostic, disabled by default)

### Settings

- Suction, water level and default mode
- Do-not-disturb switch and quiet-hours service values
- Memory map, breakpoint resume, carpet turbo, voice prompts
- Voice volume (0–100)
- Device nickname through `tatahome.set_nickname` service
- Consumables are read from the vendor's real `0x1113` response

### Settings persistence

The vendor cloud returns factory values after every new login. TATAHome stores
the user's desired settings in Home Assistant's `.storage` and re-applies them
after a heartbeat/session drop or a full HA restart. This covers suction,
water, mode, DND/quiet hours, memory map, breakpoint resume, carpet turbo,
voice and volume.

### Device support

- One TATAHome account per config entry
- One robot per account (the vendor app exposes one primary device in this
  firmware)
- Automatic TCP heartbeat every 120 s, configurable in options
- Automatic re-authentication when the cloud session expires

## Removed intentionally

These were **not** part of the original vendor APK behaviour and are not
implemented:

- Child lock — there is no vendor child-lock opcode; the previous web UI lock
  was web-only and has been removed.
- Manual driving — the vendor's manual-control command is not reliable enough
  for a HA entity and has been removed.

## Installation

### HACS (custom repository)

1. HACS → Integrations → three-dot menu → Custom repositories.
2. Add `https://github.com/iamafreeride/TATAhome_for_HA` as **Integration**.
3. Install **TATAHome** and restart Home Assistant.

### Manual

Copy `custom_components/tatahome` into your Home Assistant config directory:

```text
/config/custom_components/tatahome/
```

Restart Home Assistant, then add the integration from **Settings → Devices &
services → Add integration → TATAHome**.

## Configuration

Use the same email/password as the TATAHome app. Credentials are stored in the
config entry, never in YAML or logs. The options flow controls polling and
heartbeat intervals.

## Services

| Service | Description |
| --- | --- |
| `tatahome.set_nickname` | Change the cloud device alias |
| `tatahome.set_quiet_hours` | Enable/disable DND and set start/end times |

Example:

```yaml
service: tatahome.set_quiet_hours
data:
  enabled: true
  start: "22:00"
  end: "07:00"
```

## Entities

- `vacuum.<device>` — main robot
- `sensor.*_battery`, `sensor.*_cleaned_area`, `sensor.*_cleaning_time`
- `sensor.*_main_brush_life`, `sensor.*_side_brush_life`,
  `sensor.*_filter_life`, `sensor.*_mop_pad_life` (percent; `remaining_days`
  is an attribute)
- `binary_sensor.*_online`, `binary_sensor.*_docked`
- `switch.*_do_not_disturb`, `switch.*_memory_map`,
  `switch.*_breakpoint_resume`, `switch.*_carpet_turbo`, `switch.*_voice`
- `switch.*_edge_clean`, `switch.*_spot_clean`, `switch.*_area_clean`,
  `switch.*_two_pass_clean` (clean-mode switches; on starts, off pauses)
- `select.*_suction`, `select.*_water`, `select.*_mode`
- `number.*_voice_volume`
- `time.*_do_not_disturb_start`, `time.*_do_not_disturb_end`

## Known limitations

- Cloud-only; no local control.
- The vendor's map binary is only complete after a finished clean. The map is
  not exposed as a HA camera yet; the cloud task lookup exists but incomplete
  maps are rejected.
- The vendor has no distinct stop command; stop maps to pause.
- Clean-mode switches track the mode started from Home Assistant. The cloud
  status does not expose the current clean type, so a mode started from the
  vendor app may not be reflected until the next HA command/restart.
- Settings are re-applied from `.storage` after a new login; if the robot has
  been reset/changed from the vendor app, the saved HA values win.
- Session is bound to one TCP connection; the integration owns it and keeps it
  warm with a heartbeat.
- Only tested with Haier 200S firmware `H2.3.5.32.28R`.

## Troubleshooting

- **Cannot connect**: confirm the TATAHome app can log in and that the host can
  reach `fas.haier.3irobotix.net:4020`.
- **Unavailable**: the cloud reports the robot offline, usually when it is off
  the dock with a depleted battery.
- **Invalid auth**: use the TATAHome app password; reauthenticate from the
  integration page if the session was revoked.

## Development

```bash
python -m unittest discover -s tests -v
```

The protocol tests are dependency-free. Full HA entity tests require
`pytest-homeassistant-custom-component`.

## License

MIT. This project is an interoperability effort for a device you own; it is not
affiliated with TATAHome, Haier or iRobotix.
