# Pico W wiring — verified against original project and WireMap.xlsx

| Device | Connection | Pico W |
|---|---|---|
| MPRLS | SDA (white/green) | GP12 |
| MPRLS | SCL (green) | GP13 |
| MPRLS | Reset (brown) | GP15 |
| MPRLS | End of conversion / EOC (white/brown) | GP16 |
| MPRLS | 3.3V (blue) | 3V3 supply |
| MPRLS | GND (white/blue) | GND |
| Piezo buzzer | Positive (blue) | GP2 |
| Piezo buzzer | Negative (white/blue) | GND |

The MPRLS **ported pressure fitting** connects through tubing to the radon mitigation suction pipe. The MPRLS board and Pico stay in the room, not in the airflow. The sensor reading is the absolute pressure at that fitting; the board does **not** automatically produce a differential reading between pipe and room.

The historic `Beep Codes.txt` incorrectly described GP20/GP21 for I²C. The actual original spreadsheet and software use **GP12 (SDA), GP13 (SCL)**. Do not follow the obsolete pin numbers. The original `wire_map.png` remains in the repository root for historical reference; this text file is the corrected wiring reference for v2.

**Never connect a GPIO directly to the pipe or to mains wiring.** Turn off power when attaching or removing sensor electrical connections; confirm the breakout uses 3.3V logic before connecting to the Pico.
