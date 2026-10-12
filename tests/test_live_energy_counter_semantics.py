"""Regression checks for the documented live energy counter semantics."""
import ast
from pathlib import Path
import unittest


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "custom_components/alphaess_portal_bridge/sensor.py"
)


class LiveEnergyCounterTests(unittest.TestCase):
    def test_unique_ids_and_sources_remain_stable(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('"Heute geladen", "chargingAmount", "today_energy"', source)
        self.assertIn(
            '"Aktueller / letzter Ladeabschnitt", "lastChargingAmount", "last_energy"',
            source,
        )

    def test_only_daily_counter_is_total_increasing(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('if key == "chargingAmount":', source)
        self.assertIn("self._attr_state_class = SensorStateClass.TOTAL_INCREASING", source)

    def test_missing_values_are_not_fabricated(self):
        source = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        klass = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "AlphaESSWallboxEnergySensor"
        )
        native = next(
            node for node in klass.body
            if isinstance(node, ast.FunctionDef) and node.name == "native_value"
        )
        segment = ast.get_source_segment(source, native)
        self.assertIn("else None", segment)
        self.assertNotIn("return 0", segment)

    def test_energy_sensor_has_no_value_reconstruction_or_extra_api_calls(self):
        source = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        klass = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "AlphaESSWallboxEnergySensor"
        )
        segment = ast.get_source_segment(source, klass)
        self.assertNotIn("async_get_", segment)
        self.assertNotIn("async_request_refresh", segment)


if __name__ == "__main__":
    unittest.main()
