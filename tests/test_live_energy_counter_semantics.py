"""Regression checks for the documented live energy counter semantics."""
import ast
from pathlib import Path
import unittest
from types import SimpleNamespace


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


    def test_actual_live_sensor_values_and_state_class(self):
        """Execute the real sensor class in isolation, not only a text search."""
        source = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls_node = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "AlphaESSWallboxEnergySensor"
        )

        class FakeBase:
            def __init__(self, coordinator, entry, key):
                self.coordinator = coordinator

        namespace = {
            "AlphaESSWallboxEntity": FakeBase,
            "SensorEntity": type("SensorEntity", (), {}),
            "AlphaESSWallboxCoordinator": object,
            "ConfigEntry": object,
            "SensorDeviceClass": SimpleNamespace(ENERGY="energy"),
            "SensorStateClass": SimpleNamespace(TOTAL_INCREASING="total_increasing"),
            "UnitOfEnergy": SimpleNamespace(KILO_WATT_HOUR="kWh"),
        }
        # Annotation names are supplied to compile the original class unmodified.
        exec(
            compile(ast.fix_missing_locations(ast.Module(body=[cls_node], type_ignores=[])), str(SOURCE), "exec"),
            namespace,
        )
        sensor_type = namespace["AlphaESSWallboxEnergySensor"]
        coordinator = SimpleNamespace(data={"wallbox_status": {"chargingAmount": 2.5, "lastChargingAmount": 0.7}})
        daily = sensor_type(coordinator, None, "Heute geladen", "chargingAmount", "today_energy")
        segment = sensor_type(coordinator, None, "Aktueller / letzter Ladeabschnitt", "lastChargingAmount", "last_energy")
        self.assertEqual(daily.native_value, 2.5)
        self.assertEqual(segment.native_value, 0.7)
        self.assertEqual(daily._attr_state_class, "total_increasing")
        self.assertIsNone(getattr(segment, "_attr_state_class", None))
        coordinator.data = {"wallbox_status": {"chargingAmount": 0, "lastChargingAmount": None}}
        self.assertEqual(daily.native_value, 0.0)
        self.assertIsNone(segment.native_value)
        coordinator.data = {"wallbox_status": {"chargingAmount": "invalid"}}
        self.assertIsNone(daily.native_value)
        coordinator.data = {"wallbox_status": {}}
        self.assertIsNone(daily.native_value)


if __name__ == "__main__":
    unittest.main()
