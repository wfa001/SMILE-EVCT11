"""Guarded G1T schedule discovery must never manufacture absent fields."""
import ast
from pathlib import Path
import unittest
from typing import Any
from types import SimpleNamespace


def load_helpers():
    path = Path(__file__).resolve().parents[1] / "custom_components/alphaess_portal_bridge/entity.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    selected = {"wallbox_object", "settings_object", "time_period", "scheduled_charging_selected", "time_period_selected"}
    nodes = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in selected]
    namespace = {"Any": Any, "AlphaESSWallboxCoordinator": object}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), "exec"), namespace)
    return namespace


class G1TScheduleSchemaTests(unittest.TestCase):
    def setUp(self):
        self.helpers = load_helpers()

    def coordinator(self, settings):
        wallbox = {"g1T": settings}
        return SimpleNamespace(
            data={"configuration": {"wallbox": wallbox}, "wallbox_serial": "private-serial"},
            api=SimpleNamespace(_find_wallbox_data=lambda config, serial: config["wallbox"]),
        )

    def test_valid_existing_period_exposed(self):
        item = self.coordinator({"chargeStrategy": 1, "timePeriods": [
            {"startTime": "08:07", "endTime": "09:23", "isEnable": True}
        ]})
        self.assertEqual(self.helpers["time_period"](item, 0)["startTime"], "08:07")
        self.assertTrue(self.helpers["time_period_selected"](item, 0))

    def test_missing_timing_schema_not_exposed(self):
        item = self.coordinator({"chargeStrategy": 1, "timePeriods": [
            {"startTime": "08:07", "isEnable": True}
        ]})
        self.assertEqual(self.helpers["time_period"](item, 0), {})
        self.assertFalse(self.helpers["time_period_selected"](item, 0))

    def test_no_strategy_does_not_assume_scheduled(self):
        item = self.coordinator({"timePeriods": [
            {"startTime": "08:07", "endTime": "09:23", "isEnable": True}
        ]})
        self.assertFalse(self.helpers["scheduled_charging_selected"](item))
        self.assertFalse(self.helpers["time_period_selected"](item, 0))


if __name__ == "__main__":
    unittest.main()
