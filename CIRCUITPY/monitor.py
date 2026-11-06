"""Pure-Python pressure/alarm state machine; no hardware or Wi-Fi imports.

Designed for CircuitPython 9 on a Pico W; unit-testable on desktop CPython.

NOTE: MPRLS measures absolute pressure. This device cannot independently
remove barometric effects or measure indoor radon concentration.
"""
import math

STARTUP = "STARTUP"
NORMAL = "NORMAL"
PENDING = "LOW_SUCTION_PENDING"
LOW_SUCTION = "LOW_SUCTION_ALARM"
FAULT = "MONITOR_FAULT"


class ConfigError(ValueError):
    pass


def validate(settings):
    """Validate /settings.json; return sanitized config with explicit units."""
    c = dict(settings)
    for key in ("ambient_pressure_hpa", "working_pressure_hpa"):
        v = c.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
            raise ConfigError("Invalid " + key)

    specs = (
        ("sample_interval_s", 1, 60),
        ("average_window_s", 10, 3600),
        ("alarm_delay_s", 0, 3600),
        ("alarm_repeat_s", 3, 300),
        ("alarm_loss_percent", 1, 100),
        ("hysteresis_hpa", 0, 5),
        ("sensor_fault_after", 1, 10),
        ("stale_after_s", 5, 600),
        ("wifi_retry_s", 15, 3600),
        ("wifi_connect_timeout_s", 1, 5),
    )
    for k, lo, hi in specs:
        v = c.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < lo or v > hi:
            raise ConfigError("Invalid " + k + ": expected " + str(lo) + ".." + str(hi))

    if c["stale_after_s"] <= c["sample_interval_s"]:
        raise ConfigError("stale_after_s must exceed sample_interval_s")
    if c["average_window_s"] < c["sample_interval_s"]:
        raise ConfigError("average_window_s must be >= sample_interval_s")
    if c["sensor_fault_after"] != int(c["sensor_fault_after"]):
        raise ConfigError("sensor_fault_after must be an integer")
    if c["ambient_pressure_hpa"] and c["working_pressure_hpa"]:
        delta = c["ambient_pressure_hpa"] - c["working_pressure_hpa"]
        if delta <= 0.2:
            raise ConfigError("calibration must show > 0.2 hPa of suction")
    if c.get("hostname") and (not isinstance(c["hostname"], str) or len(c["hostname"]) > 32):
        raise ConfigError("Invalid hostname")
    return c


def valid_pressure(hpa):
    return (isinstance(hpa, (int, float)) and not isinstance(hpa, bool)
            and math.isfinite(hpa) and 700.0 <= hpa <= 1200.0)


