"""Allow Pico-owned writes ONLY during a deliberately requested calibration.

To calibrate, set ambient_pressure_hpa to 0 in settings.json and reboot.
After ambient calibration, power off, attach pressure tubing, and power on.
Do not edit CIRCUITPY from a host while its filesystem is Pico-writable.
"""
import json
import storage

try:
    with open('/settings.json', 'r') as f:
        cfg = json.load(f)
    calibrating = (cfg.get('ambient_pressure_hpa', -1) == 0 or
                   cfg.get('working_pressure_hpa', -1) == 0)
except Exception as exc:
    print('boot.py: settings unreadable; not enabling Pico writes:', exc)
    calibrating = False

storage.remount('/', readonly=not calibrating)
