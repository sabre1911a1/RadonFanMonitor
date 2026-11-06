# Radon Fan Monitor — user and installation guide

**Software release:** 2.0 (replacement for the 2024 CircuitPython project)  
**Target:** Raspberry Pi Pico W · CircuitPython 9.1.1 · MPRLS absolute-pressure breakout · piezo buzzer

## 1. What it does, and what it cannot do

This device attempts to detect *changes in the operating pressure* inside a radon mitigation suction pipe. It measures absolute pressure through the MPRLS, compares a rolling average to a threshold calculated from two saved calibration measurements, and sounds a local alarm when suction appears inadequate. A separate fault alarm indicates that readings cannot be trusted. When Wi-Fi works, a local browser can read status and silence the audible alarm.

**It does NOT measure indoor radon.** It cannot establish that a mitigation system is achieving safe radon concentration. It is NOT a certified life-safety device. A normal state can be wrong if local barometric pressure changes. Use independent radon testing and follow the mitigation contractor's recommendations.

## 2. Repository layout and hardware

The repository stores **source files**, not a directly flashable CircuitPython image. Copy `CIRCUITPY/code.py`, `boot.py`, and `monitor.py` to the root of the Pico's CIRCUITPY drive, and create device-local `/settings.json` from `CIRCUITPY/settings.example.json`. Install the matching CircuitPython 9.x `adafruit_mprls` and `adafruit_httpserver` libraries, plus `adafruit_bus_device` if required, under the Pico's `/lib/` directory. The original wiring image remains in the root of the GitHub repository; see `docs/WIRING.md` for the corrected text wiring reference.

## 3. Back up, install and start

1. Connect the Pico W by USB. Copy the entire CIRCUITPY drive to your computer **before** changing anything, including Wi-Fi settings and prior calibration data.
2. Record its CircuitPython version from `boot_out.txt` or USB serial. The previous downloadable deployment ZIP used the original CircuitPython 9.1.1 `.mpy` files, but this GitHub source tree intentionally omits binary libraries. Install compatible libraries from the matching Adafruit bundle.
3. Remove old `code.py` and now-unused Adafruit IO libraries, then copy the three Python files from this repo's `CIRCUITPY/` folder to the drive root. Do not leave behind an old root `asyncio` library merely because the old application used it; the new app doesn't need it.
4. Copy `settings.example.json` to device-local `settings.json` if needed, then set `ssid` and `wifi_pwd` to the local **2.4 GHz** wireless network, or leave them blank for standalone alarm-only operation. Wi-Fi credentials have intentionally been removed from the published archive.
5. Confirm the physical pin mapping. Reboot the Pico W and open the CircuitPython USB serial console. The monitor should log a first pressure reading *before* trying Wi-Fi.
6. If connected, access `http://<PICO_IP>/`. The machine-readable endpoint is `http://<PICO_IP>/status.json`.

**Do not flash or wire the Pico from the repository without checking the power and pin mapping.** Don't expose the HTTP service to the public Internet; it has no login and the acknowledge button is a local LAN control.

## 4. Normal operation

The monitor takes an MPRLS reading every `sample_interval_s` (default 10 s). It maintains a `average_window_s` (default 300 s) sliding average of the most recent samples. The signal is **absolute pressure in hectopascals (hPa)**, not a live room-to-pipe pressure differential.

- **NORMAL** — recent valid pressure measurements are below the configured absolute threshold. This is a fan-operation indication, not a radon-safety assurance.
- **LOW_SUCTION_PENDING** — rolling pressure is too high (toward ambient); the alarm delay timer is counting.
- **LOW_SUCTION_ALARM** — above the threshold continuously for the delay (default 300 s). The buzzer repeats five short beeps.
- **MONITOR_FAULT** — reading acquisition failed, readings are stale, or the sensor returned an implausible value enough times. The buzzer repeats three longer beeps.
- **STARTUP** — brief initial state before first successful reading; an initial sensor-read failure immediately becomes MONITOR_FAULT.

Acknowledge/silence through the local web page's button (`POST /ack`). This silences the *current* alarm only; it does not change the state and a new alarm after recovery re-enables the buzzer. The webpage refreshes every 15 seconds. The watchdog restarts the Pico if the application loop stops progressing, but it is NOT a substitute for a secondary monitor.

## 5. Thresholds — especially important

The original calibration saved **952.776 hPa ambient** and **949.865 hPa with the sensor attached to the pipe**. Their difference is 2.911 hPa (~1.17 inches of water column) *at calibration time*. The app does not measure this differential continuously.

`alarm_loss_percent` is the percentage of the *saved suction margin lost* at which the pending alarm begins:

`threshold_hpa = working_pressure_hpa + (ambient_pressure_hpa - working_pressure_hpa) × alarm_loss_percent / 100`

The migrated setting is **10%**, preserving the 2024 flash settings. It produces a threshold near **950.156 hPa**, only **0.291 hPa** above the calibrated pipe pressure. It is exceptionally sensitive to ordinary weather changes. The original prose suggested **65%**, but that was not the value on the device. We did **not** silently change it: decide which is appropriate after testing on the installed system. The newer software accepts only a numeric percentage from 1 through 100; it no longer overloads decimal numbers as absolute pressure values.

`hysteresis_hpa` (default 0.15 hPa) requires the average to recover below a lower threshold before clearing an active alarm. `alarm_delay_s` begins when the rolling average is above the threshold and resets after it returns to normal. The rolling window plus the delay can make fan-shutdown detection take many minutes. Weather changes can still cause false *or missed* alerts even with filtering.

## 6. Two-stage recalibration

Recalibration writes to flash only when deliberately requested. **Back up the settings first**. Perform calibration under normal expected system conditions; don't inadvertently calibrate a failed fan as normal.

