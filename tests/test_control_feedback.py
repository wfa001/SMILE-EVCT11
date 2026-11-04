"""Control explanations must follow known guards rather than guessed causes."""
from pathlib import Path
import runpy
import unittest

reason = runpy.run_path(str(Path(__file__).resolve().parents[1] /
    'custom_components/alphaess_portal_bridge/control_feedback.py'))['control_reason']


class ControlFeedbackTests(unittest.TestCase):
    def test_allowed_states_do_not_get_a_blocking_message(self):
        for control, status in [('START', 'PendingStart'), ('START', 'CharingStopped'),
                                ('STOP', 'Charging'), ('STOP', 'WaitingForChargingPile')]:
            self.assertIsNone(reason(control, 'g2T', {'chargeStrategy': 0}, status, True))

    def test_manual_requirement_is_g2_specific(self):
        self.assertIn('Manuell', reason('START', 'g2T', {'chargeStrategy': 2}, 'PendingStart', True))
        self.assertIsNone(reason('START', 'g1T', {}, 'PendingStart', True))

    def test_connection_and_bad_status_are_not_confused_with_vehicle_or_pv(self):
        self.assertIn('Portal-Verbindung', reason('START', 'g2T', {'chargeStrategy': 0}, 'PendingStart', False))
        for status in (None, {}, [], 1):
            self.assertIn('Wallboxstatus', reason('START', 'g1T', {}, status, True))
        message = reason('START', 'g1T', {}, 'InsufficientPower', True)
        self.assertIn('unzureichende Leistung', message)
        self.assertNotIn('PV', message)
        self.assertIn('anschließen', reason('START', 'g1T', {}, 'NotInsertedGun', True))


if __name__ == '__main__':
    unittest.main()
