"""Tests for isolated five-second G1T/G2T live polling, without Home Assistant."""
from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path
import unittest
from typing import Any


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "custom_components" / "alphaess_portal_bridge" / "coordinator.py"
)


class PortalConnectionError(Exception):
    def __init__(self, status=None, step="wallbox status"):
        self.status = status
        self.step = step


class AuthenticationError(Exception):
    def __init__(self, step="wallbox status"):
        self.step = step


class AlphaESSPortalApi:
    @staticmethod
    def wallbox_generation(data):
        return data.get("generation") if data else None


class Logger:
    def warning(self, *args):
        pass


class Scheduled:
    def __init__(self, delay, cb):
        self.delay = delay
        self.cb = cb
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    async def execute(self):
        if not self.cancelled:
            await self.cb(None)


calls = []


def async_call_later(hass, delay, callback):
    call = Scheduled(delay, callback)
    calls.append(call)
    return call.cancel


def load_methods():
    original = next(
        node for node in ast.parse(SOURCE.read_text(encoding="utf-8")).body
        if isinstance(node, ast.ClassDef)
        and node.name == "AlphaESSWallboxCoordinator"
    )
    methods = {"start_live_polling", "_schedule_live_refresh",
               "_async_live_refresh", "stop_live_polling"}
    extracted = [node for node in original.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name in methods]
    assert len(extracted) == len(methods)
    cls = ast.ClassDef(name="FastCoordinator", bases=[], keywords=[],
                       body=extracted, decorator_list=[])
    namespace = {
        "Any": Any,
        "AlphaESSPortalApi": AlphaESSPortalApi,
        "AuthenticationError": AuthenticationError,
        "PortalConnectionError": PortalConnectionError,
        "async_call_later": async_call_later,
        "_G2T_LIVE_INTERVAL_SECONDS": 5,
        "_G2T_LIVE_MAX_BACKOFF_SECONDS": 120,
        "_LOGGER": Logger(),
        "time": time,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])),
                 str(SOURCE), "exec"), namespace)
    return namespace["FastCoordinator"]


Coordinator = load_methods()


class FakeAPI:
    def __init__(self):
        self.statuses = []
        self.request_count = 0
        self._live_status_unavailable_serials = set()

    async def async_get_live_status(self, serial):
        self.request_count += 1
        value = self.statuses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeCoordinator(Coordinator):
    def __init__(self, generation="g2T"):
        self.api = FakeAPI()
        self.hass = object()
        self.data = {"generation": generation, "wallbox_serial": "example",
                     "configuration": {"timePeriods": [1, 2, 3]}}
        self._stopped = False
        self._live_refresh_cancel = None
        self._live_refresh_errors = 0
        self._live_status_supported = None
        self._live_success_count = 0
        self._live_failure_count = 0
        self._full_success_count = 0
        self._full_failure_count = 0
        self._live_last_http_status = None
        self._live_last_duration_ms = None
        self._full_last_duration_ms = None
        self._live_revision = 0
        self._latest_live_status = None
        self.notify_count = 0

    def async_update_listeners(self):
        self.notify_count += 1


class LiveRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        calls.clear()

    async def test_five_second_poll_only_changes_live_values(self):
        item = FakeCoordinator()
        item.api.statuses = [{"status": "Charging", "power": 1400}]
        item.start_live_polling()
        self.assertEqual(calls[-1].delay, 5)
        await calls[-1].execute()
        self.assertEqual(item.data["wallbox_status"]["power"], 1400)
        self.assertEqual(item.data["configuration"]["timePeriods"], [1, 2, 3])
        self.assertEqual(item.notify_count, 1)
        self.assertEqual(calls[-1].delay, 5)

    async def test_g1t_schedules_fast_poll_when_endpoint_works(self):
        item = FakeCoordinator(generation="g1T")
        item.api.statuses = [{"status": "Charging", "power": 800}]
        item.start_live_polling()
        self.assertEqual(calls[-1].delay, 5)
        await calls[-1].execute()
        self.assertEqual(item.data["wallbox_status"]["power"], 800)
        self.assertTrue(item._live_status_supported)

    async def test_g1t_unsupported_endpoint_falls_back_to_regular_poll(self):
        item = FakeCoordinator(generation="g1T")
        item.api.statuses = [PortalConnectionError(404)]
        item.start_live_polling()
        await calls[-1].execute()
        self.assertFalse(item._live_status_supported)
        self.assertEqual(len(calls), 1)
        self.assertEqual(item.notify_count, 0)

    async def test_g1t_empty_payload_disables_fast_poll(self):
        item = FakeCoordinator(generation="g1T")
        item.api.statuses = [{"some_unknown_field": "value"}]
        item.start_live_polling()
        await calls[-1].execute()
        self.assertFalse(item._live_status_supported)
        self.assertEqual(len(calls), 1)

    async def test_429_backs_off(self):
        item = FakeCoordinator()
        item.api.statuses = [PortalConnectionError(429)]
        item.start_live_polling()
        await calls[-1].execute()
        self.assertEqual(calls[-1].delay, 120)
        self.assertEqual(item.notify_count, 0)

    async def test_temporary_failure_recovers(self):
        item = FakeCoordinator()
        item.api.statuses = [PortalConnectionError(503), {"status": "Charging"}]
        item.start_live_polling()
        await calls[-1].execute()
        self.assertEqual(calls[-1].delay, 10)
        await calls[-1].execute()
        self.assertEqual(calls[-1].delay, 5)
        self.assertEqual(item._live_refresh_errors, 0)

    async def test_stopping_cancels_next_refresh(self):
        item = FakeCoordinator()
        item.start_live_polling()
        pending = calls[-1]
        item._stopped = True
        item.stop_live_polling()
        self.assertTrue(pending.cancelled)
        self.assertIsNone(item._live_refresh_cancel)


if __name__ == "__main__":
    unittest.main()
