"""Regression tests for the settings write serialization helper.

Run: python -m unittest discover -s tests -v

The decorator is extracted from the integration module's AST so these tests
can run without a full Home Assistant installation or portal credentials.
"""
from __future__ import annotations

import ast
import asyncio
import functools
from pathlib import Path
import unittest


API_FILE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "alphaess_portal_bridge"
    / "api.py"
)


def load_decorator():
    source = ast.parse(API_FILE.read_text(encoding="utf-8"))
    function = next(
        node
        for node in source.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_serialize_settings_write"
    )
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = {"wraps": functools.wraps}
    exec(compile(module, str(API_FILE), "exec"), namespace)
    return namespace["_serialize_settings_write"]


serialize = load_decorator()


class FakePortal:
    def __init__(self):
        self._settings_write_lock = asyncio.Lock()
        self.active = 0
        self.max_active = 0
        self.events = []

    @serialize
    async def update_settings(self, name, *, fail=False):
        self.active += 1
        self.max_active = max(self.active, self.max_active)
        self.events.append(("start", name))
        try:
            await asyncio.sleep(0.01)
            if fail:
                raise ValueError("invalid settings")
            self.events.append(("finish", name))
        finally:
            self.active -= 1


class SettingsWriteLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_updates_are_serialized(self):
        portal = FakePortal()
        await asyncio.gather(
            portal.update_settings("charge_current"),
            portal.update_settings("time_period"),
            portal.update_settings("smart_mode"),
        )
        self.assertEqual(portal.max_active, 1)
        self.assertEqual(
            portal.events,
            [
                ("start", "charge_current"),
                ("finish", "charge_current"),
                ("start", "time_period"),
                ("finish", "time_period"),
                ("start", "smart_mode"),
                ("finish", "smart_mode"),
            ],
        )

    async def test_exception_releases_lock(self):
        portal = FakePortal()
        with self.assertRaises(ValueError):
            await portal.update_settings("invalid", fail=True)
        await portal.update_settings("valid")
        self.assertEqual(portal.max_active, 1)
        self.assertFalse(portal._settings_write_lock.locked())

    async def test_instances_have_independent_locks(self):
        first, second = FakePortal(), FakePortal()
        await asyncio.gather(
            first.update_settings("a"),
            second.update_settings("b"),
        )
        self.assertEqual(first.max_active, 1)
        self.assertEqual(second.max_active, 1)


if __name__ == "__main__":
    unittest.main()
