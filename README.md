# Radon Fan Monitor — CircuitPython v2.0 (pre-hardware validation)

Standalone radon **mitigation fan operation** monitor using a Raspberry Pi Pico W, an Adafruit MPRLS absolute-pressure sensor and a PWM piezo buzzer. This project monitors a *proxy for fan suction*, **not radon concentration**. The original 2024 design has been reworked to remove Adafruit IO/cloud dependencies and to keep pressure monitoring independent of Wi-Fi.

> **Hardware testing pending.** The Python state-machine tests pass, but this v2 firmware has not yet been validated on an actual Pico W and installed mitigation system. Do not rely on it as a sole safety measure. Continue indoor radon testing and regular mitigation-system inspection.

## Features

- Local pressure monitoring and audible alarm that operate without Wi-Fi.
- `NORMAL`, `LOW_SUCTION_PENDING`, `LOW_SUCTION_ALARM`, and `MONITOR_FAULT` conditions.
- Separate beep patterns for low suction (five short beeps) and sensor fault (three longer beeps); audible acknowledgment.
- Rolling average, configurable alarm delay, hysteresis, sensor-error detection, and application progress watchdog.
- Best-effort Wi-Fi with a LAN-only web dashboard, `GET /status.json`, and `POST /ack` (no cloud integration).
- Two-stage ambient/pipe calibration with backup of settings.
- CPython unit tests for the pressure-monitor state machine.

## Repository layout

| Path | Use |
|---|---|
| `CIRCUITPY/code.py`, `monitor.py`, `boot.py` | CircuitPython application sources; copy to Pico drive root |
| `CIRCUITPY/settings.example.json` | **Non-secret example**, copy to `settings.json` on the Pico and edit locally |
| `docs/USER_GUIDE.md` | Installation, calibration, test procedure and operation |
| `docs/WIRING.md` | Original GPIO wiring |
| `docs/BEEP_CODES.md` | v2 alarm patterns (replaces stale 2024 `beep_codes` instructions) |
| `docs/ENGINEERING_NOTES.md` | Design trade-offs and limits |
| `docs/TROUBLESHOOTING.md` | Fault finding |
| `tests/` | Desktop checks; **do not** copy to Pico |
| `wire_map.png` | Historical wiring picture from the original repository |

## Getting started

1. Back up the entire existing `CIRCUITPY` drive, especially calibration settings; confirm CircuitPython **9.1.1** and the correct matching libraries.
2. Copy `CIRCUITPY/boot.py`, `CIRCUITPY/code.py`, and `CIRCUITPY/monitor.py` to the drive root.
3. Copy `CIRCUITPY/settings.example.json` to `/settings.json` on the device. Enter `ssid` and `wifi_pwd` **only on the device** (or a private local copy). The example retains historic calibration numbers but these **must not** be assumed valid at a different time or installation.
4. Install the `adafruit_mprls` and `adafruit_httpserver` libraries compiled for CircuitPython 9.x under `/lib/`. The MPRLS driver may also require `adafruit_bus_device`. The prebuilt files from the private deployment ZIP are another option; this source repository intentionally does not commit `.mpy` binaries.
5. Open the USB serial console, reboot, verify pressure readings and the state, then test the alarm, sensor-disconnect handling, Wi-Fi outage, and UniFi client-offline notification. See the [full user guide](docs/USER_GUIDE.md).

**Note:** `boot.py` controls CircuitPython filesystem ownership during calibration. Follow the power-cycle instructions in the guide, and do not modify host files simultaneously while the Pico owns write access.

### Run desktop tests

```bash
python -m unittest discover -s tests -v
```

These tests do not exercise CircuitPython's Wi-Fi stack or real sensor hardware. `tests/smoke_firmware_mock.py` provides an additional mocked startup check.

## Configuration and credentials

Never commit a populated `settings.json`, flash dump, network passwords, Adafruit IO key or calibration backup. The `.gitignore` excludes common secret/flash artifacts; verify your staged files before any push. No Adafruit IO integration remains in this firmware.

## Important physical limitation

The 0–25 PSI MPRLS measures **absolute** pressure. A one-time room-pressure calibration cannot eliminate later changes in barometric pressure. The saved 10% loss threshold (about 0.291 hPa above the historic in-pipe pressure) is especially weather-sensitive. Network presence or a `NORMAL` state is not evidence of safe indoor radon levels. A differential pressure sensor would be a potential hardware improvement in a future version.

## Status

**v2.0 candidate — desktop-tested, hardware validation pending.** If the device is deployed, keep independent mitigation-system checks and radon measurements in place.
