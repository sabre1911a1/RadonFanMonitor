# Troubleshooting — v2.1

Open a USB serial console and look for `[radon]` messages. Do **not** assume that a silent buzzer or an associated Wi-Fi client means the pressure measurement is valid.

| Symptom | Probable causes | What to check |
|---|---|---|
| `ImportError: adafruit_bme280` or `adafruit_bus_device` | Missing or incompatible libraries | Install **matching CircuitPython 9.x** `.mpy` libraries in `/lib/` (BME280 uses `basic.mpy` and `protocol.mpy`). Check `boot_out.txt`. |
| `MONITOR_FAULT`, BME280 missing | No BME280 / wrong I²C address | GP12 SDA, GP13 SCL, 3V3, GND. Default BME address `119` = 0x77, alternate `118` = 0x76. |
| `MONITOR_FAULT`, MPRLS missing | Pressure sensor, I²C or reset/EOC problem | MPRLS address 0x18, GP15 reset and GP16 EOC, same SDA/SCL pins, USB serial details. |
| `MONITOR_FAULT` after readings worked | Repeated invalid/failed pressure pair or stale sampling | Examine `/status.json` fields `last_sensor_error`, `consecutive_failures`, `seconds_since_valid_reading`; power-cycle for persistent hardware fault. |
| Repeating three longer beeps | Sensor failure or fatal config/software problem | USB serial, correct `/settings.json`, both sensors installed. |
| Repeating five short beeps | Loss-of-suction alarm | Verify mitigation fan and pressure tubing, compare with a **manometer**, perform independent radon measurement as appropriate. |
| Suspicious normal reading | Drift, wrong offset/baseline, leaky tube | Compare both sensors with tubing unplugged (deliberate zero stage), inspect physical tubing, and check reference manometer. **Do not auto-zero during operation.** |
| Too many false alarms | 10% threshold may be too sensitive | Characterize noise/offset drift over several days; adjust `alarm_loss_percent`, `hysteresis_hpa`, `alarm_delay_s` only based on evidence. |
| No web page but buzzer still works | No Wi-Fi/incorrect credentials, web listener stopped, LAN isolation | Check DHCP/UniFi, serial logging and client connectivity. Wi-Fi is optional for local alarm. |
| Device restarts during Wi-Fi events | Blocking network activity or watchdog timeout | Capture reset reason, reduce network exposure, test AP power loss and recovery on physical Pico. |
| No monitoring after install | `calibration_stage` intentionally starts at `zero` | Complete zero calibration with MPRLS port open to room air, then baseline with fan running and tube connected. |
| Calibration stops with a fault | Either sensor failed or insufficient suction | Verify wiring, correct tubing condition for the stage, and serial error before restarting calibration. |
| `settings.json` missing after power loss | Interrupted file replacement during calibration | Power down; use host computer to restore from `settings.backup.json` or a separately saved known-good copy. |
| UniFi reports Pico online but monitor faulty | Network association is not application health | Inspect local buzzer and `/status.json`; UniFi client-disconnect alerts are only a secondary presence signal. |

## Checking differential math by hand

1. During **zero stage**, both sensors must see the **same room air**. The resulting average `BME280 - MPRLS` is `sensor_offset_hpa` (it may be negative or zero).
2. During **baseline stage**, the tube is attached and the fan is running. The corrected difference is the saved `baseline_suction_hpa`.
3. During monitoring, the live value is `(room − pipe − offset)` hPa, or divide by **2.49089** for inches of water column.
4. The default minimum is `baseline_suction_hpa × 0.90`. A 2.911 hPa baseline would trigger pending at **2.620 hPa** or below, and recover an active alarm at **2.770 hPa** or higher (0.15 hPa hysteresis).

Test both sensors and compare to a real differential manometer before unattended deployment. Pressure is not radon concentration.
