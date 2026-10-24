"""Regression tests for the G2T RS485 observations and portal status mapping.

Execute production helpers, sensors and polling methods without cloud access.
"""
from __future__ import annotations

import ast
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

from test_fast_live_polling import FakeCoordinator, PortalConnectionError, calls

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "alphaess_portal_bridge"
MESSAGE = "Keine Kommunikation zwischen Wallbox und Energiespeichersystem"


class BaseEntity:
    def __init__(self, coordinator, entry, key):
        self.coordinator = coordinator
        self.unique_key = key


def load_production():
    entity = ast.parse((COMPONENT / "entity.py").read_text(encoding="utf-8"))
    helpers = {"wallbox_object", "settings_object", "wallbox_communication_missing"}
    selected = [node for node in entity.body if (
        isinstance(node, ast.FunctionDef) and node.name in helpers
    ) or (
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "STATUS_NAMES" for target in node.targets)
    )]
    sensor = ast.parse((COMPONENT / "sensor.py").read_text(encoding="utf-8"))
    classes = {
        "AlphaESSWallboxStatusSensor", "AlphaESSWallboxPowerSensor",
        "AlphaESSWallboxEnergySensor", "AlphaESSYesNoSensor",
    }
    selected += [node for node in sensor.body if (
        isinstance(node, ast.ClassDef) and node.name in classes
    ) or (isinstance(node, ast.FunctionDef) and node.name == "_first_value")]
    ns = {
        "AlphaESSWallboxEntity": BaseEntity,
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": SimpleNamespace(POWER="power", ENERGY="energy"),
        "SensorStateClass": SimpleNamespace(MEASUREMENT="measurement", TOTAL_INCREASING="total_increasing"),
        "UnitOfPower": SimpleNamespace(WATT="W"),
        "UnitOfEnergy": SimpleNamespace(KILO_WATT_HOUR="kWh"),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])),
                 "production entity/sensor methods", "exec"), ns)
    return ns


NS = load_production()


def attach_configuration(coordinator, generation="g2T"):
    coordinator.data["configuration"] = {"evCharger": [{"sn": "example", generation: {}}]}
    coordinator.api._find_wallbox_data = lambda config, serial: config["evCharger"][0]
    return coordinator


def coordinator_with(status, *, generation="g2T", source="real_status"):
    item = attach_configuration(FakeCoordinator(generation), generation)
    item.data.update(wallbox_status=status, wallbox_status_source=source)
    return item


def status_sensor(coordinator):
    return NS["AlphaESSWallboxStatusSensor"](coordinator, None)


class StatusTests(unittest.TestCase):
    def test_all_portal_states_have_labels(self):
        expected = {
            "Disconnected": "Verbindung getrennt", "Error": "Allgemeiner Fehler",
            "Fault": "Störung", "Upgrading": "Softwareaktualisierung läuft",
            "Charging": "Lädt", "ChargingStopped": "Laden gestoppt",
            "NotInsertedGun": "Nicht angeschlossen", "PendingStart": "Bereit",
            "InsufficientPower": "Unzureichende Leistung",
            "WaitingForChargingPile": "Warten auf Antwort des E-Autos",
        }
        for value, label in expected.items():
            with self.subTest(status=value):
                self.assertEqual(status_sensor(coordinator_with({"status": value})).native_value, label)

    def test_unknown_and_legacy_states_are_preserved(self):
        for value, expected in (("FutureState", "FutureState"), ("CharingStopped", "Laden gestoppt")):
            self.assertEqual(status_sensor(coordinator_with({"status": value})).native_value, expected)

    def test_missing_null_and_empty_status_match_portal_message(self):
        for payload in ({}, {"status": None}, {"status": ""}, {
            "gunIsLock": False, "chargingAmount": 11.6, "lastChargingAmount": 11.6,
        }):
            with self.subTest(payload=payload):
                sensor = status_sensor(coordinator_with(payload))
                self.assertEqual(sensor.native_value, MESSAGE)
                self.assertIn("Cloud hat geantwortet", sensor.extra_state_attributes["Hinweis"])

    def test_g1t_uses_shared_portal_missing_status_rule(self):
        for payload in ({}, {"status": None}, {"status": ""}, {"gunIsLock": False, "chargingAmount": 11.6}):
            with self.subTest(payload=payload):
                self.assertEqual(status_sensor(coordinator_with(payload, generation="g1T")).native_value, MESSAGE)

    def test_power_zero_alone_does_not_mean_communication_failure(self):
        sensor = status_sensor(coordinator_with({"status": "NotInsertedGun", "power": 0.0}))
        self.assertEqual(sensor.native_value, "Nicht angeschlossen")
        self.assertNotIn("Hinweis", sensor.extra_state_attributes)

    def test_system_fallback_does_not_infer_rs485_failure(self):
        for generation, source in (("g2T", "system"), ("g1T", "system"), ("g2T", None)):
            item = coordinator_with({}, generation=generation, source=source)
            self.assertIsNone(status_sensor(item).native_value)

    def test_invalid_payload_is_not_a_confirmed_communication_failure(self):
        for payload in (None, [], "invalid"):
            self.assertIsNone(status_sensor(coordinator_with(payload)).native_value)

    def test_missing_power_stays_unknown_while_counters_remain_reported(self):
        item = coordinator_with({"chargingAmount": 11.6, "lastChargingAmount": 11.6})
        self.assertIsNone(NS["AlphaESSWallboxPowerSensor"](item, None).native_value)
        daily = NS["AlphaESSWallboxEnergySensor"](item, None, "Heute geladen", "chargingAmount", "today_energy")
        self.assertEqual(daily.native_value, 11.6)
        item.data["wallbox_status"] = {}
        self.assertIsNone(daily.native_value)

    def test_faults_do_not_assert_a_connected_vehicle(self):
        for value in ("Disconnected", "Error", "Fault", "Upgrading", "", None):
            item = coordinator_with({"status": value})
            sensor = NS["AlphaESSYesNoSensor"](item, None, "Fahrzeug angeschlossen", "vehicle_connected")
            self.assertIsNone(sensor.native_value)
        for value, expected in (("NotInsertedGun", "Nein"), ("Charging", "Ja")):
            item = coordinator_with({"status": value})
            sensor = NS["AlphaESSYesNoSensor"](item, None, "Fahrzeug angeschlossen", "vehicle_connected")
            self.assertEqual(sensor.native_value, expected)


