"""Test the observed site-energy API without contacting AlphaESS."""
from datetime import datetime, timedelta, timezone
from math import isfinite
import re
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from test_authentication_recovery import API_NS, extract
from test_wallbox_communication import NS, coordinator_with


class SiteDailyEnergyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        self.clock = 10
        namespace = dict(API_NS, re=re, isfinite=isfinite, timedelta=timedelta,
                         dt_util=SimpleNamespace(now=lambda: self.now))
        namespace["time"] = SimpleNamespace(monotonic=lambda: self.clock)
        api_type = extract("api.py", "AlphaESSPortalApi", {
            "__init__", "_async_find_energy_site", "_async_get_site_daily_energy",
            "_site_energy_by_day", "async_get_site_energy_diagnostics",
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
        if step == "site energy seven days":
            self.assertEqual(params, {"startDate": "2026-11-07", "endDate": day, "dimension": "day"})
            return {"ts": ["2026-11-07", "2026-11-09", day], "evCharge": {
                "load": [26.29, {"source": "0.0", "parsedValue": 0}, 19.74],
            }}
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

    async def test_week_diagnostics_keep_zero_and_missing_days_distinct(self):
        result = await self.api.async_get_site_energy_diagnostics("WALLBOX")
        self.assertTrue(result["site_match"])
        self.assertEqual(result["result"], "received")
        self.assertEqual(len(result["days"]), 7)
        self.assertEqual([row["kwh"] for row in result["days"]],
                         [26.29, None, 0.0, None, None, None, 19.74])
        self.assertNotIn("test-site", repr(result))
        self.assertIsNone(self.api._site_energy_key)

    async def test_diagnostics_record_site_match_and_kwh_without_identifiers(self):
        self.api.history = Mock()
        self.assertEqual(await self.api._async_get_site_daily_energy("WALLBOX"), ("2026-11-13", 19.74))
        records = [entry.kwargs for entry in self.api.history.record.call_args_list]
        self.assertIn({
            "event": "energy_site_devices", "candidate": 2,
            "inverter_and_wallbox_match": True, "wallbox_count": 1, "eligible": True,
        }, records)
        self.assertEqual(records[-1], {
            "event": "site_daily_energy", "day": "2026-11-13",
            "result": "accepted", "kwh": 19.74,
        })
        for identifier in ("test-site", "INVERTER", "WALLBOX"):
            self.assertNotIn(identifier, repr(records))

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
