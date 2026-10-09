"""Regression tests for AlphaESS wallbox settings write transactions.

Run without Home Assistant:
    python -m unittest discover -s tests -v

Only production methods are extracted from api.py via ast. No portal credentials,
network requests or hardware access are used in these tests.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import functools
from pathlib import Path
import re
import typing
import unittest


API_FILE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "alphaess_portal_bridge"
    / "api.py"
)


class PortalConnectionError(Exception):
    def __init__(self, status=None, step="connection"):
        self.status = status
        self.step = step
        super().__init__(step)


def load_production_methods():
    """Compile the actual decorator and update methods without HA imports."""
    source = ast.parse(API_FILE.read_text(encoding="utf-8"))
    decorator = next(
        node for node in source.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_serialize_settings_write"
    )
    original_class = next(
        node for node in source.body
        if isinstance(node, ast.ClassDef) and node.name == "AlphaESSPortalApi"
    )
    selected = {
        "async_update_wallbox_settings",
        "async_update_time_period",
        "_settings_from_wallbox",
        "_find_wallbox_data",
        "_validate_hhmm",
    }
    methods = [
        node for node in original_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in selected
    ]
    assert len(methods) == len(selected), "An API method was renamed/removed"
    extracted_class = ast.ClassDef(
        name="ExtractedPortalMethods",
        bases=[],
        keywords=[],
        body=methods,
        decorator_list=[],
    )
    module = ast.fix_missing_locations(
        ast.Module(body=[decorator, extracted_class], type_ignores=[])
    )
    namespace = {
        "wraps": functools.wraps,
        "copy": copy,
        "re": re,
        "Any": typing.Any,
        "PortalConnectionError": PortalConnectionError,
    }
    exec(compile(module, str(API_FILE), "exec"), namespace)
    cls = namespace["ExtractedPortalMethods"]
    # The recursive static helper uses the production class name explicitly.
    namespace["AlphaESSPortalApi"] = cls
    return cls


ProductionMethods = load_production_methods()


def sample_configuration():
    return {
        "evCharger": [{
            "sn": "ALP_TEST",
            "model": "SMILE-G3-EVCT11/S",
            "houseHoldCurrent": 25,
            "allowInstallersControl": False,
            "g2T": {
                "chargeMode": 4,
                "chargeCurrent": 6,
                "chargeStrategy": 0,
                "obcPhase": 1,
                "smartMode": False,
                "gunLineSelfLockEnable": False,
                "isSupportGunLineSelfLock": True,
                "timePeriods": [
                    {"isEnable": True, "startTime": "08:00", "endTime": "17:00",
                     "chargeMode": 1, "chargeCurrent": 6},
                    {"isEnable": True, "startTime": "17:00", "endTime": "21:00",
                     "chargeMode": 1, "chargeCurrent": 6},
                    {"isEnable": True, "startTime": "00:15", "endTime": "04:45",
                     "chargeMode": 4, "chargeCurrent": 16},
                ],
            },
        }]
    }


class FakePortal(ProductionMethods):
    def __init__(self):
        self._settings_write_lock = asyncio.Lock()
        self._charge_current_request_id = 0
        self._wallbox_serial = "ALP_TEST"
        self._system_serial = "ALA_TEST"
        self.configuration = sample_configuration()
        self.patches = []
        self.active_patches = 0
        self.max_active_patches = 0
        self.fail_next_patch = False
        self.patch_started = None
        self.release_patch = None

    async def _async_get(self, path, *, step):
        return copy.deepcopy(self.configuration)

    async def _async_authenticated_patch(self, path, payload, *, step):
        self.active_patches += 1
        self.max_active_patches = max(self.max_active_patches, self.active_patches)
        try:
            if self.patch_started is not None:
                self.patch_started.set()
            if self.release_patch is not None:
                await self.release_patch.wait()
            if self.fail_next_patch:
                self.fail_next_patch = False
                raise PortalConnectionError(503, step)
            self.configuration = copy.deepcopy(payload)
            self.patches.append((step, copy.deepcopy(payload)))
            await asyncio.sleep(0)
        finally:
            self.active_patches -= 1

    @property
    def wallbox(self):
        return self.configuration["evCharger"][0]

    @property
    def settings(self):
        return self.wallbox["g2T"]


class SettingsWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_different_fields_are_serialized_and_preserved(self):
        portal = FakePortal()
        original_periods = copy.deepcopy(portal.settings["timePeriods"])
        await asyncio.gather(
            portal.async_update_wallbox_settings(charge_current=10),
            portal.async_update_wallbox_settings(household_current=32),
            portal.async_update_time_period(0, start_time="09:00"),
        )
        self.assertEqual(portal.max_active_patches, 1)
        self.assertEqual(len(portal.patches), 3)
        self.assertEqual(portal.settings["chargeCurrent"], 10)
        self.assertEqual(portal.wallbox["houseHoldCurrent"], 32)
        self.assertEqual(portal.settings["timePeriods"][0]["startTime"], "09:00")
        self.assertEqual(
            portal.settings["timePeriods"][1:], original_periods[1:]
        )
        self.assertFalse(portal.settings["smartMode"])
        self.assertEqual(portal.settings["chargeStrategy"], 0)

    async def test_queued_current_changes_use_latest_value(self):
        portal = FakePortal()
        async with portal._settings_write_lock:
            first = asyncio.create_task(
                portal.async_update_wallbox_settings(charge_current=8)
            )
            await asyncio.sleep(0)
            second = asyncio.create_task(
                portal.async_update_wallbox_settings(charge_current=9)
            )
            await asyncio.sleep(0)
            last = asyncio.create_task(
                portal.async_update_wallbox_settings(charge_current=10)
            )
            await asyncio.sleep(0)
        await asyncio.gather(first, second, last)
        self.assertEqual(portal.settings["chargeCurrent"], 10)
        self.assertEqual(len(portal.patches), 1)

    async def test_other_settings_are_not_coalesced(self):
        portal = FakePortal()
        async with portal._settings_write_lock:
            first = asyncio.create_task(
                portal.async_update_wallbox_settings(charge_current=8)
            )
            await asyncio.sleep(0)
            other = asyncio.create_task(
                portal.async_update_wallbox_settings(household_current=40)
            )
            await asyncio.sleep(0)
            last = asyncio.create_task(
                portal.async_update_wallbox_settings(charge_current=10)
            )
            await asyncio.sleep(0)
        await asyncio.gather(first, other, last)
        self.assertEqual(portal.wallbox["houseHoldCurrent"], 40)
        self.assertEqual(portal.settings["chargeCurrent"], 10)
        self.assertEqual(len(portal.patches), 2)

    async def test_inflight_patch_is_not_cancelled(self):
        portal = FakePortal()
        portal.patch_started = asyncio.Event()
        portal.release_patch = asyncio.Event()
        first = asyncio.create_task(
            portal.async_update_wallbox_settings(charge_current=10)
        )
        await portal.patch_started.wait()
        second = asyncio.create_task(
            portal.async_update_wallbox_settings(charge_current=6)
        )
        await asyncio.sleep(0)
        portal.release_patch.set()
        await asyncio.gather(first, second)
        self.assertEqual(len(portal.patches), 2)
        self.assertEqual(portal.settings["chargeCurrent"], 6)

    async def test_identical_values_do_not_send_another_patch(self):
        portal = FakePortal()
        await portal.async_update_wallbox_settings(charge_current=6)
        await portal.async_update_time_period(0, start_time="08:00")
        self.assertEqual(portal.patches, [])

    async def test_failed_patch_releases_lock_without_fake_success(self):
        portal = FakePortal()
        portal.fail_next_patch = True
        with self.assertRaises(PortalConnectionError):
            await portal.async_update_wallbox_settings(charge_current=10)
        self.assertEqual(portal.settings["chargeCurrent"], 6)
        await portal.async_update_wallbox_settings(charge_current=9)
        self.assertEqual(portal.settings["chargeCurrent"], 9)
        self.assertFalse(portal._settings_write_lock.locked())

    async def test_invalid_current_does_not_discard_valid_request(self):
        portal = FakePortal()
        async with portal._settings_write_lock:
            valid = asyncio.create_task(
                portal.async_update_wallbox_settings(charge_current=10)
            )
            await asyncio.sleep(0)
            invalid = asyncio.create_task(
                portal.async_update_wallbox_settings(charge_current=17)
            )
            await asyncio.sleep(0)
        results = await asyncio.gather(valid, invalid, return_exceptions=True)
        self.assertIsNone(results[0])
        self.assertIsInstance(results[1], ValueError)
        self.assertEqual(portal.settings["chargeCurrent"], 10)

    async def test_configuration_missing_current_is_patched_not_skipped(self):
        portal = FakePortal()
        del portal.settings["chargeCurrent"]
        await portal.async_update_wallbox_settings(charge_current=6)
        self.assertEqual(len(portal.patches), 1)
        self.assertEqual(portal.settings["chargeCurrent"], 6)


if __name__ == "__main__":
    unittest.main()
