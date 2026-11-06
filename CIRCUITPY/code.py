"""Radon mitigation FAN OPERATION monitor, v2.1.

Hardware: Pico W + MPRLS pipe sensor + BME280 room sensor + buzzer.
CircuitPython: target 9.1.1, using the user's original .mpy libraries.

The local alarm NEVER requires Wi-Fi. No Adafruit IO, MQTT, or HTTPS.
The web server is meant ONLY for a trusted private LAN.

LIMITATION: calculated suction depends on two absolute sensors, their
relative zero calibration and drift. Not a certified radon or pressure gauge.
Pressure is NOT a measure of indoor radon concentration.
"""
import board
import busio
import digitalio
import gc
import json
import microcontroller
import os
import pwmio
import socketpool
import time
import wifi

from adafruit_httpserver import GET, POST, Request, Response, Server
from monitor import (Monitor, ConfigError, FAULT, LOW_SUCTION, STARTUP,
                     validate, valid_pressure, calculate_suction)

SETTINGS_PATH = "/settings.json"
BACKUP_PATH = "/settings.backup.json"
TEMP_PATH = "/settings.tmp.json"

# Original wiring. The MPRLS board's port is connected to the suction pipe.
I2C_SDA = board.GP12
I2C_SCL = board.GP13
MPRLS_RESET = board.GP15
MPRLS_EOC = board.GP16
PIEZO = board.GP2

MONITOR = None
CFG = None
PIEZO_OUT = None
MPR = None
BME = None
I2C = None
EOC_PIN = None
RESET_PIN = None
SERVER = None
POOL = None
LAST_NETWORK_ERROR = ""
LAST_HTTP_ERROR = ""
HTTP_FAILURES = 0
WIFI_ATTEMPTS = 0
FREE_HEAP_LOW_WATER = None
BOOT_RESET_REASON = str(microcontroller.cpu.reset_reason)
ROOM_TEMP_C = None
ROOM_HUMIDITY_PCT = None
LAST_ENV_ERROR = ""

