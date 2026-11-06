# Radon Fan Monitor — v2.1 (two-sensor suction monitoring)

A local, audible **radon-mitigation fan operation monitor** using a Raspberry Pi Pico W, an Adafruit MPRLS absolute-pressure sensor connected to the suction pipe, an Adafruit BME280 exposed to room air, and a piezo buzzer. The onboard web page is optional; **sampling and alarms do not depend on Wi-Fi, Adafruit IO, or Internet access**.

> **This is not a radon detector or a certified safety instrument.** It cannot determine indoor radon concentration or prove that mitigation is effective. Pressure readings can be affected by sensor offset and drift. Maintain a conventional radon test program and check mitigation-system operation independently.

## How it works

Every 10 seconds, the Pico takes a **paired** reading from both absolute sensors:

```text
BME280 room pressure  ─┐
                       ├─ (room − pipe − zero_offset) = estimated suction (hPa)
MPRLS pipe pressure  ──┘                       │
                                        rolling average
                                              │
                               percentage-of-baseline threshold
                                              │
                                   alarm delay / hysteresis
                                              │
                                     buzzer and LAN status
```

Both sensors share I²C on Pico GP12/GP13. No tubing is attached to the BME280; it must be exposed to ambient air. See [wiring](docs/WIRING.md).

The system explicitly distinguishes **NORMAL**, **LOW_SUCTION_PENDING**, **LOW_SUCTION_ALARM**, and **MONITOR_FAULT**. Any inability to acquire a valid pair of pressure readings eventually becomes a fault, never a reassuring normal status. Recovery from a sensor fault requires 3 consecutive valid paired readings by default.

## START HERE — upgrade from v2.0

**Your original 2024 absolute-pressure calibrations cannot be automatically converted into this two-sensor calibration.** This release deliberately ships with `calibration_stage: "zero"`, and blank `sensor_offset_hpa` / `baseline_suction_hpa` values. You must calibrate with the actual installed BME280 and MPRLS.

1. Read **[Installation, calibration and acceptance testing](docs/USER_GUIDE.md)** in full.
2. Back up the whole current `CIRCUITPY` drive, including private Wi-Fi credentials.
3. Wire the BME280 to GP12/GP13 + 3.3V/GND and allow it to sense room air. Power off before wiring.
4. Install the Python files from `CIRCUITPY/` and matching CircuitPython **9.x** libraries (see guide); create a private `settings.json` from `settings.example.json`.
5. **Disconnect the MPRLS pressure tube** and run the 5-minute sensor-zero calibration; then power off.
6. **Reconnect the MPRLS tube**, ensure the fan is operating, and run the 5-minute working-suction calibration. The device then reboots into monitoring.
7. Characterize readings against a conventional manometer, test the buzzer and sensor faults, and verify UniFi's client-offline notification.

## Source layout

| Path | Purpose |
|---|---|
| `CIRCUITPY/code.py` | Pico hardware, dual-pressure acquisition, local HTTP status, Wi-Fi and buzzer |
| `CIRCUITPY/monitor.py` | Independent suction calculator and alarm state machine |
| `CIRCUITPY/boot.py` | Filesystem-write ownership only during deliberate calibration |
| `CIRCUITPY/settings.example.json` | Public **credential-free** template (copy to device-local `settings.json`) |
| `docs/USER_GUIDE.md` | Installation, zero/baseline calibration, alarms, testing and maintenance |
| `docs/WIRING.md` | Original wiring and BME280 additions |
| `docs/BEEP_CODES.md` | Audible alarm patterns |
| `docs/TROUBLESHOOTING.md` | Diagnostic reference |
| `docs/ENGINEERING_NOTES.md` | Algorithm, limitations and engineering tradeoffs |
| `tests/` | Desktop tests and mocked firmware smoke test |

Compiled `.mpy` libraries, secrets, and device-local calibration are intentionally excluded from Git. See the [official CircuitPython library bundle](https://circuitpython.org/libraries) for compatible `adafruit_bme280`, `adafruit_mprls`, `adafruit_httpserver`, and `adafruit_bus_device` dependencies. Confirm your board's actual firmware version before selecting the bundle.

## Run desktop tests

```bash
python -m unittest discover -s tests -v
python tests/smoke_firmware_mock.py
```

These tests exercise logic and mocked wiring/HTTP paths. **They are not a substitute for tests on the physical Pico W and sensors.** The MCU watchdog, Wi-Fi stack, sensor repeatability, and two-sensor drift require on-device verification.

## Default behavior

- 10-second paired acquisition; five-minute rolling mean.
- 10% suction loss starts the pending alarm timer; five additional minutes triggers the low-suction buzzer.
- 0.15 hPa hysteresis on alarm clearing, subject to the configured baseline being large enough.
- 3 consecutive failed pairs produce a monitor fault (initial acquisition failure faults immediately); 3 consecutive successful pairs recover from a fault.
- Five short repeating beeps = low suction. Three longer repeating beeps = monitor fault. Acknowledge the current buzzer through `POST /ack`, without clearing the actual state.
- The local dashboard is `http://<Pico-IP>/`; JSON is `/status.json`. No cloud accounts, no remote reboot endpoint, and no unauthenticated Internet exposure.

**Important precision note:** Calculating the difference of two absolute sensors cancels *shared barometric changes*, but their independent offsets, temperature effects, and drift do **not** necessarily cancel. An uncorrected 0.3 hPa shift is already about 10% of the historical 2.911 hPa suction. The default threshold is a starting point **for testing**, not a validated tolerance.
