"""Tests for the coordinator's debounced post-PATCH configuration read-back.

The real coordinator methods are loaded from the source AST, allowing these
tests to run without an installed Home Assistant instance.
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
import typing
import unittest


COORDINATOR_FILE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "alphaess_portal_bridge"
    / "coordinator.py"
)


class FakeScheduledCall:
    def __init__(self, callback):
        self.callback = callback
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    async def run(self):
        if not self.cancelled:
            await self.callback(None)


scheduled_calls = []


def fake_async_call_later(hass, seconds, callback):
    assert seconds == 3
    call = FakeScheduledCall(callback)
    scheduled_calls.append(call)
    return call.cancel


def load_coordinator_methods():
    module = ast.parse(COORDINATOR_FILE.read_text(encoding="utf-8"))
    original = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef)
        and node.name == "AlphaESSWallboxCoordinator"
    )
    names = {
        "_schedule_followup_refresh",
        "_async_followup_refresh",
        "stop_followup_refresh",
    }
    methods = [
        node for node in original.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    assert len(methods) == len(names)
    extracted = ast.ClassDef(
        name="ExtractedCoordinator",
        bases=[],
        keywords=[],
        body=methods,
        decorator_list=[],
    )
    script = ast.fix_missing_locations(
        ast.Module(body=[extracted], type_ignores=[])
    )
    namespace = {
        "Any": typing.Any,
        "async_call_later": fake_async_call_later,
        "_POST_WRITE_READBACK_SECONDS": 3,
    }
    exec(compile(script, str(COORDINATOR_FILE), "exec"), namespace)
    return namespace["ExtractedCoordinator"]


Methods = load_coordinator_methods()


class FakeApi:
    def __init__(self):
        self.callback = "registered"

    def set_settings_written_callback(self, callback):
        self.callback = callback


class FakeCoordinator(Methods):
    def __init__(self):
        self.hass = object()
        self.api = FakeApi()
        self._cancel_followup_refresh = None
        self._stopped = False
        self.refresh_count = 0

    async def async_request_refresh(self):
        self.refresh_count += 1


class FollowupReadbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        scheduled_calls.clear()

    async def test_rapid_writes_schedule_only_one_readback(self):
        coordinator = FakeCoordinator()
        coordinator._schedule_followup_refresh()
        coordinator._schedule_followup_refresh()
        coordinator._schedule_followup_refresh()
        self.assertEqual(len(scheduled_calls), 3)
        self.assertTrue(scheduled_calls[0].cancelled)
        self.assertTrue(scheduled_calls[1].cancelled)
        self.assertFalse(scheduled_calls[2].cancelled)
        for call in scheduled_calls:
            await call.run()
        self.assertEqual(coordinator.refresh_count, 1)
        self.assertIsNone(coordinator._cancel_followup_refresh)

    async def test_unload_cancels_pending_network_refresh(self):
        coordinator = FakeCoordinator()
        coordinator._schedule_followup_refresh()
        coordinator.stop_followup_refresh()
        self.assertTrue(scheduled_calls[-1].cancelled)
        self.assertIsNone(coordinator.api.callback)
        await scheduled_calls[-1].run()
        self.assertEqual(coordinator.refresh_count, 0)

    async def test_unloaded_coordinator_ignores_new_notifications(self):
        coordinator = FakeCoordinator()
        coordinator.stop_followup_refresh()
        coordinator._schedule_followup_refresh()
        self.assertEqual(scheduled_calls, [])


if __name__ == "__main__":
    unittest.main()