# Static HTML avoids a separate index.html file and extra filesystem reads.
HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15"><title>Radon Fan Monitor</title>
<style>body{{max-width:710px;margin:2em auto;padding:0 1em;font:16px system-ui,sans-serif;background:#f6f7f9;color:#18212b}}
main{{background:white;padding:1.4em;border-radius:12px;border:1px solid #d5dce5}}h1{{font-size:1.5em}}
dl{{display:grid;grid-template-columns:1fr 1fr;gap:.5em}}dt{{color:#52616e}}dd{{margin:0}}
hr{{border:0;border-top:1px solid #dde2e7}}button{{padding:.7em 1em}}small{{color:#56616c}}
</style></head><body><main><h1>Radon Fan Monitor</h1>
<h2>{state}</h2><p>{meaning}</p><hr>
<h2>{suction_water} inH2O</h2><p>Live offset-corrected suction: {suction} hPa</p>
<dl><dt>Rolling average suction</dt><dd>{average} hPa</dd>
<dt>Minimum suction</dt><dd>{threshold} hPa</dd>
<dt>Recovery suction</dt><dd>{recovery} hPa</dd>
<dt>Calibrated baseline suction</dt><dd>{baseline} hPa</dd>
<dt>Zero offset (BME - MPRLS)</dt><dd>{offset} hPa</dd>
<dt>BME280 room pressure</dt><dd>{ambient} hPa</dd>
<dt>MPRLS pipe pressure</dt><dd>{pipe} hPa</dd>
<dt>Room temperature</dt><dd>{temperature} C</dd>
<dt>Room humidity</dt><dd>{humidity} %</dd>
<dt>Last paired pressure reading</dt><dd>{sample_age} seconds ago</dd>
<dt>Wi-Fi</dt><dd>{wifi_status}</dd>
<dt>IP address</dt><dd>{ip}</dd>
<dt>Uptime</dt><dd>{uptime} seconds</dd>
<dt>Failed paired samples</dt><dd>{faults}</dd>
<dt>Alarm acknowledged</dt><dd>{acknowledged}</dd>
<dt>Last reboot reason</dt><dd>{reset_reason}</dd>
<dt>Free heap / minimum</dt><dd>{heap} / {heap_low} bytes</dd></dl>
{ack_button}<hr>
<small>Calculated suction uses TWO absolute sensors plus a stored zero offset. Sensor drift can cause false/missed alarms.
A healthy pressure result does NOT establish safe indoor radon levels; verify radon independently.</small>
<p><small>JSON: <a href="/status.json">/status.json</a>. Refreshes every 15 seconds. Trusted LAN only.</small></p>
</main></body></html>"""




def say(message):
    print("[radon]", message)


def safe_text(value):
    # Escape only the text we render from configurable/user-controlled fields.
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def fmt(value):
    return "--" if value is None else str(value)


def load_settings():
    # An interrupted calibration write can leave settings.tmp.json; ignore it.
    # A backup is retained for MANUAL recovery, not silently applied.
    with open(SETTINGS_PATH, "r") as f:
        c = json.load(f)
    return validate(c)


def save_calibration(stage, value):
    """Backup -> temp -> replace settings; only used with Pico-owned volume."""
    with open(SETTINGS_PATH, "r") as file:
        current = json.load(file)
    with open(BACKUP_PATH, "w") as file:
        json.dump(current, file)
        file.flush()
    os.sync()
    if stage == "zero":
        current["sensor_offset_hpa"] = round(value, 5)
        current["baseline_suction_hpa"] = None
        current["calibration_stage"] = "baseline"
    elif stage == "baseline":
        current["baseline_suction_hpa"] = round(value, 5)
        current["calibration_stage"] = "ready"
    else:
        raise ValueError("Unknown calibration stage")
    validate(current)
    with open(TEMP_PATH, "w") as file:
        json.dump(current, file)
        file.flush()
    os.sync()
    os.remove(SETTINGS_PATH)
    os.rename(TEMP_PATH, SETTINGS_PATH)
    os.sync()



def init_sensors():
    """Shared I2C bus on GPIO12/13; hardware pressure channels are separate."""
    global I2C, RESET_PIN, EOC_PIN, MPR, BME
    if I2C is None:
        I2C = busio.I2C(scl=I2C_SCL, sda=I2C_SDA)
        RESET_PIN = digitalio.DigitalInOut(MPRLS_RESET)
        EOC_PIN = digitalio.DigitalInOut(MPRLS_EOC)
    if MPR is None:
        import adafruit_mprls
        MPR = adafruit_mprls.MPRLS(
            I2C, eoc_pin=EOC_PIN, reset_pin=RESET_PIN, psi_min=0, psi_max=25)
    if BME is None:
        from adafruit_bme280 import basic as adafruit_bme280
        BME = adafruit_bme280.Adafruit_BME280_I2C(
            I2C, address=CFG["bme280_i2c_address"])


def acquire_pair():
    init_sensors()
    # Read sequentially on the same bus. No mixing readings from cycles.
    ambient = BME.pressure
    pipe = MPR.pressure
    if not valid_pressure(ambient, ambient=True) or not valid_pressure(pipe):
        raise ValueError("Invalid BME280 or MPRLS pressure")
    return ambient, pipe


def read_environment():
    """Informational only. Temperature/humidity never alter suction alarm."""
    global ROOM_TEMP_C, ROOM_HUMIDITY_PCT, LAST_ENV_ERROR
    if BME is None:
        return
    try:
        ROOM_TEMP_C = round(BME.temperature, 1)
        ROOM_HUMIDITY_PCT = round(BME.relative_humidity, 1)
        LAST_ENV_ERROR = ""
    except Exception as exc:
        LAST_ENV_ERROR = str(exc)[:100]
        ROOM_TEMP_C = None
        ROOM_HUMIDITY_PCT = None



class Buzzer:
    """Nonblocking alarm. Fault and low-suction patterns differ."""
    def __init__(self, pwm, interval):
        self.pwm = pwm
        self.interval = interval
        self.pattern = ()
        self.step = 0
        self.until = 0.0
        self.next_cycle = 0.0
        self.last_mode = None

    def update(self, now, state, enabled):
        mode = state if enabled else "OFF"
        if mode != self.last_mode:
            self.pwm.duty_cycle = 0
            self.last_mode = mode
            self.step = 0
            self.next_cycle = now
            self.until = now
            if state == FAULT:
                self.pattern = (0.4, 0.22, 0.4, 0.22, 0.4)  # 3 LONG
            elif state == LOW_SUCTION:
                self.pattern = (0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12)  # 5 SHORT
            else:
                self.pattern = ()
        if mode == "OFF":
            return
        if now < self.until or now < self.next_cycle:
            return
        if self.step >= len(self.pattern):
            self.pwm.duty_cycle = 0
            self.step = 0
            self.next_cycle = now + self.interval
            return
        self.pwm.duty_cycle = 32768 if self.step % 2 == 0 else 0
        self.until = now + self.pattern[self.step]
        self.step += 1


def fatal_alarm(message):
    """Invalid settings or irrecoverable software failure: audible local fault.

    No watchdog is intentionally started before validation. For a runtime
    exception AFTER WDT starts, WDT will reboot us even if this loop is stuck.
    """
    say("FATAL: " + str(message))
    try:
        if PIEZO_OUT is not None:
            while True:
                for duration in (0.4, 0.2, 0.4, 0.2, 0.4, 3.0):
                    PIEZO_OUT.duty_cycle = 32768 if duration == 0.4 else 0
                    time.sleep(duration)
    except Exception as exc:
        say("Buzzer failed: " + str(exc))
    while True:
        time.sleep(1)


def calibrate(cfg):
    """Deliberate paired-sensor zero, then working suction calibration.

    Stage zero: MPRLS tube DISCONNECTED and both sensors exposed to room air.
    Stage baseline: tube connected and mitigation fan operating normally.
    """
    global MPR, BME
    stage = cfg["calibration_stage"]
    if stage not in ("zero", "baseline"):
        return
    say("Calibration stage: " + stage)
    say("ZERO = tube disconnected; BASELINE = tube connected, fan on")
    interval = cfg["sample_interval_s"]
    end = time.monotonic() + cfg["average_window_s"]
    next_read = time.monotonic()
    total = 0.0
    count = 0
    while time.monotonic() < end:
        now = time.monotonic()
        if now >= next_read:
            next_read += interval
            try:
                ambient, pipe = acquire_pair()
                difference = ambient - pipe
                value = difference if stage == "zero" else difference - cfg["sensor_offset_hpa"]
                if not -50 <= value <= 100:
                    raise ValueError("Implausible pressure difference")
                total += value
                count += 1
                say("calibration pair " + str(count) + ": room=" + str(round(ambient, 3)) +
                    " pipe=" + str(round(pipe, 3)) + " diff=" + str(round(value, 3)))
            except Exception as exc:
                MPR, BME = None, None
                fatal_alarm("Calibration failed; check both sensors: " + str(exc))
        time.sleep(0.05)
    if count < 3:
        fatal_alarm("Not enough paired calibration readings")
    value = total / count
    if stage == "baseline" and not 0.2 < value <= 50:
        fatal_alarm("Corrected suction invalid; check fan, tubing and zero offset")
    try:
        save_calibration(stage, value)
    except Exception as exc:
        fatal_alarm("Cannot save calibration; restore settings backup: " + str(exc))
    say("Saved " + stage + " calibration: " + str(round(value, 4)) + " hPa")
    if stage == "zero":
        say("POWER OFF; attach tubing to suction pipe, then power on for baseline stage.")
        while True:
            time.sleep(1)
    say("Baseline calibration complete; rebooting in normal monitoring mode")
    time.sleep(1)
    microcontroller.reset()



def status_data(now):
    global FREE_HEAP_LOW_WATER
    gc.collect()
    heap = gc.mem_free()
    if FREE_HEAP_LOW_WATER is None or heap < FREE_HEAP_LOW_WATER:
        FREE_HEAP_LOW_WATER = heap
    result = MONITOR.snapshot(now)
    result.update({
        "wifi_connected": bool(wifi.radio.connected),
        "ip_address": str(wifi.radio.ipv4_address) if wifi.radio.connected else None,
        "last_wifi_error": LAST_NETWORK_ERROR,
        "last_http_error": LAST_HTTP_ERROR,
        "http_failures": HTTP_FAILURES,
        "wifi_connect_attempts": WIFI_ATTEMPTS,
        "free_heap_bytes": heap,
        "minimum_observed_free_heap_bytes": FREE_HEAP_LOW_WATER,
        "reset_reason": BOOT_RESET_REASON,
        "firmware": "radon-fan-monitor-2.1",
        "measurement_type": "offset_corrected_suction_from_two_absolute_sensors",
        "room_temperature_c": ROOM_TEMP_C,
        "room_humidity_percent": ROOM_HUMIDITY_PCT,
        "last_environment_error": LAST_ENV_ERROR,
    })
    return result


def build_server():
    global SERVER, POOL
    if not wifi.radio.connected:
        return
    try:
        POOL = socketpool.SocketPool(wifi.radio)
        srv = Server(POOL, debug=False)
        srv.socket_timeout = 0.25

        @srv.route("/", GET)
        def index(request: Request):
            d = status_data(time.monotonic())
            state = d["state"]
            if state == FAULT:
                meaning = "Monitor fault: measurements cannot be trusted."
            elif state == LOW_SUCTION:
                meaning = "Low suction alarm. Check fan and tubing."
            elif state == "LOW_SUCTION_PENDING":
                meaning = "Reduced suction detected. Alarm delay is running."
            elif state == STARTUP:
                meaning = "Waiting for first valid pressure reading."
            else:
                meaning = "Offset-corrected suction is above the configured minimum."
            ack = ""
            if state in (FAULT, LOW_SUCTION) and not d["alarm_acknowledged"]:
                ack = '<form method="post" action="/ack"><button>Acknowledge / silence buzzer</button></form>'
            body = HTML.format(
                state=safe_text(state), meaning=safe_text(meaning),
                suction=fmt(d["last_suction_hpa"]),
                suction_water="--" if d["last_suction_hpa"] is None else round(d["last_suction_hpa"] / 2.49089, 2),
                average=fmt(d["rolling_average_suction_hpa"]),
                threshold=fmt(d["minimum_suction_hpa"]), recovery=fmt(d["recovery_suction_hpa"]),
                baseline=fmt(d["baseline_suction_hpa"]), offset=fmt(d["sensor_offset_hpa"]),
                ambient=fmt(d["last_ambient_hpa"]), pipe=fmt(d["last_pipe_hpa"]),
                temperature=fmt(d["room_temperature_c"]), humidity=fmt(d["room_humidity_percent"]),
                sample_age=fmt(d["seconds_since_valid_reading"]),
                wifi_status="Connected" if d["wifi_connected"] else "Disconnected",
                ip=fmt(d["ip_address"]), uptime=d["uptime_seconds"], faults=d["total_failed_samples"],
                acknowledged=str(d["alarm_acknowledged"]), reset_reason=safe_text(d["reset_reason"]),
                heap=d["free_heap_bytes"], heap_low=d["minimum_observed_free_heap_bytes"],
                ack_button=ack)
            return Response(request, body, content_type="text/html")

        @srv.route("/status.json", GET)
        def json_status(request: Request):
            return Response(request, json.dumps(status_data(time.monotonic())), content_type="application/json")

        @srv.route("/ack", POST)
        def acknowledge(request: Request):
            MONITOR.acknowledge()
            return Response(request, "Alarm acknowledged. Return to / to see current state.", content_type="text/plain")

        srv.start(str(wifi.radio.ipv4_address), 80)
        SERVER = srv
        say("Web server started at http://" + str(wifi.radio.ipv4_address) + "/")
    except Exception as exc:
        say("HTTP start failed: " + str(exc))
        SERVER = None
        POOL = None


def stop_server():
    global SERVER, POOL
    if SERVER is not None:
        try:
            SERVER.stop()
        except Exception as exc:
            say("HTTP stop failed: " + str(exc))
    SERVER = None
    POOL = None
    gc.collect()


def connect_wifi(cfg):
    global WIFI_ATTEMPTS, LAST_NETWORK_ERROR
    if not cfg.get("ssid") or not cfg.get("wifi_pwd"):
        return False
    WIFI_ATTEMPTS += 1
    try:
        wifi.radio.hostname = cfg["hostname"]
        # Network call is synchronous. Limiting its timeout reduces (but does
        # NOT eliminate) interference with sensor acquisition and 8s watchdog.
        wifi.radio.connect(cfg["ssid"], cfg["wifi_pwd"], timeout=cfg["wifi_connect_timeout_s"])
        LAST_NETWORK_ERROR = ""
        say("Wi-Fi connected: " + str(wifi.radio.ipv4_address))
        return True
    except Exception as exc:
        LAST_NETWORK_ERROR = str(exc)[:100]
        say("Wi-Fi unavailable; local alarm continues: " + LAST_NETWORK_ERROR)
        return False


def main():
    global MONITOR, CFG, PIEZO_OUT, MPR, BME, LAST_HTTP_ERROR, HTTP_FAILURES
    PIEZO_OUT = pwmio.PWMOut(PIEZO, frequency=4000, duty_cycle=0)
    CFG = load_settings()
    if CFG["calibration_stage"] != "ready":
        calibrate(CFG)
        return

    started = time.monotonic()
    MONITOR = Monitor(CFG, started)
    buzzer = Buzzer(PIEZO_OUT, CFG["alarm_repeat_s"])
    interval = CFG["sample_interval_s"]
    next_sample = started
    next_network = started + 1.0
    next_poll = started
    last_sample_loop = started
    say("Monitoring started. Minimum suction: " + str(round(MONITOR.minimum_suction_hpa, 3)) + " hPa")

    # Initialize before enabling the WDT; a failed sensor is a local fault, not
    # a reboot loop. Read once BEFORE attempting any Wi-Fi operation.
    try:
        ambient, pipe = acquire_pair()
        MONITOR.update(time.monotonic(), ambient, pipe)
        read_environment()
    except Exception as exc:
        MPR, BME = None, None
        MONITOR.update(time.monotonic(), error=exc)
        say("Initial sensor error: " + str(exc))
    last_sample_loop = time.monotonic()
    next_sample = last_sample_loop + interval
    next_environment = last_sample_loop + 60

    from watchdog import WatchDogMode
    wdt = microcontroller.watchdog
    wdt.timeout = 8
    wdt.mode = WatchDogMode.RESET
    wdt.feed()

    # Deterministic cooperative loop, rather than unprotected asyncio tasks.
    # Critical operations first; Wi-Fi and HTTP are best effort.
    while True:
        now = time.monotonic()
        if now >= next_sample:
            last_sample_loop = now
            try:
                ambient, pipe = acquire_pair()
                MONITOR.update(now, ambient, pipe)
                say("suction hPa: " + str(round(MONITOR.last_suction_hpa, 3)) + " avg: " +
                    str(round(MONITOR.average_suction_hpa, 3)) + " state: " + MONITOR.state)
            except Exception as exc:
                MPR, BME = None, None
                MONITOR.update(now, error=exc)
                say("Sensor read failure: " + str(exc))
            # Skip missed deadlines; do not run a burst of stale readings.
            next_sample = now + interval
        if now >= next_environment and BME is not None:
            next_environment = now + 60
            read_environment()

        now = time.monotonic()
        MONITOR.evaluate(now)
        buzzer.update(now, MONITOR.state, MONITOR.audible())
        # Feed only when the acquisition scheduler is still making progress.
        # Persistent sensor failure is explicitly alarmed and does not force
        # repeated resets. A hung scheduler or event loop should reset.
        if now - last_sample_loop < max(20, 2 * interval + 5):
            wdt.feed()

        if now >= next_network:
            next_network = now + CFG["wifi_retry_s"]
            if not wifi.radio.connected and CFG.get("ssid") and CFG.get("wifi_pwd"):
                stop_server()
                # Give the WDT its full budget before this bounded call.
                wdt.feed()
                if connect_wifi(CFG):
                    build_server()
            elif wifi.radio.connected and SERVER is None:
                build_server()

        now = time.monotonic()
        if not wifi.radio.connected and SERVER is not None:
            stop_server()
        if SERVER is not None and now >= next_poll:
            next_poll = now + 0.1
            try:
                SERVER.poll()
                LAST_HTTP_ERROR = ""
            except Exception as exc:
                LAST_HTTP_ERROR = str(exc)[:100]
                HTTP_FAILURES += 1
                say("HTTP poll failed: " + LAST_HTTP_ERROR)
                stop_server()
                # Give a broken socket a short recovery period, not a tight loop.
                next_network = time.monotonic() + 10
        time.sleep(0.05)


try:
    main()
except (ConfigError, ValueError, KeyError, OSError) as error:
    fatal_alarm("Startup/configuration error: " + str(error))
except Exception as error:
    # WDT will reset if active; otherwise local fault buzzer continues.
    fatal_alarm("Unhandled exception: " + str(error))
