"""Sensor-independent differential suction alarm state machine for CircuitPython.

Input: near-simultaneous absolute room and pipe readings in hPa.
Positive (ambient - pipe - offset) means suction. No radon concentration reading.
"""
import math

STARTUP = "STARTUP"
NORMAL = "NORMAL"
PENDING = "LOW_SUCTION_PENDING"
LOW_SUCTION = "LOW_SUCTION_ALARM"
FAULT = "MONITOR_FAULT"

class ConfigError(ValueError):
    pass


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def validate(settings):
    """Validate both runtime configuration and deliberate calibration stages."""
    c = dict(settings)
    stage = c.get("calibration_stage")
    if stage not in ("zero", "baseline", "ready"):
        raise ConfigError("calibration_stage must be zero, baseline, or ready")
    for name in ("sensor_offset_hpa", "baseline_suction_hpa"):
        value = c.get(name)
        if value is not None and not _number(value):
            raise ConfigError("Invalid " + name)
    offset = c.get("sensor_offset_hpa")
    baseline = c.get("baseline_suction_hpa")
    if offset is not None and abs(offset) > 50:
        raise ConfigError("Offset exceeds 50 hPa; check sensor wiring")
    if baseline is not None and not (0.2 < baseline <= 50):
        raise ConfigError("Invalid baseline suction; expected 0.2..50 hPa")
    if stage == "zero" and (offset is not None or baseline is not None):
        raise ConfigError("Zero stage requires both calibration values null")
    if stage == "baseline" and (offset is None or baseline is not None):
        raise ConfigError("Baseline stage requires offset but no baseline")
    if stage == "ready" and (offset is None or baseline is None):
        raise ConfigError("Ready stage requires both calibration values")
    specs = (
        ("sample_interval_s", 1, 60),
        ("average_window_s", 10, 3600),
        ("alarm_delay_s", 0, 3600),
        ("alarm_repeat_s", 3, 300),
        ("alarm_loss_percent", 1, 100),
        ("hysteresis_hpa", 0, 5),
        ("sensor_fault_after", 1, 10),
        ("sensor_recovery_samples", 1, 10),
        ("stale_after_s", 5, 600),
        ("wifi_retry_s", 15, 3600),
        ("wifi_connect_timeout_s", 1, 5),
    )
    for name, lo, hi in specs:
        value = c.get(name)
        if not _number(value) or not lo <= value <= hi:
            raise ConfigError("Invalid " + name + ": expected " + str(lo) + ".." + str(hi))
    for name in ("sensor_fault_after", "sensor_recovery_samples"):
        if c[name] != int(c[name]):
            raise ConfigError(name + " must be an integer")
    if c["stale_after_s"] <= c["sample_interval_s"]:
        raise ConfigError("stale_after_s must exceed sample_interval_s")
    if c["average_window_s"] < c["sample_interval_s"]:
        raise ConfigError("average_window_s must be >= sample_interval_s")
    if c["baseline_suction_hpa"] is not None:
        limit = c["baseline_suction_hpa"] * (1 - c["alarm_loss_percent"] / 100)
        if c["hysteresis_hpa"] >= c["baseline_suction_hpa"] - limit:
            raise ConfigError("hysteresis_hpa must be less than the suction loss margin")
    addr = c.get("bme280_i2c_address")
    if type(addr) is not int or addr not in (0x76, 0x77):
        raise ConfigError("bme280_i2c_address must be 118 (0x76) or 119 (0x77)")
    if c.get("hostname") and (not isinstance(c["hostname"], str) or len(c["hostname"]) > 32):
        raise ConfigError("Invalid hostname")
    if not isinstance(c.get("ssid"), str) or not isinstance(c.get("wifi_pwd"), str):
        raise ConfigError("SSID and password must be strings")
    return c


def valid_pressure(hpa, ambient=False):
    # BME280 compensated-pressure data sheet operating range: 300..1100 hPa.
    # MPRLS is a broader-range absolute sensor. Constrain both to plausible air.
    low, high = (300, 1100) if ambient else (700, 1200)
    return _number(hpa) and low <= hpa <= high


def calculate_suction(ambient_hpa, pipe_hpa, offset_hpa):
    if not valid_pressure(ambient_hpa, ambient=True):
        raise ValueError("Invalid BME280 ambient pressure")
    if not valid_pressure(pipe_hpa):
        raise ValueError("Invalid MPRLS pipe pressure")
    if not _number(offset_hpa) or abs(offset_hpa) > 50:
        raise ValueError("Missing/invalid sensor zero offset")
    suction = ambient_hpa - pipe_hpa - offset_hpa
    # Allow negative readings (overpressure or offset drift) as low suction;
    # grossly impossible differences indicate a malfunction instead.
    if not -50 <= suction <= 100:
        raise ValueError("Implausible pressure difference")
    return suction


