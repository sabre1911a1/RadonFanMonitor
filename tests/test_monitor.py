"""Run on a PC: python -m unittest discover -s tests -v"""
import json
import math
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CIRCUITPY"))
from monitor import (Monitor, validate, ConfigError, NORMAL, FAULT, PENDING,
                     LOW_SUCTION, valid_pressure)


def config(**overrides):
    c = json.loads((ROOT / 'CIRCUITPY' / 'settings.example.json').read_text())
    c.update({"sample_interval_s":1, "average_window_s":10, "alarm_delay_s":5,
              "stale_after_s":5, "sensor_fault_after":2})
    c.update(overrides)
    return c


class MonitorTests(unittest.TestCase):
    def test_preserves_original_threshold_math(self):
        m = Monitor(config())
        self.assertAlmostEqual(m.threshold_hpa, 950.1561, places=4)
        self.assertAlmostEqual(m.recover_hpa, 950.0061, places=4)

    def test_normal_pressure(self):
        m = Monitor(config())
        for now in range(8):
            m.update(now, 949.865)
        self.assertEqual(m.state, NORMAL)
        self.assertEqual(m.total_samples, 8)
        self.assertFalse(m.audible())

    def test_alarm_delay_and_ack(self):
        m = Monitor(config())
        for now in range(8):
            m.update(now, 951.0)
        self.assertEqual(m.state, LOW_SUCTION)
        self.assertTrue(m.audible())
        self.assertTrue(m.acknowledge())
        self.assertFalse(m.audible())
        self.assertTrue(m.acknowledged)

    def test_new_alarm_rearms_after_recovery(self):
        m = Monitor(config())
        for t in range(10):
            m.update(t, 951.0)
        self.assertEqual(m.state, LOW_SUCTION)
        m.acknowledge()
        for t in range(10, 35):
            m.update(t, 949.0)
        self.assertEqual(m.state, NORMAL)
        self.assertFalse(m.acknowledged)
        for t in range(35, 55):
            m.update(t, 951.0)
        self.assertEqual(m.state, LOW_SUCTION)
        self.assertTrue(m.audible())

    def test_consecutive_sensor_failures_enter_fault(self):
        m = Monitor(config())
        m.update(0, 949.8)
        m.update(1, error=OSError("I2C bus timeout"))
        self.assertEqual(m.state, NORMAL)
        m.update(2, error=OSError("I2C bus timeout"))
        self.assertEqual(m.state, FAULT)
        self.assertTrue(m.audible())
        self.assertEqual(m.total_failures, 2)

    def test_initial_failure_is_immediate_fault(self):
        m = Monitor(config())
        m.update(0, error=ValueError("missing sensor"))
        self.assertEqual(m.state, FAULT)

    def test_stale_data_is_a_fault(self):
        m = Monitor(config())
        m.update(0, 949.8)
        m.evaluate(6)
        self.assertEqual(m.state, FAULT)

    def test_fault_recovery_with_valid_sample(self):
        m = Monitor(config())
        m.update(0, error=OSError("missing"))
        m.acknowledge()
        m.update(1, 949.8)
        self.assertEqual(m.state, NORMAL)
        self.assertFalse(m.acknowledged)

    def test_invalid_sensor_values(self):
        for bad in (None, float("nan"), float("inf"), -1, 0, 1300, "900"):
            self.assertFalse(valid_pressure(bad))
        self.assertTrue(valid_pressure(950.1))

    def test_rolling_window_is_bounded(self):
        m = Monitor(config())
        for i in range(40):
            m.update(i, 949.0 + (i % 3) * .01)
        self.assertEqual(m.value_count, 10)
        self.assertEqual(m.total_samples, 40)
        self.assertTrue(949.0 < m.average_hpa < 949.03)

    def test_bad_calibration_rejected(self):
        for a, w in ((0, 950), (949, 950), (951, 951)):
            c = config(ambient_pressure_hpa=a, working_pressure_hpa=w)
            if a == 0:
                self.assertEqual(validate(c)["ambient_pressure_hpa"], 0)
                with self.assertRaises(ConfigError): Monitor(c)
            else:
                with self.assertRaises(ConfigError): validate(c)

    def test_percent_not_ambiguous_absolute(self):
        for v in (0, -1, 101, 200.5):
            with self.assertRaises(ConfigError): validate(config(alarm_loss_percent=v))

    def test_simulated_failure_over_original_five_minute_window(self):
        c = config(sample_interval_s=10, average_window_s=300, alarm_delay_s=300,
                   stale_after_s=35)
        m = Monitor(c)
        # Stable fan operation for 5 minutes, then instant pressure increase.
        for t in range(0, 300, 10):
            m.update(t, 949.865)
        first_alarm = None
        for t in range(300, 1000, 10):
            m.update(t, 952.776)
            if m.state == LOW_SUCTION:
                first_alarm = t
                break
        self.assertIsNotNone(first_alarm)
        self.assertGreaterEqual(first_alarm, 600)
        self.assertLess(first_alarm, 680)

    def test_snapshot_does_not_claim_live_differential_pressure(self):
        m = Monitor(config())
        m.update(0, 949.8)
        d = m.snapshot(0)
        self.assertEqual(d['calibration_delta_hpa'], 2.911)
        self.assertNotIn('current_suction', d)


if __name__ == '__main__':
    unittest.main()
