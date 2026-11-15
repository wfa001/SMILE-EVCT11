"""Regression tests for removed report-backed wallbox sensors."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call
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


class G1TSessionSensorTests(unittest.TestCase):
    def test_sensor_setup_registers_session_energy_for_g2t_only(self):
        module = ast.parse((BASE / "sensor.py").read_text(encoding="utf-8"))
        setup = next(node for node in module.body
                     if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry")
        namespace = {node.name: Mock(name=node.name) for node in module.body
                     if isinstance(node, ast.ClassDef)}
        namespace.update(DOMAIN="bridge", UnitOfPower=SimpleNamespace(WATT="W"))
        source = compile(ast.Module(body=[setup], type_ignores=[]), "sensor setup", "exec")
        exec(source, namespace)
        for profile, include_session in (("g1T", False), ("g2T", True)):
            coordinator = SimpleNamespace(data={}, api=SimpleNamespace(wallbox_generation=lambda _: profile))
            hass = SimpleNamespace(data={"bridge": {"current": coordinator}})
            entry = SimpleNamespace(entry_id="current")
            registered = []
            asyncio.run(namespace["async_setup_entry"](hass, entry, registered.extend))
            self.assertIn(namespace["AlphaESSWallboxDailyEnergySensor"].return_value, registered)
            for sensor in ("AlphaESSWallboxEnergySensor", "AlphaESSWallboxLastChargeSensor"):
                self.assertEqual(namespace[sensor].return_value in registered, include_session)

    def test_cleanup_is_limited_to_g1t_and_to_the_current_config_entry(self):
        module = ast.parse((BASE / "__init__.py").read_text(encoding="utf-8"))
        setup = next(node for node in module.body
                     if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry")
        guard = next(node for node in setup.body if isinstance(node, ast.If)
                     and any(isinstance(child, ast.Constant) and child.value == "last_completed_energy"
                             for child in ast.walk(node)))
        cleanup = compile(ast.Module(body=[guard], type_ignores=[]), "G1T registry cleanup", "exec")
        for profile in ("g1T", "g2T", None):
            for foreign_row in (False, True):
                registry = Mock()
                registry.async_get_entity_id.side_effect = lambda _, __, unique_id: "sensor." + unique_id
                registry.async_get.side_effect = lambda entity_id: SimpleNamespace(
                    config_entry_id="other" if foreign_row and entity_id.endswith("last_energy") else "current"
                )
                exec(cleanup, {"generation": profile, "Platform": SimpleNamespace(SENSOR="sensor"),
                               "DOMAIN": "bridge", "system_serial": "system", "entity_registry": registry,
                               "entry": SimpleNamespace(entry_id="current")})
                expected = [] if profile != "g1T" else (
                    [call("sensor.system_last_completed_energy")] if foreign_row
                    else [call("sensor.system_last_energy"), call("sensor.system_last_completed_energy")]
                )
                self.assertEqual(registry.async_remove.call_args_list, expected)


if __name__ == "__main__":
    unittest.main()
