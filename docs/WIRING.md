# Pico W wiring — v2.1

The original 2024 wiring spreadsheet and code agree on the MPRLS connections below. The **BME280 is added to the same I²C bus**, not connected to the pipe.

| Function | Pico W | Physical device connection |
|---|---|---|
| I²C SDA | **GP12** | MPRLS SDA **and** BME280 SDI/SDA |
| I²C SCL | **GP13** | MPRLS SCL **and** BME280 SCK/SCL |
| MPRLS reset | GP15 | MPRLS RST |
| MPRLS end of conversion | GP16 | MPRLS EOC |
| Buzzer positive | GP2 | Piezo + |
| Shared 3.3 V | Pico **3V3(OUT)** | MPRLS VIN and BME280 VIN (Adafruit breakout compatible) |
| Shared ground | GND | Both breakouts and buzzer - |

Original harness color reference: SDA **white/green**, SCL **green**, MPRLS reset **brown**, MPRLS EOC **white/brown**, 3.3 V **blue**, GND **white/blue**, piezo + **blue**. There is **no historical color mapping for the new BME280 wires**; choose and document one before permanent assembly.

**BME280 address:** Adafruit's board defaults to **0x77** (`bme280_i2c_address: 119`). Some configurations use **0x76** (`118` decimal). The MPRLS address is **0x18**. Ensure SDA/SCL and supply share a common reference. The Adafruit breakouts provide I²C pull-ups; confirm appropriate bus voltage when mixing boards.

## Physical arrangement

```text
Room air        [BME280]  (vented enclosure, no tube)
    |               |
    +-- Pico W ------+--- I²C bus GP12/13
           |
           +--- [MPRLS port]--- tubing ---> suction tap in radon pipe
           |
           +--- [Piezo buzzer] GP2
```

The pressure tube goes **only** from the MPRLS port to the radon suction pipe. The BME280 must sense room air, away from enclosed heat, water ingress, or direct drafts. Power the Pico **off** for wiring changes. Avoid any mains wiring around the sensor connectors.

**Calibration:** For the *zero* stage, disconnect tubing from the MPRLS pressure port, exposing it to room air alongside the BME280. For the *baseline* stage, reconnect tubing and verify the mitigation fan is operating normally.

The original project's beep troubleshooting documentation incorrectly instructed using GP20/GP21 for I²C. Those pins are not the actual SDA/SCL assignments; use GP12 and GP13.
