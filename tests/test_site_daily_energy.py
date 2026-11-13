"""Test the observed site-energy API without contacting AlphaESS."""
from datetime import datetime, timezone
from math import isfinite
import re
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from test_authentication_recovery import API_NS, extract
from test_wallbox_communication import NS, coordinator_with


class SiteDailyEnergyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        self.clock = 10
        namespace = dict(API_NS, re=re, isfinite=isfinite, dt_util=SimpleNamespace(now=lambda: self.now))
        namespace["time"] = SimpleNamespace(monotonic=lambda: self.clock)
        api_type = extract("api.py", "AlphaESSPortalApi", {
            "__init__", "_async_find_energy_site", "_async_get_site_daily_energy",
        }, namespace)
        self.api = api_type(SimpleNamespace(session=None), {
            "username": "test", "password": "test", "system_serial": "INVERTER",
        })
        self.devices = {
            "ess": [{"sysSn": "INVERTER", "evChargers": [{"sysSn": "WALLBOX"}]}],
            "others": [{"type": "EvCharger", "sysSn": "WALLBOX"}],
        }
        self.read = self.api._async_get = AsyncMock(side_effect=self.reply)

    async def reply(self, path, *, params=None, step, supplemental):
        self.assertTrue(supplemental)
        if path.endswith("/sites"):
            self.assertEqual(params, {"snTypes": "residential,commercial"})
            return [{"id": "another-site"}, {"id": "test-site"}]
        if path.endswith("another-site/devices"):
            return {"ess": [{"sysSn": "OTHER"}]}
        if path.endswith("/devices"):
            return self.devices
        day = self.now.date().isoformat()
        self.assertEqual(path, "/internal/v1/sites/test-site/energy")
        self.assertEqual(params, {"startDate": day, "endDate": day, "dimension": "day"})
        return {"ts": [day], "evCharge": {"load": [19.74 if day.endswith("13") else 0]}}

    async def test_matches_inverter_and_wallbox_and_reloads_on_day_change(self):
        self.assertEqual(await self.api._async_get_site_daily_energy("WALLBOX"), ("2026-11-13", 19.74))
        self.assertEqual(self.read.await_count, 4)
        self.assertEqual(await self.api._async_get_site_daily_energy("WALLBOX"), ("2026-11-13", 19.74))
        self.assertEqual(self.read.await_count, 4)
        self.now = self.now.replace(day=14)
        self.assertEqual(await self.api._async_get_site_daily_energy("WALLBOX"), ("2026-11-14", 0.0))
        self.assertEqual(self.read.await_count, 5)

    async def test_rejects_site_totals_with_more_than_one_wallbox(self):
        self.devices["others"].append({"type": "EvCharger", "sysSn": "SECOND"})
        self.assertIsNone(await self.api._async_get_site_daily_energy("WALLBOX"))
        self.assertEqual(self.read.await_count, 3)

    def test_g1t_daily_sensor_uses_today_only_and_prefers_live_data(self):
        day = NS["dt_util"].now().date().isoformat()
        coordinator = coordinator_with({"status": "Charging"}, generation="g1T")
        sensor = NS["AlphaESSWallboxDailyEnergySensor"](coordinator, None)
        self.assertIsNone(sensor.native_value)
        coordinator.data["site_daily_energy"] = ("2000-01-01", 10)
        self.assertIsNone(sensor.native_value)
        coordinator.data["site_daily_energy"] = (day, 19.74)
        self.assertEqual(sensor.native_value, 19.74)
        self.assertIn("evCharge.load", sensor.extra_state_attributes["Quelle"])
        coordinator.data["wallbox_status"]["chargingAmount"] = 0
        self.assertEqual(sensor.native_value, 0)
