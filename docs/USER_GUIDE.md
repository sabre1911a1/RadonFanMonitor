# Installation and operating guide — v2.1

**Hardware:** Raspberry Pi Pico W, Adafruit MPRLS ported 0–25 PSI absolute pressure breakout (tube to radon pipe), Adafruit BME280 exposed to room air, GP2 PWM piezo buzzer. **Target firmware:** CircuitPython 9.1.1, as used by the original project.

**Important:** This project monitors *estimated suction* to infer radon-mitigation fan operation. It does **not measure radon concentration**, guarantee mitigation performance, or replace a conventional manometer and periodic radon testing. Sensor offsets and drift can produce inaccurate readings.

## 1. Back up and prepare

1. Connect the Pico to a computer by USB. **Make a complete backup of the existing CIRCUITPY contents before replacing anything**; preserve private Wi-Fi settings and original calibration for your own records.
2. Check `boot_out.txt` for the version actually installed on the Pico. **For CircuitPython 9.x, use libraries from the 9.x `.mpy` bundle** available at [circuitpython.org/libraries](https://circuitpython.org/libraries); 8.x libraries are incompatible. Do not install every library from the bundle.
3. Power off and wire the new BME280 in parallel with the MPRLS on the same **GP12/GP13** I²C bus, plus 3V3 and GND. The BME280 remains open to the **room air**, not connected by tubing. See [WIRING.md](WIRING.md).
4. Install the following modules in `/lib` (or verify an identical matching version is already available): `adafruit_mprls.mpy`; `adafruit_bme280/basic.mpy` and `adafruit_bme280/protocol.mpy`; the `adafruit_httpserver/` directory; and `adafruit_bus_device/` if the sensor drivers fail to import its I²C helper. The BME280 Python package's `__init__.mpy` can also be copied if present. Match all modules to the board firmware.
5. Copy `CIRCUITPY/boot.py`, `code.py`, and `monitor.py` to the **root** of the mounted CIRCUITPY drive. Copy `settings.example.json` to **`settings.json`**, at that same root. The example contains no actual credentials. Fill in `ssid`/`wifi_pwd` privately for 2.4 GHz Wi-Fi, or leave blank for buzzer-only mode.
6. Leave `calibration_stage: "zero"`, and `sensor_offset_hpa` / `baseline_suction_hpa` as `null`. These are new calibration parameters. **Do not reuse** the saved 2024 `ambient_pressure_hpa` and `working_pressure_hpa` values.

Do not expose the web interface to the Internet. It has **no authentication** and its alarm acknowledgment route is only appropriate for a trusted LAN.

## 2. Two-stage calibration — REQUIRED after adding BME280

Both stages collect paired BME280/MPRLS readings over the configured `average_window_s` (default 300 seconds, five minutes). The Pico records progress through the USB serial console and writes the result to `settings.json` with a backup.

### Stage A: sensor zero (tube disconnected)

1. **Power off the Pico.** Disconnect the pressure tube from the **MPRLS sensor port**, leaving that port exposed to room air. Both sensors must be sensing the same environment; the BME280 stays in room air at all times.
2. Keep `calibration_stage: "zero"` with both calibration values `null`. Power the Pico, and monitor the serial console.
3. For five minutes, the Pico calculates each paired `BME280 ambient − MPRLS open port` reading and averages their differences. It stores the result as `sensor_offset_hpa` and advances `calibration_stage` to `"baseline"`.
4. The Pico **stops and asks for a power cycle**. Do not attach the pressure tube or edit the USB volume while the Pico is still powered/writing to flash. A zero offset of exactly 0.0 is valid.

### Stage B: working-suction baseline (fan operating)

1. **Power off the Pico** after Stage A finishes. Reattach the tube from the MPRLS port to the mitigation pipe, ensure it is sealed, and verify the mitigation fan is operating normally.
2. Power on the Pico. The saved `calibration_stage: "baseline"` initiates a second five-minute set of paired readings.
3. The Pico computes `suction = (BME280 room − MPRLS pipe) − sensor_offset_hpa` for each pair, averages them, and saves `baseline_suction_hpa`. A baseline of 0.2 hPa or less is rejected as insufficient; very large or implausible values are also rejected.
4. Successful completion advances to `calibration_stage: "ready"` and automatically reboots into ordinary monitoring. Verify live suction agrees reasonably with a conventional manometer before relying on any alarms.

To deliberately recalibrate later, **back up `settings.json`**, then on a host set `calibration_stage` to `"zero"`, both `sensor_offset_hpa` and `baseline_suction_hpa` to JSON `null`, save, disconnect tubing, and repeat the two stages. The unit does **not** periodically self-zero in normal operation. Recalibrating with the fan running and the tube attached during zero stage would erase the suction signal.

**Filesystem warning:** During calibration, `boot.py` remounts the storage writable to the Pico, not to your host computer. Never write to the mounted USB volume from both simultaneously. The write algorithm retains `settings.backup.json`, but replacing a file on FAT is not power-loss atomic. Restore it from a computer if needed.

## 3. What normal operation reports

The application samples **both sensors** every `sample_interval_s` (10 s default), subtracts the stored zero offset, and maintains a five-minute rolling mean of suction in hPa. A positive value indicates the pipe is below room pressure.

- **NORMAL:** recent valid paired measurements, rolling suction above the configured minimum.
- **LOW_SUCTION_PENDING:** rolling suction at or below the minimum; a 300-second persistence timer has started.
- **LOW_SUCTION_ALARM:** reduced suction persists beyond the delay; five short beeps repeat.
- **MONITOR_FAULT:** no initial pair, too many failed pairs, or readings older than `stale_after_s`; three longer beeps repeat. **No fallback to absolute-only monitoring.**
- **STARTUP:** waiting for the first pair. An initial failure immediately becomes a fault.

Following a sensor fault, the default is to require **three consecutive successful paired samples** before returning to normal or pending. Repeating faults do not silently clear. Acknowledge from `POST /ack` to silence the *current* buzzer without changing the alarm state.

### Threshold calculation

`alarm_loss_percent` = 10% by default, **the value on the original Pico**; the older document's example of 65% was not the saved setting. This parameter indicates the tolerated loss from the *newly measured* baseline.

```text
minimum_suction_hpa = baseline_suction_hpa * (1 - alarm_loss_percent/100)
recovery_suction_hpa = minimum_suction_hpa + hysteresis_hpa
```

For an **illustrative** 2.911 hPa baseline, 10% loss means an alarm-pending threshold of **2.620 hPa**. A 0.15 hPa hysteresis means an active alarm clears at **2.770 hPa** or greater. Those numbers are **NOT loaded as the new calibration**; the actual device determines them after Stage B. The rolling window *plus* the persistence delay means a real failure can take many minutes to alarm. Do not enable an immediate low-suction alarm without first characterizing sensor noise.

## 4. Dashboard, API and UniFi

Once the Pico associates with its 2.4 GHz Wi-Fi network, browse to `http://<PICO_IP>/`. It shows live estimated suction in hPa/inH2O, room and pipe absolute pressures, the saved calibration offset and baseline, rolling average, alarm threshold, state, sensor failures, temperature, humidity, uptime, and diagnostic information.

| HTTP route | Function |
|---|---|
| `GET /` | Auto-refreshing local status dashboard |
| `GET /status.json` | Machine-readable diagnostics and readings |
| `POST /ack` | Acknowledge/silence current audible alarm; **does not** clear alarm condition |

Wi-Fi and HTTP are **optional**: the buzzer and pressure monitor continue without Internet access or a working access point, subject to the cooperative-loop/driver constraints below. The AP/controller can send a UniFi **wireless client disconnected** alert for the Pico. Test it by disconnecting the Pico's power. Association alone does not prove the sensor software is healthy; a faulted monitor may remain connected to Wi-Fi.

The Pico W Wi-Fi `connect()` call is synchronous; unusual AP/driver hangs can still interfere with sampling until the 8-second watchdog resets the microcontroller. Verify this on the real device during Wi-Fi outage/recovery tests.

## 5. Configuration reference

| Key | Default/template | Meaning |
|---|---|---|
| `ssid`, `wifi_pwd` | blank | 2.4 GHz Wi-Fi; optional for local alarm |
| `hostname` | `RnFanMonitor` | Wi-Fi hostname |
| `calibration_stage` | `zero` | Required sequence: `zero` → `baseline` → `ready` |
| `sensor_offset_hpa` | `null` | Averaged **room minus open-port** bias; signed, zero valid |
| `baseline_suction_hpa` | `null` | Verified, corrected fan-running suction; determined only in Stage B |
| `bme280_i2c_address` | `119` | Decimal 0x77; `118` for 0x76 |
| `sample_interval_s` | `10` | Paired reading interval |
| `average_window_s` | `300` | Rolling suction mean window and calibration duration |
| `alarm_loss_percent` | `10` | Percent of baseline suction permitted to disappear |
| `alarm_delay_s` | `300` | Time below minimum before full alarm |
| `hysteresis_hpa` | `0.15` | Additional suction required to clear active alarm; must be smaller than loss margin |
| `alarm_repeat_s` | `15` | Gap between beep sequences |
| `sensor_fault_after` | `3` | Consecutive bad pairs before monitor fault |
| `sensor_recovery_samples` | `3` | Consecutive good pairs to recover from fault |
| `stale_after_s` | `35` | Last valid paired sample age limit |
| `wifi_retry_s` | `60` | Connection retry interval |
| `wifi_connect_timeout_s` | `3` | Requested synchronous connect timeout in seconds |

Temperature and humidity are **diagnostics only**, refreshed separately; they are not used to adjust suction.

## 6. Before you leave it unattended

Conduct these acceptance tests, ideally while observing the USB serial console:

1. Confirm initial **zero stage** and **baseline stage** finish with physically correct tubing and a reliably operating mitigation fan.
2. Read `/status.json`: both sensor values should be plausible, and corrected suction should agree with a **real differential manometer**.
3. Log readings for a few days with normal weather variation; examine offset repeatability and pressure noise against the manometer. The historical 10% setting corresponds to only ~0.291 hPa for the old 2.911 hPa reference; it may be **too tight** for these sensors.
4. Temporarily disconnect the pressure tube from the **sensor** (leave port open to room air), or perform a controlled fan interruption if safe. Confirm low-suction pending/alarm after the configured delay. Restore the tube/fan promptly.
5. Power off, temporarily disconnect the **BME280**, restart, confirm `MONITOR_FAULT` and three-long-beep pattern. Restore with power off. Repeat with the MPRLS if appropriate.
6. Trigger and acknowledge a buzzer alarm, verify state remains alarmed; restore pressure and check hysteresis-based recovery and re-arm.
7. Disable Wi-Fi/unplug the AP; confirm sampling/alarm survive. Restore Wi-Fi, check dashboard and `/status.json`.
8. Unplug Pico and verify the **UniFi client-disconnect notification** actually arrives, with an appropriate delay and alert channel.
9. Soak-test continuously for several days; watch failed sample count, reset reason, low free heap, and reboots.

If tests show noisy suction despite correct wiring/calibration, **do not assume dual absolute sensors are accurate enough**. A purpose-built differential pressure transducer may eventually be necessary. The current approach is an experiment until characterized.

## 7. Troubleshooting and references

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md), [BEEP_CODES.md](BEEP_CODES.md), and [ENGINEERING_NOTES.md](ENGINEERING_NOTES.md).

- Adafruit BME280 driver/API: https://docs.circuitpython.org/projects/bme280/en/latest/api.html
- CircuitPython 9.x `.mpy` libraries: https://circuitpython.org/libraries
- Adafruit MPRLS sensor guide: https://learn.adafruit.com/adafruit-mprls-ported-pressure-sensor-breakout/overview
