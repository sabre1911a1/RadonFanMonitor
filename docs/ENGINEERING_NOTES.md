# Engineering notes — software v2.0

## Why a single loop?

The original CircuitPython asyncio design allowed synchronous Adafruit IO HTTPS operations to stall pressure polling. It also fed the hardware watchdog from an independent coroutine, allowing the sensor task to die without triggering a reboot. v2 runs a priority-ordered cooperative loop: pressure acquisition → state evaluation → buzzer → watchdog feed → occasional Wi-Fi work → HTTP polling. Failures of the sensor operation become a local fault state rather than terminating monitoring.

There is a qualification: the **Pico W Wi-Fi connect and HTTP server APIs are synchronous**. The firmware requests a 3-second Wi-Fi connection timeout and polls HTTP in short intervals, but an underlying driver or unusual client may still block long enough for the 8-second watchdog to reset the device. This is a tradeoff with CircuitPython on RP2040. It needs physical soak testing, including AP power loss.

## Watchdog semantics

WDT is armed after settings validation, the first pressure acquisition attempt, and before any Wi-Fi attempt. The main loop feeds it only while the sensor **acquisition scheduler is progressing**. Bad/missing I²C readings are reported as `MONITOR_FAULT` and **do not** force repeated resets. Actual scheduler stalls, blocking network calls, or a hung main loop stop feeding the watchdog and should provoke a hardware reset. A fresh sensor reading is *not* mandatory for watchdog feeding, because a disconnected sensor is an alarm condition that should remain audible and diagnosable.

## State transitions and filtering

- `MONITOR_FAULT`: initial read fails; `sensor_fault_after` consecutive failures occur; last good sample becomes older than `stale_after_s`.
- `NORMAL`: a recent valid average is below threshold and there is no active fault.
- `LOW_SUCTION_PENDING`: average reaches or exceeds threshold, but delay is still running.
- `LOW_SUCTION_ALARM`: persistent high absolute pressure exceeds configured delay.
- Active low-suction alarms clear when the average returns below `threshold - hysteresis`.
- Each new alarm state resets audible acknowledgment.
- Ring buffer stores a fixed number of float samples; no continually growing sample list.

**Known design limitation:** The rolling average intentionally includes recent historical readings, so pressure state can lag a real fan failure by several minutes. Absolute barometric variation can dominate the difference between pressure readings. No software can fully correct this without a current ambient-pressure reference or other physical sensor. Avoid promising a radon-safety guarantee.

## Filesystem safety

`boot.py` grants CircuitPython writable access to `/` only when calibration values are zero. `code.py` saves a copy to `settings.backup.json`, writes `settings.tmp.json`, removes old `settings.json`, then renames the temp file. This is recoverable but not power-loss-atomic on FAT. For firmware upgrades, back up the CIRCUITPY volume before replacement. The original `resetFlashRW.py` referenced nonexistent `/calib.json` and has been discarded.

## Security and privacy

The local HTTP server exposes a non-authenticated read-only status endpoint and a POST-only audible acknowledgment. No remote reset, cloud account, Adafruit IO feed, MQTT client, telemetry upload, or Internet dependency. The listener must remain on a trusted private network (or properly isolated IoT VLAN). The repository supplies `settings.example.json` with blank SSID/password fields; copy to device-local `settings.json` and enter credentials privately.

## Compatibility and validation

The MPRLS driver imports `adafruit_bus_device.i2c_device`. The original archive did not carry this dependency, and CircuitPython may already freeze it into firmware; do not inject an unneeded conflicting duplicate. If missing at startup, install the matching 9.x bundle copy.

The separate downloadable deployment ZIP retained the original compiled drivers. The source repository does not version `.mpy` libraries; install versions matching CircuitPython 9.x for a source-based deployment. `monitor.py` is deliberately standard Python. Desktop unit tests validate state transitions, elapsed-time alarm delay, stale sensor handling, filtering, thresholds and schema. The actual Pico W, MPRLS, buzzer, and web server are **not physically tested** by these tests. Before deployment, verify the serial console, unpowered sensor fault, pressure-loss alarm, Wi-Fi outage/recovery, UniFi disconnect notification, and multiday operation.
