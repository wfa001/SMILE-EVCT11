"""Regression checks for the documented live energy counter semantics."""
import ast
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "custom_components/alphaess_portal_bridge/sensor.py"
)


class LiveEnergyCounterTests(unittest.TestCase):
    def test_unique_ids_and_sources_remain_stable(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('"Heute geladen", "chargingAmount", "today_energy"', source)
        self.assertIn(
            '"Aktuelle / letzte Ladesitzung", "lastChargingAmount", "last_energy"',
            source,
        )

    def test_missing_values_without_a_valid_live_reply_stay_unknown(self):
        from test_wallbox_communication import NS, coordinator_with
        for payload in ({}, {"status": "Fault"}, {"status": None}):
            coordinator = coordinator_with(payload)
            sensor = NS["AlphaESSWallboxDailyEnergySensor"](coordinator, None)
            self.assertIsNone(sensor.native_value)

    def test_energy_sensor_has_no_value_reconstruction_or_extra_api_calls(self):
        source = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        klass = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "AlphaESSWallboxEnergySensor"
        )
        segment = ast.get_source_segment(source, klass)
        self.assertNotIn("async_get_", segment)
        self.assertNotIn("async_request_refresh", segment)


    def test_actual_live_sensor_values_and_state_class(self):
        from test_wallbox_communication import NS, coordinator_with

        coordinator = coordinator_with(
            {"chargingAmount": 2.5, "lastChargingAmount": 0.7}, generation="g1T"
        )
        daily = NS["AlphaESSWallboxDailyEnergySensor"](coordinator, None)
        segment = NS["AlphaESSWallboxEnergySensor"](
            coordinator, None, "Aktuelle / letzte Ladesitzung", "lastChargingAmount", "last_energy"
        )
        self.assertEqual(daily.native_value, 2.5)
        self.assertEqual(segment.native_value, 0.7)
        self.assertEqual(daily._attr_state_class, "total_increasing")
        self.assertIsNone(getattr(segment, "_attr_state_class", None))
        coordinator.data["wallbox_status"] = {"chargingAmount": 0, "lastChargingAmount": None}
        self.assertEqual(daily.native_value, 0.0)
        self.assertIsNone(segment.native_value)
        coordinator.data["wallbox_status"] = {"chargingAmount": "invalid"}
        self.assertIsNone(daily.native_value)
        coordinator.data["wallbox_status"] = {}
        self.assertIsNone(daily.native_value)

    def test_energy_trace_distinguishes_missing_null_and_zero(self):
        from test_wallbox_communication import NS, coordinator_with

        coordinator = coordinator_with({"status": "Charging", "serial": "SECRET-SERIAL"})
        daily = NS["AlphaESSWallboxDailyEnergySensor"](coordinator, None)
        status = coordinator.data["wallbox_status"]
        with self.assertLogs(NS["_LOGGER"], level="DEBUG") as logs:
            self.assertEqual(daily.native_value, 0.0)
            self.assertEqual(daily.native_value, 0.0)
            status["chargingAmount"] = 0
            self.assertEqual(daily.native_value, 0.0)
            status["chargingAmount"] = None
            self.assertIsNone(daily.native_value)
            status["chargingAmount"] = "SECRET-INVALID"
            self.assertIsNone(daily.native_value)
            status["chargingAmount"] = "1.25"
            coordinator.data["wallbox_status_source"] = "system"
            self.assertEqual(daily.native_value, 1.25)

        self.assertEqual(len(logs.output), 5)
        for line, expected in zip(logs.output, (
            "source=real_status status=Charging api=missing sensor_kWh=0.0",
            "source=real_status status=Charging api=number(0) sensor_kWh=0.0",
            "source=real_status status=Charging api=null sensor_kWh=None",
            "source=real_status status=Charging api=invalid sensor_kWh=None",
            "source=system status=Charging api=numeric string(1.25) sensor_kWh=1.25",
        ), strict=True):
            self.assertIn(expected, line)
            self.assertNotIn("SECRET", line)


class G2TDailyEnergyTests(unittest.IsolatedAsyncioTestCase):
    async def test_midday_zeros_are_ignored_across_reload_but_midnight_can_reset(self):
        from test_wallbox_communication import NS, coordinator_with

        coordinator = coordinator_with(
            {"status": "Charging", "chargingAmount": 31.85}
        )
        sensor_type = NS["AlphaESSWallboxDailyEnergySensor"]
        daily = sensor_type(coordinator, None)
        status = coordinator.data["wallbox_status"]

        with patch.object(NS["dt_util"], "now") as now:
            now.return_value = datetime(2026, 11, 8, 4, tzinfo=timezone.utc)
            self.assertEqual(daily.native_value, 31.85)

            del status["chargingAmount"]
            self.assertEqual(daily.native_value, 31.85)
            status["chargingAmount"] = None
            self.assertIsNone(daily.native_value)

            reloaded = sensor_type(coordinator, None)
            reloaded.previous = daily.extra_restore_state_data
            await reloaded.async_added_to_hass()
            status["chargingAmount"] = "0"
            with self.assertLogs(NS["_LOGGER"], level="DEBUG") as logs:
                self.assertEqual(reloaded.native_value, 31.85)
            self.assertIn("api=numeric string(0.0) sensor_kWh=31.85", logs.output[0])
            status["chargingAmount"] = 35.73
            self.assertEqual(reloaded.native_value, 35.73)

            now.return_value = datetime(2026, 11, 9, 0, tzinfo=timezone.utc)
            self.assertEqual(reloaded.native_value, 35.73)
            del status["chargingAmount"]
            self.assertEqual(reloaded.native_value, 0.0)
            status["chargingAmount"] = 2.25
            self.assertEqual(reloaded.native_value, 2.25)
            status["chargingAmount"] = 0
            self.assertEqual(reloaded.native_value, 2.25)


if __name__ == "__main__":
    unittest.main()