class DailyEnergyTests(unittest.TestCase):
    def energy(self, item, key="chargingAmount"):
        return NS["AlphaESSWallboxEnergySensor"](item, None, "Energy", key, key).native_value

    def test_midnight_reply_without_energy_shows_zero(self):
        item = coordinator_with({"status": "NotInsertedGun", "gunIsLock": False, "power": 0.0})
        self.assertEqual(self.energy(item), 0.0)
        self.assertIsNone(self.energy(item, "lastChargingAmount"))

    def test_reported_energy_is_preserved_including_zero(self):
        for value in (0, 11.6):
            item = coordinator_with({"status": "NotInsertedGun", "chargingAmount": value})
            self.assertEqual(self.energy(item), float(value))

    def test_communication_failure_does_not_synthesize_zero(self):
        for state in (None, "", "Disconnected", "Error", "Fault", "Upgrading", "FutureState"):
            with self.subTest(state=state):
                self.assertIsNone(self.energy(coordinator_with({"status": state})))
        self.assertIsNone(self.energy(coordinator_with({})))

    def test_fallback_and_unconfirmed_g1t_do_not_synthesize_zero(self):
        for generation, source in (("g2T", "system"), ("g1T", "real_status"), ("g2T", None)):
            self.assertIsNone(self.energy(coordinator_with({"status": "NotInsertedGun"}, generation=generation, source=source)))

    def test_null_and_invalid_energy_do_not_become_zero(self):
        for value in (None, "", "invalid", [], {}):
            self.assertIsNone(self.energy(coordinator_with({"status": "NotInsertedGun", "chargingAmount": value})))
        for payload in (None, [], "invalid"):
            self.assertIsNone(self.energy(coordinator_with(payload)))

    def test_read_failure_does_not_reuse_old_reply_to_synthesize_zero(self):
        for attribute, value in (("_live_refresh_errors", 1), ("_full_consecutive_errors", 1), ("last_update_success", False)):
            item = coordinator_with({"status": "NotInsertedGun"})
            setattr(item, attribute, value)
            self.assertIsNone(self.energy(item))
            setattr(item, attribute, True if attribute == "last_update_success" else 0)
            self.assertEqual(self.energy(item), 0.0)


class PollingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        calls.clear()

    async def test_disconnect_and_reconnect_keep_polling_and_replace_stale_power(self):
        item = attach_configuration(FakeCoordinator())
        counters = {"gunIsLock": False, "chargingAmount": 11.6, "lastChargingAmount": 11.6}
        item.api.statuses = [
            {"status": "Charging", "power": 3200, **counters},
            counters, counters,
            {"status": "NotInsertedGun", "power": 0.0, **counters},
        ]
        sensor = status_sensor(item)
        power = NS["AlphaESSWallboxPowerSensor"](item, None)
        item.start_live_polling()
        await calls[-1].execute()
        self.assertEqual(power.native_value, 3200.0)
        for _ in range(2):
            await calls[-1].execute()
            self.assertEqual(sensor.native_value, MESSAGE)
            self.assertIsNone(power.native_value)
            self.assertTrue(item._live_status_supported)
            self.assertEqual(calls[-1].delay, 5)
            self.assertEqual(item._live_refresh_errors, 0)
        await calls[-1].execute()
        self.assertEqual(sensor.native_value, "Nicht angeschlossen")
        self.assertEqual(power.native_value, 0.0)
        self.assertEqual(item.api.request_count, 4)
        self.assertEqual(item._live_failure_count, 0)

    async def test_successful_empty_g2t_response_does_not_disable_polling(self):
        item = attach_configuration(FakeCoordinator())
        item.api.statuses = [{}, {"status": "PendingStart"}]
        item.start_live_polling()
        await calls[-1].execute()
        self.assertEqual(status_sensor(item).native_value, MESSAGE)
        self.assertTrue(item._live_status_supported)
        await calls[-1].execute()
        self.assertEqual(status_sensor(item).native_value, "Bereit")

    async def test_g1t_statusless_replies_and_reconnection_keep_polling(self):
        item = coordinator_with({"status": "Charging", "power": 3200}, generation="g1T")
        item.api.statuses = [{"gunIsLock": False, "chargingAmount": 11.6}, {}, {"status": "NotInsertedGun", "power": 0.0}]
        for _ in range(2):
            await item._async_live_refresh(None)
            self.assertEqual(status_sensor(item).native_value, MESSAGE)
            self.assertTrue(item._live_status_supported)
            self.assertEqual(calls[-1].delay, 5)
            self.assertIsNone(NS["AlphaESSWallboxPowerSensor"](item, None).native_value)
        await calls[-1].execute()
        self.assertEqual(status_sensor(item).native_value, "Nicht angeschlossen")

    async def test_g1t_unsupported_endpoint_does_not_publish_communication_failure(self):
        for code in (404, 409):
            calls.clear()
            item = coordinator_with({"status": "Charging"}, generation="g1T", source="system")
            item.api.statuses = [PortalConnectionError(code)]
            await item._async_live_refresh(None)
            self.assertFalse(item._live_status_supported)
            self.assertEqual(status_sensor(item).native_value, "Lädt")
            self.assertEqual(item.data["wallbox_status_source"], "system")
            self.assertEqual(calls, [])

    async def test_cloud_failure_does_not_fabricate_a_missing_status_response(self):
        for error in (PortalConnectionError(503), PortalConnectionError(None)):
            item = coordinator_with({"status": "Charging", "power": 3200})
            previous = copy.deepcopy(item.data)
            item.api.statuses = [error]
            await item._async_live_refresh(None)
            self.assertEqual(item.data, previous)
            self.assertEqual(status_sensor(item).native_value, "Lädt")
            self.assertEqual(item._live_failure_count, 1)
            self.assertEqual(calls[-1].delay, 10)

    async def test_invalid_g2t_shape_backs_off_and_recovers(self):
        item = coordinator_with({"status": "Charging"})
        item.api.statuses = [[], {"status": "ChargingStopped"}]
        await item._async_live_refresh(None)
        self.assertEqual(status_sensor(item).native_value, "Lädt")
        self.assertEqual(item._live_failure_count, 1)
        self.assertIsNot(item._live_status_supported, False)
        self.assertEqual(calls[-1].delay, 10)
        await calls[-1].execute()
        self.assertEqual(status_sensor(item).native_value, "Laden gestoppt")

    async def test_fast_communication_failure_wins_over_inflight_full_refresh(self):
        item = coordinator_with({"status": "Charging", "power": 3200})
        older_full_data = copy.deepcopy(item.data)
        item.api.statuses = [{"gunIsLock": False, "chargingAmount": 11.6}]

        async def fetch_full():
            await item._async_live_refresh(None)
            return older_full_data

        item.api.async_get_wallbox_data = fetch_full
        item.data = await item._async_update_data()
        self.assertEqual(status_sensor(item).native_value, MESSAGE)
        self.assertNotIn("power", item.data["wallbox_status"])

    async def test_rs485_failure_does_not_mark_cloud_api_disconnected(self):
        source = ast.parse((COMPONENT / "coordinator.py").read_text(encoding="utf-8"))
        cls = next(node for node in source.body if isinstance(node, ast.ClassDef))
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "api_connection_status")
        method.decorator_list = []
        ns = {"datetime": datetime, "timezone": timezone}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                     "production api_connection_status", "exec"), ns)
        item = attach_configuration(FakeCoordinator())
        item._last_full_success = datetime.now(timezone.utc)
        item._full_consecutive_errors = 0
        item.update_interval = timedelta(seconds=30)
        item.api.statuses = [{"chargingAmount": 11.6}]
        await item._async_live_refresh(None)
        self.assertEqual(ns["api_connection_status"](item), "Verbunden")
        self.assertEqual(status_sensor(item).native_value, MESSAGE)


if __name__ == "__main__":
    unittest.main()
