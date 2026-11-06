"""Give the Pico filesystem write access only during EXPLICIT calibration.

Set calibration_stage to 'zero' with both values null, disconnect MPRLS
pressure tubing, then reboot. After offset calibration, the device saves
stage 'baseline'; power off, attach tubing, and restart for baseline.
NEVER edit CIRCUITPY from USB host while calibration is running (Pico RW).
"""
import json
import storage

try:
    with open('/settings.json', 'r') as file:
        cfg = json.load(file)
    calibration = cfg.get('calibration_stage') in ('zero', 'baseline')
except Exception as exc:
    print('boot.py: settings unreadable; keeping Pico filesystem read-only:', exc)
    calibration = False

storage.remount('/', readonly=not calibration)
