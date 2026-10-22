"""Regression checks for G2T schedule feedback requested by forum testers.

Run: python -m unittest discover -s tests -v

The helpers and entity attribute methods are extracted from their actual source
files using the standard-library AST. No Home Assistant installation, credentials
or wallbox are required.
"""
from __future__ import annotations

import ast
import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest
import runpy


COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "alphaess_portal_bridge"


def extract_helpers():
    source = ast.parse((COMPONENT / "entity.py").read_text(encoding="utf-8"))
    wanted = {
        "wallbox_object",
        "settings_object",
        "time_period",
        "scheduled_charging_selected",
        "time_period_selected",
        "time_period_status",
    }
    functions = [
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    assert {f.name for f in functions} == wanted
    module = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    guard = runpy.run_path(str(COMPONENT / "schedule.py"))
    namespace = {"Any": Any, "AlphaESSWallboxCoordinator": object, **guard}
    exec(compile(module, str(COMPONENT / "entity.py"), "exec"), namespace)
    return namespace


NS = extract_helpers()


class FakeApi:
    @staticmethod
    def _find_wallbox_data(configuration, serial):
        for box in configuration.get("evCharger", []):
            if box.get("sn") == serial:
                return box
        return {}


def make_coordinator(strategy=1, enabled=True, generation="g2T"):
    settings = {
        "chargeStrategy": strategy,
        "chargeCurrent": 10,
        "timePeriods": [
            {"isEnable": enabled, "startTime": "08:00", "endTime": "17:00", "chargeMode": 1, "chargeCurrent": 6},
            {"isEnable": False, "startTime": "17:00", "endTime": "21:00", "chargeMode": 2, "chargeCurrent": 8},
            {"isEnable": True, "startTime": "00:15", "endTime": "04:45", "chargeMode": 4, "chargeCurrent": 16},
        ],
    }
    if generation == "g1T":
        # A reported global strategy is interpretable only with the confirmed
        # two-period G1T schema, not with a copied three-period G2T document.
        settings["timePeriods"] = settings["timePeriods"][:2]
    data = {
        "wallbox_serial": "TEST",
        "configuration": {"evCharger": [{"sn": "TEST", generation: settings}]},
    }
    return SimpleNamespace(api=FakeApi(), data=data)


def get_attributes(filename, classname, self_object):
    source_file = COMPONENT / filename
    source = ast.parse(source_file.read_text(encoding="utf-8"))
    cls = next(
        node for node in source.body
        if isinstance(node, ast.ClassDef) and node.name == classname
    )
    method = next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "extra_state_attributes"
    )
    method.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    namespace = dict(NS)
    if hasattr(self_object, "coordinator"):
        # Supply the base entity's property using its actual settings helper.
        self_object.settings_generation = NS["settings_object"](self_object.coordinator)[0]
    exec(compile(module, str(source_file), "exec"), namespace)
    return namespace["extra_state_attributes"](self_object)


class TesterFeedbackScheduleTests(unittest.TestCase):
    def test_schedule_selected_for_reported_strategy_on_either_generation(self):
        for strategy, expected in [(0, False), (1, True), (2, False)]:
            with self.subTest(strategy=strategy):
                co = make_coordinator(strategy=strategy)
                self.assertIs(NS["scheduled_charging_selected"](co), expected)
        self.assertTrue(NS["scheduled_charging_selected"](make_coordinator(generation="g1T")))
        missing = make_coordinator(generation="g1T")
        del missing.data["configuration"]["evCharger"][0]["g1T"]["chargeStrategy"]
        self.assertFalse(NS["scheduled_charging_selected"](missing))

    def test_period_requires_schedule_strategy_and_enabled_flag(self):
        self.assertTrue(NS["time_period_selected"](make_coordinator(1, True), 0))
        self.assertFalse(NS["time_period_selected"](make_coordinator(1, False), 0))
        self.assertFalse(NS["time_period_selected"](make_coordinator(2, True), 0))
        self.assertFalse(NS["time_period_selected"](make_coordinator(0, True), 0))
        self.assertFalse(NS["time_period_selected"](make_coordinator(1, True), 1))

    def test_switch_shows_enabled_setting_without_changing_it(self):
        co = make_coordinator(2, True)
        before = copy.deepcopy(co.data)
        self_object = SimpleNamespace(coordinator=co, _index=0)
        attrs = get_attributes("switch.py", "AlphaESSTimePeriodSwitch", self_object)
        self.assertFalse(attrs["Zeitfenster laut Portal-Modus ausgewählt"])
        self.assertIn("Plug and Play", attrs["Hinweis"])
        self.assertIn("nicht ausgewählt", attrs["Zeitfenster-Status"])
        self.assertEqual(co.data, before)

    def test_time_fields_and_modes_retain_saved_values(self):
        for filename, classname in [
            ("time.py", "AlphaESSTimePeriodTime"),
            ("select.py", "AlphaESSTimePeriodModeSelect"),
        ]:
            with self.subTest(filename=filename):
                co = make_coordinator(strategy=1, enabled=True)
                self_object = SimpleNamespace(coordinator=co, _index=0)
                attrs = get_attributes(filename, classname, self_object)
                self.assertTrue(attrs["Zeitfenster laut Portal-Modus ausgewählt"])

    def test_status_distinguishes_deactivated_from_non_selected(self):
        checks = [
            (1, True, "Im Zeitplan aktiviert"),
            (1, False, "Deaktiviert"),
            (2, True, "nicht ausgewählt"),
            (0, True, "nicht ausgewählt"),
        ]
        for strategy, enabled, text in checks:
            with self.subTest(strategy=strategy, enabled=enabled):
                co = make_coordinator(strategy=strategy, enabled=enabled)
                self.assertIn(text, NS["time_period_status"](co, 0))

    def test_missing_enable_flag_does_not_claim_inactive(self):
        co = make_coordinator(strategy=1, enabled=True)
        del co.data["configuration"]["evCharger"][0]["g2T"]["timePeriods"][0]["isEnable"]
        self.assertIn("Unbekannt", NS["time_period_status"](co, 0))
        attrs = get_attributes(
            "switch.py", "AlphaESSTimePeriodSwitch",
            SimpleNamespace(coordinator=co, _index=0),
        )
        self.assertIn("Unbekannt", attrs["Zeitfenster-Status"])

    def test_strategy_select_indicates_when_schedule_is_not_selected(self):
        for strategy, selected in [(1, True), (2, False)]:
            co = make_coordinator(strategy=strategy)
            attrs = get_attributes(
                "select.py", "AlphaESSWallboxStrategySelect",
                SimpleNamespace(coordinator=co),
            )
            self.assertIs(attrs["Zeitgesteuertes Laden ausgewählt"], selected)
            self.assertIn("nicht gelöscht", attrs["Hinweis"])

    def test_current_setpoint_is_not_misrepresented_as_actual(self):
        attrs = get_attributes(
            "number.py", "AlphaESSWallboxChargeCurrentNumber", SimpleNamespace()
        )
        self.assertIn("Soll-Ladestrom", attrs["Hinweis"])
        self.assertIn("Live-Leistung", attrs["Hinweis"])


if __name__ == "__main__":
    unittest.main()
