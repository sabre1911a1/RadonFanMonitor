# Beep patterns — v2.0

The v2 firmware **does not** use the old numerical 2024 calibration / Wi-Fi error codes. The original repo's top-level `beep_codes` is now a deprecation pointer; the obsolete 2024 contents remain accessible in Git history and should not be followed when troubleshooting v2.

| Pattern | Meaning | Action |
|---|---|---|
| Repeating **five short beeps** | `LOW_SUCTION_ALARM`: measured absolute pressure has crossed the configured threshold for the configured delay | Check mitigation fan, tubing, and pressure setup; verify indoor radon independently |
| Repeating **three longer beeps** | `MONITOR_FAULT`: sensor is missing, readings invalid/stale, or no readings are trustworthy | Check sensor wiring (SDA **GP12**, SCL **GP13**), sensor power, and USB serial output |
| No beeps | Normal, awaiting alarm delay, or currently acknowledged/silenced | Check status page/serial; silence does **not** mean a fault is cleared |
| Repeating long fault-like pattern during startup | Fatal configuration/software error | Inspect USB serial output and `settings.json` |

The v2 buzzer does not provide a Wi-Fi-disconnected beep: **the local monitor continues while offline**. The friend's UniFi Network installation can separately alert when the Pico wireless client disappears, but that is a network-presence check, not an application-health check.
