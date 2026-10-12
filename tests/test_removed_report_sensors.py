"""Regression tests for removed report-backed wallbox sensors."""
import ast
from pathlib import Path
import unittest

BASE = Path(__file__).resolve().parents[1] / "custom_components" / "alphaess_portal_bridge"


class RemovedReportSensorTests(unittest.TestCase):
    def test_removed_sensor_classes_and_setup_instances(self):
        source = (BASE / "sensor.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        classes = {node.name for node in module.body if isinstance(node, ast.ClassDef)}
        self.assertNotIn("AlphaESSTodayChargeReportSensor", classes)
        self.assertNotIn("AlphaESSLatestChargeReportSensor", classes)
        self.assertNotIn("AlphaESSTodayChargeReportSensor(", source)
        self.assertNotIn("AlphaESSLatestChargeReportSensor(", source)

    def test_live_energy_unique_ids_remain_stable(self):
        source = (BASE / "sensor.py").read_text(encoding="utf-8")
        self.assertIn('"chargingAmount", "today_energy"', source)
        self.assertIn('"lastChargingAmount", "last_energy"', source)

    def test_removed_registry_ids_are_cleaned_up(self):
        source = (BASE / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('f"{system_serial}_today_report_energy"', source)
        self.assertIn('f"{system_serial}_latest_charge_report"', source)
        self.assertIn('entity_registry.async_remove(old_entity_id)', source)


if __name__ == "__main__":
    unittest.main()
