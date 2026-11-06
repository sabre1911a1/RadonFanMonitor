# Engineering notes — v2.1 dual absolute pressure sensing

## Measurement model

The MPRLS measures **pipe absolute pressure** and the BME280 measures **room absolute pressure**. At each scheduled acquisition, the Pico reads a fresh pair on the same I²C bus. The signal used by the state machine is:

```text
zero_offset_hpa = average(BME280.room_hpa - MPRLS.open_to_room_hpa)
suction_hpa = BME280.room_hpa - MPRLS.pipe_hpa - zero_offset_hpa
baseline_suction_hpa = average(suction_hpa) with mitigation fan operating
minimum_suction_hpa = baseline_suction_hpa * (1 - alarm_loss_percent/100)
recover_suction_hpa = minimum_suction_hpa + hysteresis_hpa
```

**Positive suction means lower pipe pressure than room pressure.** Sensor offsets may be positive or negative. An offset of exactly zero is valid; `null` means **not calibrated** and is never conflated with zero. The two historical absolute readings (952.776 and 949.865 hPa) are *not* used for live monitoring or for the new baseline: the actual two-sensor arrangement requires new calibration.

The pressure samples are **sequential**, not synchronized in hardware. This is reasonable for relatively slowly varying barometric pressure, but needs physical validation under fan cycling and environmental transients. The BME280's `pressure` is in **hPa** and Adafruit's basic driver has default I²C address 0x77; it may be configured to 0x76. Temperature and relative humidity are recorded separately for diagnostics only and do **not** alter the pressure alarm.

## State machine and fault behavior

- `STARTUP`: no successful pair yet. Initial read failure immediately enters `MONITOR_FAULT`.
- `NORMAL`: valid recent readings, rolling suction **greater than** minimum threshold.
- `LOW_SUCTION_PENDING`: rolling suction **less than or equal** to minimum; timer running.
- `LOW_SUCTION_ALARM`: low suction persists for `alarm_delay_s`; repeats five short beeps.
- `MONITOR_FAULT`: stale readings, `sensor_fault_after` failed paired readings, or missing required sensor; repeats three longer beeps.
- Once faulted, `sensor_recovery_samples` **consecutive valid pairs** are required before clearing fault; previous pre-fault average is discarded.
- Once low suction is alarmed, recovery requires rolling suction **at least** `minimum_suction_hpa + hysteresis_hpa`.
- Audible acknowledgment changes only the buzzer, not the state. No cloud notifications or remote reset route.

Ring-buffer memory is fixed by `average_window_s/sample_interval_s` and only accepted valid pairs go into the average. A sensor failure must **not** substitute a stale last-known value or silently fall back to v2.0 absolute-pressure comparison.

## Operational tradeoffs

Sampling, alarm state evaluation, buzzer scheduling, and watchdog feeding take priority over optional Wi-Fi and HTTP polling in one cooperative loop. The Wi-Fi connect API is still synchronous; a misbehaving driver/network operation may block for longer than the requested timeout and provoke the RP2040 8-second watchdog. This needs real hardware testing. A genuine I²C sensor failure is reported as a persistent local alarm instead of forcing an endless reboot.

The saved zero offset compensates **initial cross-sensor bias**, not independent drift. Weather variation common to both sensors should cancel algebraically, but different temperature coefficients, long-term drift, tubing leaks, and sensor error may give false or missed alarms. The BME280's own environmental readings are not a substitute for characterizing long-term suction accuracy. The previous 10% loss threshold represented about **0.291 hPa** for an example 2.911 hPa baseline, so verify repeatability against a manometer before selecting sensitivity.

A five-minute rolling average followed by five minutes of threshold persistence introduces deliberate delay. A fast near-zero-suction path was discussed but **not enabled** until sensor noise is characterized on real hardware.

## Calibration, storage, and security

The configured `calibration_stage` must follow **zero → baseline → ready**. Only `zero`/`baseline` boots remount the filesystem writable to the Pico; the regular runtime does not write any file. Each calibration writes a backup, writes a temporary JSON file, validates the next stage, and renames into place. FAT update is recoverable but **not power-loss atomic**; manually restore from backup on a host if needed. Never edit the USB volume from a computer while the Pico has write ownership.

No device-specific Wi-Fi credentials or saved calibration files are tracked in Git. The HTTP interface is an unauthenticated **LAN-only** status page, status JSON and POST-only buzzer acknowledgment. UniFi can detect a lost wireless client but cannot guarantee that the monitoring application is healthy. The Pico cannot generate any alert if it is completely without power: external power/network monitoring is complementary.

## Firmware libraries

For CircuitPython 9.1.1 use the **9.x `.mpy` bundle**. Dependencies: `adafruit_mprls.mpy`, the `adafruit_bme280` directory containing `basic.mpy` and `protocol.mpy`, `adafruit_httpserver` directory, and `adafruit_bus_device` if not frozen into firmware. Check `docs/USER_GUIDE.md` for installation. The source repo does not version compiled dependencies.

## Test scope

Desktop tests cover offset arithmetic, weather shifts, threshold/hysteresis, delays, dual-sensor fault/recovery, invalid values, calibration schemas, and an in-memory mock of the firmware/HTTP stack. Physical on-device tests, a pressure reference, Wi-Fi outage testing and extended soak testing remain required. This device does **not** measure radon concentration or verify radon safety.
