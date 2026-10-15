"""G1T time-period controls must match the observed two-window portal schema."""
import ast
import asyncio
import copy
import re
import runpy
from pathlib import Path
import unittest
from types import SimpleNamespace
from typing import Any


def load_helpers():
    path = Path(__file__).resolve().parents[1] / "custom_components/alphaess_portal_bridge/entity.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    selected = {
        "wallbox_object",
        "settings_object",
        "time_period",
        "scheduled_charging_selected",
        "time_period_selected",
    }
    nodes = [
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in selected
    ]
    guard = runpy.run_path(str(path.parent / "schedule.py"))
    namespace = {
        "Any": Any,
        "AlphaESSWallboxCoordinator": object,
        **guard,
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
            str(path),
            "exec",
        ),
        namespace,
    )
    return namespace


def observed_g1t_settings():
    return {
        "obcPhase": 3,
        "chargeMode": 2,
        "chargeCurrent": 11,
        "timePeriods": [
            {"isEnable": True, "startTime": "02:00", "endTime": "02:45"},
            {"isEnable": False, "startTime": "00:00", "endTime": "00:00"},
        ],
    }


class G1TScheduleSchemaTests(unittest.TestCase):
    def setUp(self):
        self.helpers = load_helpers()

    def coordinator(self, settings):
        wallbox = {"g1T": settings}
        return SimpleNamespace(
            data={"configuration": {"wallbox": wallbox}, "wallbox_serial": "private-serial"},
            api=SimpleNamespace(_find_wallbox_data=lambda config, serial: config["wallbox"]),
        )

    def test_observed_two_period_schema_is_exposed_without_strategy(self):
        settings = observed_g1t_settings()
        item = self.coordinator(settings)
        self.assertTrue(self.helpers["schedule_supported"]("g1T", settings))
        self.assertEqual(self.helpers["time_period"](item, 0), settings["timePeriods"][0])
        self.assertEqual(self.helpers["time_period"](item, 1), settings["timePeriods"][1])
        self.assertEqual(self.helpers["time_period"](item, 2), {})

    def test_missing_global_strategy_is_unknown_not_assumed(self):
        item = self.coordinator(observed_g1t_settings())
        self.assertFalse(self.helpers["scheduled_charging_selected"](item))
        self.assertIsNone(self.helpers["time_period_selected"](item, 0))

    def test_explicit_strategy_can_be_interpreted(self):
        settings = observed_g1t_settings()
        settings["chargeStrategy"] = 1
        item = self.coordinator(settings)
        self.assertTrue(self.helpers["strategy_supported"]("g1T", settings))
        self.assertTrue(self.helpers["scheduled_charging_selected"](item))
        self.assertTrue(self.helpers["time_period_selected"](item, 0))

    def test_incomplete_timing_schema_is_not_exposed(self):
        settings = observed_g1t_settings()
        del settings["timePeriods"][0]["endTime"]
        item = self.coordinator(settings)
        self.assertFalse(self.helpers["schedule_supported"]("g1T", settings))
        self.assertEqual(self.helpers["time_period"](item, 0), {})
        self.assertIsNone(self.helpers["time_period_selected"](item, 0))

    def test_unexpected_third_period_is_not_assumed(self):
        settings = observed_g1t_settings()
        settings["timePeriods"].append(
            {"isEnable": False, "startTime": "03:00", "endTime": "03:30"}
        )
        self.assertFalse(self.helpers["schedule_supported"]("g1T", settings))

    def test_g2t_schedule_support_is_unchanged(self):
        self.assertTrue(self.helpers["schedule_supported"]("g2T", {}))
        self.assertTrue(self.helpers["strategy_supported"]("g2T", {}))


class FakePortalConnectionError(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(kwargs.get("step", "portal error"))


def load_api_writer():
    path = Path(__file__).resolve().parents[1] / "custom_components/alphaess_portal_bridge/api.py"
    module = ast.parse(path.read_text(encoding="utf-8"))
    api_class = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "AlphaESSPortalApi"
    )
    method = next(
        node for node in api_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_update_time_period"
    )
    method.decorator_list = []
    guard = runpy.run_path(str(path.parent / "schedule.py"))
    namespace = {
        "copy": copy,
        "re": re,
        "PortalConnectionError": FakePortalConnectionError,
        **guard,
    }
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(path), "exec"),
        namespace,
    )
    return namespace["async_update_time_period"]


class ScheduleWriterTests(unittest.TestCase):
    def setUp(self):
        self.writer = load_api_writer()
        self.patches = []
        self.configuration = {
            "wallbox": {
                "g1T": {
                    "obcPhase": 3,
                    "chargeMode": 2,
                    "chargeCurrent": 11,
                    "timePeriods": [
                        {"startTime": "02:00", "endTime": "02:45", "isEnable": True},
                        {"startTime": "00:00", "endTime": "00:00", "isEnable": False},
                    ],
                }
            }
        }
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
        if not isinstance(value, str) or re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value) is None:
            raise ValueError("invalid time")

    def test_time_update_preserves_schema_without_inventing_fields(self):
        asyncio.run(self.writer(self.api, 0, end_time="02:30"))
        self.assertEqual(len(self.patches), 1)
        payload = self.patches[0][0][1]
        settings = payload["wallbox"]["g1T"]
        self.assertEqual(settings["timePeriods"][0]["endTime"], "02:30")
        self.assertNotIn("chargeStrategy", settings)
        self.assertNotIn("chargeMode", settings["timePeriods"][0])
        self.assertNotIn("chargeCurrent", settings["timePeriods"][0])

    def test_existing_enabled_field_allows_update(self):
        asyncio.run(self.writer(self.api, 1, enabled=True))
        self.assertEqual(len(self.patches), 1)
        payload = self.patches[0][0][1]
        self.assertTrue(payload["wallbox"]["g1T"]["timePeriods"][1]["isEnable"])

    def test_missing_enable_field_rejects_write_without_patch(self):
        del self.configuration["wallbox"]["g1T"]["timePeriods"][1]["isEnable"]
        with self.assertRaises(ValueError):
            asyncio.run(self.writer(self.api, 1, enabled=True))
        self.assertEqual(self.patches, [])

    def test_missing_timing_field_rejects_write_without_patch(self):
        del self.configuration["wallbox"]["g1T"]["timePeriods"][0]["endTime"]
        with self.assertRaises(ValueError):
            asyncio.run(self.writer(self.api, 0, start_time="02:15"))
        self.assertEqual(self.patches, [])

    def test_third_period_rejects_write(self):
        with self.assertRaises(FakePortalConnectionError):
            asyncio.run(self.writer(self.api, 2, enabled=True))
        self.assertEqual(self.patches, [])

    def test_noop_does_not_patch(self):
        asyncio.run(self.writer(self.api, 0, enabled=True))
        self.assertEqual(self.patches, [])


if __name__ == "__main__":
    unittest.main()