class Monitor:
    def __init__(self, config, now=0.0):
        self.cfg = validate(config)
        if self.cfg["calibration_stage"] != "ready":
            raise ConfigError("Cannot monitor until both calibrations complete")
        self.minimum_suction_hpa = (self.cfg["baseline_suction_hpa"]
                                    * (1 - self.cfg["alarm_loss_percent"] / 100))
        self.recover_suction_hpa = self.minimum_suction_hpa + self.cfg["hysteresis_hpa"]
        self.max_samples = max(1, int(self.cfg["average_window_s"] / self.cfg["sample_interval_s"]))
        self.values = [0.0] * self.max_samples
        self.value_count = 0
        self.write_index = 0
        self.sum_values = 0.0
        self.state = STARTUP
        self.last_ambient_hpa = None
        self.last_pipe_hpa = None
        self.last_suction_hpa = None
        self.average_suction_hpa = None
        self.last_sample_ok_s = None
        self.last_sample_attempt_s = None
        self.consecutive_failures = 0
        self.recovery_good_samples = 0
        self.total_failures = 0
        self.total_samples = 0
        self.last_error = ""
        self.pending_since_s = None
        self.acknowledged = False
        self.started_s = now
        self.last_state_change_s = now

    def _transition(self, state, now):
        if self.state != state:
            self.state = state
            self.last_state_change_s = now
            if state in (LOW_SUCTION, FAULT, NORMAL):
                self.acknowledged = False

    def _mark_fault(self, now):
        if self.state != FAULT:
            self.sum_values = 0.0
            self.value_count = 0
            self.write_index = 0
            self.average_suction_hpa = None
            self.recovery_good_samples = 0
        self.pending_since_s = None
        self._transition(FAULT, now)

    def update(self, now, ambient_hpa=None, pipe_hpa=None, error=None):
        self.last_sample_attempt_s = now
        try:
            if error is not None:
                raise ValueError(str(error))
            suction = calculate_suction(ambient_hpa, pipe_hpa, self.cfg["sensor_offset_hpa"])
        except (ValueError, TypeError) as exc:
            self.total_failures += 1
            self.consecutive_failures += 1
            self.recovery_good_samples = 0
            # A failed reading during fault recovery invalidates the partial
            # recovery history; only a fresh run of good pairs may clear it.
            if self.state == FAULT:
                self.sum_values = 0.0
                self.value_count = 0
                self.write_index = 0
                self.average_suction_hpa = None
            self.last_error = str(exc)[:100]
            if self.consecutive_failures >= self.cfg["sensor_fault_after"] or self.last_sample_ok_s is None:
                self._mark_fault(now)
            return

        self.consecutive_failures = 0
        self.last_error = ""
        self.last_sample_ok_s = now
        self.total_samples += 1
        self.last_ambient_hpa = float(ambient_hpa)
        self.last_pipe_hpa = float(pipe_hpa)
        self.last_suction_hpa = float(suction)
        if self.state == FAULT:
            self.recovery_good_samples += 1
        if self.value_count < self.max_samples:
            self.value_count += 1
        else:
            self.sum_values -= self.values[self.write_index]
        self.values[self.write_index] = suction
        self.sum_values += suction
        self.write_index = (self.write_index + 1) % self.max_samples
        self.average_suction_hpa = self.sum_values / self.value_count
        self.evaluate(now)

    def evaluate(self, now):
        if self.last_sample_ok_s is None or now - self.last_sample_ok_s > self.cfg["stale_after_s"]:
            self._mark_fault(now)
            return
        if self.consecutive_failures >= self.cfg["sensor_fault_after"]:
            self._mark_fault(now)
            return
        if self.state == FAULT and self.recovery_good_samples < self.cfg["sensor_recovery_samples"]:
            return
        if self.average_suction_hpa is None:
            self._transition(STARTUP, now)
            return
        if self.state == LOW_SUCTION and self.average_suction_hpa < self.recover_suction_hpa:
            return
        if self.average_suction_hpa <= self.minimum_suction_hpa:
            if self.pending_since_s is None:
                self.pending_since_s = now
            if now - self.pending_since_s >= self.cfg["alarm_delay_s"]:
                self._transition(LOW_SUCTION, now)
            else:
                self._transition(PENDING, now)
        else:
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
            "last_ambient_hpa": None if self.last_ambient_hpa is None else round(self.last_ambient_hpa, 3),
            "last_pipe_hpa": None if self.last_pipe_hpa is None else round(self.last_pipe_hpa, 3),
            "last_suction_hpa": None if self.last_suction_hpa is None else round(self.last_suction_hpa, 3),
            "rolling_average_suction_hpa": None if self.average_suction_hpa is None else round(self.average_suction_hpa, 3),
            "minimum_suction_hpa": round(self.minimum_suction_hpa, 3),
            "recovery_suction_hpa": round(self.recover_suction_hpa, 3),
            "sensor_offset_hpa": round(self.cfg["sensor_offset_hpa"], 3),
            "baseline_suction_hpa": round(self.cfg["baseline_suction_hpa"], 3),
            "seconds_since_valid_reading": age(self.last_sample_ok_s),
            "seconds_since_attempt": age(self.last_sample_attempt_s),
            "pending_seconds": age(self.pending_since_s),
            "samples_in_average": self.value_count,
            "total_valid_samples": self.total_samples,
            "total_failed_samples": self.total_failures,
            "consecutive_failures": self.consecutive_failures,
            "recovery_good_samples": self.recovery_good_samples,
            "last_sensor_error": self.last_error,
            "uptime_seconds": int(max(0, now - self.started_s)),
        }