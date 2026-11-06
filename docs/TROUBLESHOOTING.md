# Troubleshooting & audible patterns — v2.0

These patterns replace the original (now-obsolete) 2024 multi-part diagnostic beep codes.

| Sound | State / meaning | First checks |
|---|---|---|
| Five **short** beeps, repeats | `LOW_SUCTION_ALARM` | Fan operating? Pipe/tubing connection? Recent barometric changes? Review threshold and serial readings. |
| Three **long** beeps, repeats | `MONITOR_FAULT` | MPRLS sensor/I²C power and pins GP12 SDA, GP13 SCL, GP15 reset, GP16 EOC; bad sample or stale reading. |
| Three **long** beeps during startup/configuration error | Fatal startup fault | USB serial output; malformed/missing `settings.json`, invalid settings, or incompatible library. |
| Silent after web acknowledgment | Current alarm acknowledged | Dashboard still shows actual state; any newly entered alarm sounds again. |
| Silent, with no readings | NOT proof of healthy operation | Inspect USB serial, web status, and independent UniFi client-presence monitoring. |

## No Wi-Fi or web page

1. This is **not** supposed to prevent local pressure monitoring.
2. `settings.json` must contain `ssid` and `wifi_pwd` (no `.toml` in this release).
3. Pico W requires a 2.4 GHz network. Review Wi-Fi VLAN / client isolation / firewall behavior, DHCP and AP association.
4. Browse to the device IP: `http://<IP>/` or `http://<IP>/status.json`. Port 80 is used.
5. Observe `[radon]` serial messages such as `Wi-Fi unavailable` or `Web server started`.
6. Watch `last_wifi_error`, `last_http_error`, `http_failures`, and `wifi_connect_attempts` when the JSON endpoint becomes available.
7. After a successful first association, CircuitPython provides Wi-Fi reconnection; a periodic bounded application retry is also attempted.

## Low-suction warning seems too sensitive

- The saved threshold is 10% loss of the calibration difference, near **950.156 hPa absolute** for the preserved 2024 numbers. This is VERY close to the original operating-pressure snapshot.
- Weather can change atmospheric pressure much more than that small 0.291 hPa threshold margin.
- Review the actual running average, and consider a more permissive `alarm_loss_percent` after testing; the historical design notes suggested 65% as a trial value.
- All of these are approximate fan-operation clues. The present hardware cannot measure live differential suction or radon concentration.

## Missing Adafruit I²C helper on startup

The original bundled `adafruit_mprls.mpy` imports `adafruit_bus_device.i2c_device`. This helper can be built into some CircuitPython builds, which likely explains why the historic flash dump did not contain it. If the serial console says `ImportError: no module named adafruit_bus_device`, install the library from the compatible **CircuitPython 9.x** Adafruit bundle. Do not add a second copy if the firmware already includes it.

## Pressure is missing / implausible

- Power off before rewiring.
- Check I²C SDA GP12, SCL GP13 (NOT obsolete GP20/GP21), 3V3, GND, reset GP15, EOC GP16.
- A failed sensor read is caught; successive failures enter MONITOR_FAULT. Reinitialization is attempted at the next scheduled sample.
- Investigate the sensor's port and tubing for condensate, leakage, blockage, or accidental disconnection (without introducing fluid into the electronics).

## Calibration / flash corruption

- Recalibration starts only when either `ambient_pressure_hpa` or `working_pressure_hpa` is 0. Normal operation keeps the Pico's own flash access read-only.
- If an interrupted flash write leaves `settings.json` unreadable/missing, restore a valid copy from your PC backup. `settings.backup.json` contains the last pre-write configuration.
- Host and Pico must NOT modify the CIRCUITPY volume at the same time during calibration. Safe-eject CIRCUITPY before running the calibrating device.
- During the first ambient stage the device intentionally waits for you to power off, attach the tubing, then power on; this is not a hang.

## Diagnosis from JSON

The `/status.json` endpoint reports `state`, `sensor_healthy`, `last_reading_hpa`, `rolling_average_hpa`, calibrated absolute values, thresholds, ages of recent readings, successful/failed sample counts, previous sensor error, reset reason, and free-heap statistics.

The fan or pressure tube may fail in ways that don't change the monitored pressure significantly. The Pico might also keep Wi-Fi association while pressure monitoring has failed. **UniFi client-disconnect notifications are only supplemental.**
