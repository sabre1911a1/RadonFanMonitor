# Audible indications — v2.1

The old 2024 multi-digit calibration/Wi-Fi codes are **not used by this firmware**.

| Pattern | Status | What to do |
|---|---|---|
| Repeating **five short beeps** | `LOW_SUCTION_ALARM` | Valid paired readings indicate sustained inadequate suction. Verify fan, tubing, conventional manometer, and radon separately. |
| Repeating **three longer beeps** | `MONITOR_FAULT` | One/both pressure sensors cannot be read reliably, data is stale, or configuration/software failed. Inspect USB serial and I²C on GP12/GP13. |
| Silence | May be NORMAL, PENDING, STARTUP or **acknowledged alarm** | Check the dashboard or serial status. Silence alone does not mean healthy. |

The alarm can be **acknowledged** from the trusted LAN web page. Acknowledgment only silences the *current* buzzer; it does not clear the alarm state. A new alarm episode re-enables the buzzer. Wi-Fi outages do not cause local beeping: the mitigation alarm continues independently, while UniFi may provide a wireless-client disconnect notification.

Calibration progress and failures are printed to the USB serial console; do not rely on undocumented legacy beep numbers for those operations.