1. With power removed, disconnect the *pressure tubing from the MPRLS port*, leaving the port open to room air; keep the electrical connection intact.
2. From a computer, edit `settings.json`: set `ambient_pressure_hpa` to `0` (do not change Wi-Fi values). Save, eject the CIRCUITPY drive safely, and restart the Pico.
3. For the next five minutes, the Pico measures ambient pressure, backs up old settings in `settings.backup.json`, writes the new ambient value and resets `working_pressure_hpa` to `0`. It then **stops and waits for a physical power cycle**. Watch the serial output for confirmation.
4. Remove power. Securely attach the pressure tubing to the MPRLS port and the radon suction tap. Confirm the mitigation fan is operating.
5. Restore power. The Pico measures the pipe's absolute pressure for five minutes, writes it, then automatically reboots into monitoring mode. It refuses a working calibration that shows 0.2 hPa or less of suction relative to the saved ambient value.
6. After successful calibration, `boot.py` makes flash read-only to Pico code (the host can still manage the CIRCUITPY volume). Reinspect `settings.json` and verify readings and the alarm threshold.

**Power-off and USB writing warning:** While in a calibration boot, the Pico gets filesystem write ownership; avoid editing CIRCUITPY from the host at the same time. `settings.backup.json` holds the prior settings. If power fails in the short replace step and `settings.json` is missing or corrupt, restore a known-good `settings.json` from your backup on a PC and restart.

## 7. Wi-Fi, HTTP and UniFi notifications

Network operations are **best effort**. Pressure monitoring begins before the initial Wi-Fi connection. If connection fails, the local alarm continues. The Pico W Wi-Fi stack attempts automatic reconnection after a successful association, and the application makes time-bounded retry attempts once per `wifi_retry_s` (default 60 s) when disconnected. The HTTP server is stopped and recreated after a link change or socket failure.

On the friend's UniFi controller, identify the Pico's wireless client, preferably give it a DHCP reservation, and configure a **client disconnected/offline notification** for that client using the network application's available alarm settings. Then unplug the Pico to verify that a notification really arrives. UniFi's client-offline alert tests Wi-Fi presence—not necessarily sensor health. A Pico may remain associated even during an application or sensor problem. The local fault buzzer and `/status.json` are the primary indication of monitor health.

- Local webpage: `GET /`
- Structured status: `GET /status.json`
- Silence buzzer: `POST /ack`
- Remote reset: deliberately removed
- Internet/Adafruit IO: not used

**LAN security:** The HTTP server does not authenticate users. Keep it on a trusted/private network or restrictive IoT VLAN with only intended access. Never port-forward TCP/80 to the Internet.

## 8. Settings summary

All settings live in the single `CIRCUITPY/settings.json` file. Time units are now explicit in field names.

| Setting | Included value | Meaning |
|---|---:|---|
| `hostname` | `RnFanMonitor` | Wi-Fi hostname |
| `ssid` / `wifi_pwd` | blank | Enter local Wi-Fi credentials; optional for buzzer |
| `ambient_pressure_hpa` | 952.776 | Saved calibration in open room air |
| `working_pressure_hpa` | 949.865 | Saved calibration with fan operating |
| `sample_interval_s` | 10 | How often to read MPRLS |
| `average_window_s` | 300 | Sliding average history |
| `alarm_loss_percent` | 10 | Percentage of saved suction margin lost before pending alarm |
| `alarm_delay_s` | 300 | Continuous time above threshold until alarm |
| `hysteresis_hpa` | 0.15 | Extra margin needed to clear active alarm |
| `alarm_repeat_s` | 15 | Repetition interval after a beep sequence finishes |
| `sensor_fault_after` | 3 | Consecutive failed readings before fault; first-ever failure immediately faults |
| `stale_after_s` | 35 | Valid reading older than this produces a monitor fault |
| `wifi_retry_s` | 60 | Retry interval if disconnected |
| `wifi_connect_timeout_s` | 3 | Requested limit on a synchronous Wi-Fi connect attempt |

## 9. Acceptance and maintenance tests

Before depending on the device, perform these tests **at the installed location**:

1. **Offline:** Power up with Wi-Fi credentials blank or the AP turned off; confirm sampling and local alarms continue and the device does not reboot repeatedly.
2. **Online:** Restore Wi-Fi; confirm the dashboard shows refreshed readings, `/status.json` works, and UniFi sees the Pico.
3. **Fan test:** Under appropriate safe conditions, stop the mitigation fan or remove the pressure tubing from the suction tap (leave the MPRLS port open to room air), and observe the pending state and eventual alarm. Restore normal suction and verify recovery. **Restore the tubing and fan promptly.**
4. **Sensor test:** Power down, disconnect the sensor's I²C connection, power up, and confirm the three-long-beep monitor fault pattern; reattach only with power off.
5. **Acknowledge:** Silence an alarm from the browser; confirm state remains alarmed and that a subsequent new alarm sounds again.
6. **Watchdog:** Confirm `reset_reason` is exposed in `/status.json`. Do not deliberately hang a deployed unit just to test the watchdog unless you have a controlled test bench.
7. **UniFi test:** Unplug the Pico and confirm the configured client-disconnect notification arrives; do not assume UniFi detects a stalled application that remains associated.
8. **Soak:** Run continuously for several days and review live readings, reset reason, `total_failed_samples`, and `minimum_observed_free_heap_bytes`.

## 10. When something goes wrong

See `docs/TROUBLESHOOTING.md`. The USB serial console logs `[radon]` messages. If there is no web page, check Wi-Fi settings/IP, but remember the buzzer alarm does not need the network. If settings are invalid, the unit intentionally sounds a repeating fault tone; fix `settings.json` using USB. No Internet service or Adafruit IO account is required.
