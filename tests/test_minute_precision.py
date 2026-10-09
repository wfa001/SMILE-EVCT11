"""Test minute-precision G2T times without hardware or Home Assistant.

The production methods are compiled from the integration source via AST
so validation and UI forwarding cannot silently diverge.
"""
from __future__ import annotations

import ast
import asyncio
from datetime import time
from pathlib import Path
import re
from types import SimpleNamespace
import unittest


COMPONENT = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "alphaess_portal_bridge"
)


def load_method(filename, classname, name):
    file = COMPONENT / filename
    source = ast.parse(file.read_text(encoding="utf-8"))
    cls = next(
        item for item in source.body
        if isinstance(item, ast.ClassDef) and item.name == classname
    )
    method = next(
        item for item in cls.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == name
    )
    # Remove @staticmethod (the bound-method descriptor is not needed here).
    method.decorator_list = []
    program = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    namespace = {
        "re": re,
        "time": time,
        "HomeAssistantError": HomeAssistantError,
        "AuthenticationError": AuthenticationError,
        "PortalConnectionError": PortalConnectionError,
    }
    exec(compile(program, str(file), "exec"), namespace)
    return namespace[name]


class HomeAssistantError(Exception):
    pass


class AuthenticationError(Exception):
    pass


class PortalConnectionError(Exception):
    pass


validate_hhmm = load_method("api.py", "AlphaESSPortalApi", "_validate_hhmm")
async_set_value = load_method("time.py", "AlphaESSTimePeriodTime", "async_set_value")


class StubCoordinator:
    def __init__(self):
        self.api = self
        self.writes = []
        self.refreshes = 0

    async def async_update_time_period(self, index, **kwargs):
        value = kwargs.get("start_time", kwargs.get("end_time"))
        validate_hhmm(value)
        self.writes.append((index, kwargs))

    async def async_request_refresh(self):
        self.refreshes += 1


class MinuteValidationTests(unittest.TestCase):
    def test_accepts_any_valid_minute(self):
        for hhmm in ("00:00", "00:01", "08:07", "13:19", "23:59", "17:30"):
            with self.subTest(value=hhmm):
                self.assertIsNone(validate_hhmm(hhmm))

    def test_rejects_invalid_time_strings(self):
        for value in ("24:00", "12:60", "8:07", "12:00:00", "99:59",
                      "-1:00", "", None, "07:3", "18:99"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_hhmm(value)


class MinuteTimeEntityTests(unittest.IsolatedAsyncioTestCase):
    async def test_forwards_exact_minute_for_start_and_end(self):
        coordinator = StubCoordinator()
        for boundary, moment in (("start", time(8, 7)), ("end", time(21, 59))):
            with self.subTest(boundary=boundary):
                entity = SimpleNamespace(
                    coordinator=coordinator, _boundary=boundary, _index=1
                )
                await async_set_value(entity, moment)
        self.assertEqual(coordinator.writes, [
            (1, {"start_time": "08:07"}),
            (1, {"end_time": "21:59"}),
        ])
        self.assertEqual(coordinator.refreshes, 2)

    async def test_does_not_silently_truncate_seconds(self):
        coordinator = StubCoordinator()
        for moment in (time(9, 0, 1), time(9, 0, 0, 100000)):
            with self.subTest(moment=moment):
                entity = SimpleNamespace(
                    coordinator=coordinator, _boundary="start", _index=0
                )
                with self.assertRaises(HomeAssistantError):
                    await async_set_value(entity, moment)
        self.assertEqual(coordinator.writes, [])
        self.assertEqual(coordinator.refreshes, 0)


if __name__ == "__main__":
    unittest.main()