class Monitor:
    def __init__(self, config, now=0.0):
        self.cfg = validate(config)
        a = self.cfg["ambient_pressure_hpa"]
        w = self.cfg["working_pressure_hpa"]
        if a == 0 or w == 0:
            raise ConfigError("Monitoring requires both calibrations")
        self.threshold_hpa = w + (a - w) * self.cfg["alarm_loss_percent"] / 100.0
        self.recover_hpa = self.threshold_hpa - self.cfg["hysteresis_hpa"]
        # Fixed-size storage; no allocation on every sample beyond scalar arithmetic.
        self.max_samples = max(1, int(self.cfg["average_window_s"] / self.cfg["sample_interval_s"]))
        self.values = [0.0] * self.max_samples
        self.value_count = 0
        self.write_index = 0
        self.sum_values = 0.0
        self.state = STARTUP
        self.last_reading_hpa = None
        self.average_hpa = None
        self.last_sample_ok_s = None
        self.last_sample_attempt_s = None
        self.consecutive_failures = 0
        self.total_failures = 0
        self.total_samples = 0
        self.last_error = ""
        self.pending_since_s = None
        self.acknowledged = False
        self.started_s = now
        self.last_state_change_s = now

    def _transition(self, new_state, now):
        if self.state != new_state:
            self.state = new_state
            self.last_state_change_s = now
            if new_state in (LOW_SUCTION, FAULT):
                self.acknowledged = False
            elif new_state == NORMAL:
                self.acknowledged = False

    def _mark_fault(self, now):
        if self.state != FAULT:
            # Never blend stale pre-fault readings into recovery decisions.
            self.sum_values = 0.0
            self.value_count = 0
            self.write_index = 0
            self.average_hpa = None
        self.pending_since_s = None
        self._transition(FAULT, now)

    def update(self, now, hpa=None, error=None):
        """Record a scheduled acquisition attempt; exceptions are converted to faults."""
        self.last_sample_attempt_s = now
        if error is not None or not valid_pressure(hpa):
            self.total_failures += 1
            self.consecutive_failures += 1
            self.last_error = str(error)[:100] if error is not None else "Implausible pressure reading"
            if self.consecutive_failures >= self.cfg["sensor_fault_after"] or self.last_sample_ok_s is None:
                self._mark_fault(now)
            return
        self.last_error = ""
        self.consecutive_failures = 0
        self.last_sample_ok_s = now
        self.total_samples += 1
        self.last_reading_hpa = float(hpa)
        if self.value_count < self.max_samples:
            self.value_count += 1
        else:
            self.sum_values -= self.values[self.write_index]
        self.values[self.write_index] = self.last_reading_hpa
        self.sum_values += self.last_reading_hpa
        self.write_index = (self.write_index + 1) % self.max_samples
        self.average_hpa = self.sum_values / self.value_count
        self.evaluate(now)

    def evaluate(self, now):
        # Staleness is a fault, even if our last average looked fine.
        if (self.last_sample_ok_s is None or
                now - self.last_sample_ok_s > self.cfg["stale_after_s"]):
            self._mark_fault(now)
            return
        if self.consecutive_failures >= self.cfg["sensor_fault_after"]:
            self._mark_fault(now)
            return
        if self.average_hpa is None:
            self._transition(STARTUP, now)
            return

        # While alarmed, require extra pressure margin before clearing.
        # This applies after sensor faults too: do not immediately consider a
        # recovered sensor healthy if it is still reporting low suction.
        if self.state == LOW_SUCTION and self.average_hpa > self.recover_hpa:
            return

        if self.average_hpa >= self.threshold_hpa:
            if self.pending_since_s is None:
                self.pending_since_s = now
            if now - self.pending_since_s >= self.cfg["alarm_delay_s"]:
                self._transition(LOW_SUCTION, now)
            else:
                self._transition(PENDING, now)
        else:
            # Recover fully once below threshold (or recover_hpa if alarmed).
            self.pending_since_s = None
            self._transition(NORMAL, now)

    def acknowledge(self):
        if self.state in (LOW_SUCTION, FAULT):
            self.acknowledged = True
            return True
        return False

    def audible(self):
        return self.state in (LOW_SUCTION, FAULT) and not self.acknowledged

    def snapshot(self, now):
        def age(t):
            return None if t is None else round(max(0, now - t), 1)
        return {
            "state": self.state,
            "alarm_acknowledged": self.acknowledged,
            "sensor_healthy": self.state != FAULT,
            "last_reading_hpa": None if self.last_reading_hpa is None else round(self.last_reading_hpa, 3),
            "rolling_average_hpa": None if self.average_hpa is None else round(self.average_hpa, 3),
            "alarm_threshold_hpa": round(self.threshold_hpa, 3),
            "recovery_threshold_hpa": round(self.recover_hpa, 3),
            "calibration_ambient_hpa": self.cfg["ambient_pressure_hpa"],
            "calibration_pipe_hpa": self.cfg["working_pressure_hpa"],
            "calibration_delta_hpa": round(self.cfg["ambient_pressure_hpa"] - self.cfg["working_pressure_hpa"], 3),
            "seconds_since_valid_reading": age(self.last_sample_ok_s),
            "seconds_since_attempt": age(self.last_sample_attempt_s),
            "pending_seconds": age(self.pending_since_s),
            "samples_in_average": self.value_count,
            "total_valid_samples": self.total_samples,
            "total_failed_samples": self.total_failures,
            "consecutive_failures": self.consecutive_failures,
            "last_sensor_error": self.last_error,
            "uptime_seconds": int(max(0, now - self.started_s)),
        }
