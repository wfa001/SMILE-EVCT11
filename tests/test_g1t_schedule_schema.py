"""Guarded G1T schedule discovery must never manufacture absent fields."""
import ast
import asyncio
import copy
import re
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


def load_api_writer():
    path = Path(__file__).resolve().parents[1] / "custom_components/alphaess_portal_bridge/api.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    api_class = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "AlphaESSPortalApi")
    method = next(node for node in api_class.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_update_time_period")
    method.decorator_list = []  # Test method's real body without HA locking machinery.
    namespace = {"copy": copy, "re": re, "PortalConnectionError": RuntimeError}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(path), "exec"), namespace)
    return namespace["async_update_time_period"]


class ScheduleWriterTests(unittest.TestCase):
    def setUp(self):
        self.writer = load_api_writer()
        self.patches = []
        self.configuration = {"wallbox": {"g1T": {
            "timePeriods": [
                {"startTime": "08:00", "endTime": "09:00", "isEnable": False},
                {"startTime": "10:00", "endTime": "11:00"},
                {"startTime": "12:00", "endTime": "13:00"},
            ]
        }}}
        self.api = SimpleNamespace(
            _system_serial="system",
            _wallbox_serial="wallbox",
            _async_get=self.fake_get,
            _async_authenticated_patch=self.fake_patch,
            _find_wallbox_data=lambda payload, serial: payload["wallbox"],
            _settings_from_wallbox=lambda wallbox: ("g1T", wallbox["g1T"]),
            _validate_hhmm=self.validate_time,
        )

    async def fake_get(self, *args, **kwargs):
        return copy.deepcopy(self.configuration)

    async def fake_patch(self, *args, **kwargs):
        self.patches.append((args, kwargs))

    @staticmethod
    def validate_time(value):
        if not isinstance(value, str) or re.fullmatch(r"(?:[01]\\d|2[0-3]):[0-5]\\d", value) is None:
            raise ValueError("invalid time")

    def test_existing_enabled_field_allows_guarded_update(self):
        asyncio.run(self.writer(self.api, 0, enabled=True))
        self.assertEqual(len(self.patches), 1)
        self.assertTrue(self.patches[0][0][1]["wallbox"]["g1T"]["timePeriods"][0]["isEnable"])

    def test_missing_field_rejects_write_without_patch(self):
        with self.assertRaises(ValueError):
            asyncio.run(self.writer(self.api, 1, enabled=True))
        self.assertEqual(self.patches, [])

    def test_missing_timing_schema_rejects_write(self):
        del self.configuration["wallbox"]["g1T"]["timePeriods"][0]["endTime"]
        with self.assertRaises(ValueError):
            asyncio.run(self.writer(self.api, 0, start_time="08:07"))
        self.assertEqual(self.patches, [])

    def test_nonexistent_period_rejects_write(self):
        with self.assertRaises(ValueError):
            asyncio.run(self.writer(self.api, 3, enabled=True))
        self.assertEqual(self.patches, [])

    def test_noop_does_not_patch(self):
        asyncio.run(self.writer(self.api, 0, enabled=False))
        self.assertEqual(self.patches, [])


if __name__ == "__main__":
    unittest.main()
