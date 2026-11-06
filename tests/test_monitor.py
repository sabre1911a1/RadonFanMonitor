"""Run on a PC: python -m unittest discover -s tests -v"""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CIRCUITPY"))
from monitor import (Monitor, validate, ConfigError, NORMAL, FAULT, PENDING,
                     LOW_SUCTION, valid_pressure, calculate_suction)


def config(**overrides):
    cfg = json.loads((ROOT / 'CIRCUITPY' / 'settings.example.json').read_text())
    cfg.update({"calibration_stage": "ready", "sensor_offset_hpa": 0.0,
                "baseline_suction_hpa": 2.911, "sample_interval_s": 1,
                "average_window_s": 10, "alarm_delay_s": 5,
                "stale_after_s": 5, "sensor_fault_after": 2,
                "sensor_recovery_samples": 3})
    cfg.update(overrides)
    return cfg


def sample(m, t, suction=2.911, ambient=953.0, error=None):
    if error is not None:
        m.update(t, error=error)
    else:
        pipe = ambient - m.cfg['sensor_offset_hpa'] - suction
        m.update(t, ambient, pipe)


class MonitorTests(unittest.TestCase):
    def test_minimum_suction_and_recovery(self):
        m = Monitor(config())
        self.assertAlmostEqual(m.minimum_suction_hpa, 2.6199)
        self.assertAlmostEqual(m.recover_suction_hpa, 2.7699)

    def test_normal_reading_and_units(self):
        m = Monitor(config(sensor_offset_hpa=0.4))
        sample(m, 0, suction=2.911)
        self.assertEqual(m.state, NORMAL)
        self.assertAlmostEqual(m.last_suction_hpa, 2.911)
        self.assertFalse(m.audible())
        d = m.snapshot(0)
        self.assertAlmostEqual(d['last_suction_hpa'], 2.911)
        self.assertEqual(d['sensor_offset_hpa'], 0.4)
        self.assertNotIn('last_reading_hpa', d)

    def test_barometric_pressure_shift_cancels(self):
        m = Monitor(config(sensor_offset_hpa=0.6))
        for n, ambient in enumerate((955, 945, 935, 925, 910, 965)):
            sample(m, n, suction=2.911, ambient=ambient)
        self.assertAlmostEqual(m.average_suction_hpa, 2.911, places=8)
        self.assertEqual(m.state, NORMAL)

    def test_loss_starts_pending_then_alarm_ack(self):
        m = Monitor(config())
        for now in range(8):
            sample(m, now, suction=0.0)
        self.assertEqual(m.state, LOW_SUCTION)
        self.assertTrue(m.audible())
        self.assertTrue(m.acknowledge())
        self.assertFalse(m.audible())

    def test_alarm_recovery_requires_hysteresis(self):
        m = Monitor(config(average_window_s=10))
        for now in range(12):
            sample(m, now, suction=0.0)
        self.assertEqual(m.state, LOW_SUCTION)
        m.acknowledge()
        for now in range(12, 32):
            sample(m, now, suction=2.7)
        self.assertEqual(m.state, LOW_SUCTION)
        for now in range(32, 52):
            sample(m, now, suction=3.0)
        self.assertEqual(m.state, NORMAL)
        self.assertFalse(m.acknowledged)

    def test_rearms_after_recovery(self):
        m = Monitor(config())
        for t in range(10): sample(m, t, 0.0)
        m.acknowledge()
        for t in range(10, 30): sample(m, t, 2.911)
        self.assertEqual(m.state, NORMAL)
        for t in range(30, 50): sample(m, t, 0.0)
        self.assertEqual(m.state, LOW_SUCTION)
        self.assertTrue(m.audible())

    def test_one_failed_pair_does_not_alarm_immediately(self):
        m = Monitor(config())
        sample(m, 0)
        sample(m, 1, error=OSError("BME280 NACK"))
        self.assertEqual(m.state, NORMAL)
        sample(m, 2, error=OSError("MPRLS timeout"))
        self.assertEqual(m.state, FAULT)
        self.assertEqual(m.total_failures, 2)
        self.assertTrue(m.audible())

    def test_initial_sensor_failure_is_fault(self):
        m = Monitor(config())
        sample(m, 0, error=ImportError("adafruit_bme280 missing"))
        self.assertEqual(m.state, FAULT)

    def test_fault_recovery_needs_three_good_pairs(self):
        m = Monitor(config())
        sample(m, 0, error=OSError('disconnect'))
        m.acknowledge()
        sample(m, 1)
        sample(m, 2)
        self.assertEqual(m.state, FAULT)
        self.assertFalse(m.audible())
        sample(m, 3)
        self.assertEqual(m.state, NORMAL)
        self.assertFalse(m.acknowledged)

    def test_recovery_interrupted_by_failure(self):
        m = Monitor(config())
        sample(m, 0, error=OSError('disconnect'))
        sample(m, 1)
        sample(m, 2, error=OSError('another failure'))
        sample(m, 3)
        sample(m, 4)
        self.assertEqual(m.state, FAULT)
        sample(m, 5)
        self.assertEqual(m.state, NORMAL)

    def test_stale_pairs_fault(self):
        m = Monitor(config())
        sample(m, 0)
        m.evaluate(6)
        self.assertEqual(m.state, FAULT)

    def test_invalid_sensor_values(self):
        for bad in (None, float('nan'), float('inf'), -1, 0, 1300, '900', True):
            self.assertFalse(valid_pressure(bad))
        self.assertTrue(valid_pressure(950.1))
        self.assertTrue(valid_pressure(400, ambient=True))
        for ambient, pipe in [(float('nan'), 952), (952, float('inf')), (200, 950), (952, 1400)]:
            with self.assertRaises(ValueError):
                calculate_suction(ambient, pipe, 0)

    def test_negative_suction_is_low_suction_not_sensor_fault(self):
        m = Monitor(config())
        for i in range(9): sample(m, i, suction=-0.1)
        self.assertEqual(m.state, LOW_SUCTION)

    def test_ring_window_bounded(self):
        m = Monitor(config())
        for i in range(40): sample(m, i, 2.8 + (i % 3) * .01)
        self.assertEqual(m.value_count, 10)
        self.assertEqual(m.total_samples, 40)
        self.assertTrue(2.8 < m.average_suction_hpa < 2.83)

    def test_calibration_stage_validation(self):
        zero = json.loads((ROOT / 'CIRCUITPY' / 'settings.example.json').read_text())
        self.assertEqual(validate(zero)['calibration_stage'], 'zero')
        with self.assertRaises(ConfigError): Monitor(zero)
        baseline = dict(zero, calibration_stage='baseline', sensor_offset_hpa=-1.2)
        self.assertEqual(validate(baseline)['calibration_stage'], 'baseline')
        for invalid in [dict(zero, calibration_stage='ready'),
                        dict(zero, calibration_stage='baseline'),
                        dict(zero, calibration_stage='zero', sensor_offset_hpa=0),
                        dict(baseline, baseline_suction_hpa=-3),
                        dict(config(), baseline_suction_hpa=0.1)]:
            with self.assertRaises(ConfigError): validate(invalid)

    def test_offset_zero_is_valid(self):
        c=config(sensor_offset_hpa=0.0)
        self.assertEqual(validate(c)['sensor_offset_hpa'], 0.0)

    def test_validation_rejects_hysteresis_exceeding_loss_margin(self):
        with self.assertRaises(ConfigError): validate(config(hysteresis_hpa=1.0))

    def test_validation_rejects_bad_address(self):
        with self.assertRaises(ConfigError): validate(config(bme280_i2c_address=120))
        self.assertEqual(validate(config(bme280_i2c_address=118))['bme280_i2c_address'], 118)

    def test_five_minute_window_delays_alarm(self):
        c = config(sample_interval_s=10, average_window_s=300, alarm_delay_s=300,
                   stale_after_s=35)
        m = Monitor(c)
        for t in range(0, 300, 10): sample(m, t, suction=2.911)
        alarm_t = None
        for t in range(300, 1100, 10):
            sample(m, t, suction=0)
            if m.state == LOW_SUCTION:
                alarm_t=t
                break
        self.assertIsNotNone(alarm_t)
        self.assertGreaterEqual(alarm_t, 600)
        self.assertLess(alarm_t, 680)

    def test_independent_sensor_failure_prevents_normal(self):
        for msg in ('BME280 disconnected', 'MPRLS disconnected'):
            m=Monitor(config(sensor_fault_after=1))
            sample(m, 0)
            sample(m, 1, error=OSError(msg))
            self.assertEqual(m.state, FAULT)


if __name__ == '__main__':
    unittest.main()
