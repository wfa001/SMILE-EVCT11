"""Experimental G1T settings compatibility tests (no portal access).

Existing G2T write-lock regressions remain in test_settings_write_lock.py.
"""
from __future__ import annotations

import ast
import copy
import runpy
from pathlib import Path
import unittest

from test_settings_write_lock import FakePortal, PortalConnectionError


class FakeG1Portal(FakePortal):
    def __init__(self):
        super().__init__()
        box = self.configuration["evCharger"][0]
        values = box.pop("g2T")
        # G1T supports exactly two periods. Extra fields are only writable
        # when explicitly returned, so keep them here for compatibility tests.
        values["timePeriods"] = values["timePeriods"][:2]
        box["g1T"] = values

    @property
    def settings(self):
        return self.wallbox["g1T"]


ENTITY = (
    Path(__file__).resolve().parents[1]
    / "custom_components/alphaess_portal_bridge/entity.py"
)


def load_entity_helpers():
    """Extract only the production functions, not HA dependencies."""
    tree = ast.parse(ENTITY.read_text(encoding="utf-8"))
    names = {
        "time_period", "time_period_selected",
        "time_period_status", "scheduled_charging_selected",
    }
    chosen = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert len(chosen) == len(names)

    def settings_object(coordinator):
        box = coordinator.wallbox
        if isinstance(box.get("g2T"), dict):
            return "g2T", box["g2T"]
        if isinstance(box.get("g1T"), dict):
            return "g1T", box["g1T"]
        return None, {}

    namespace = {"settings_object": settings_object, **runpy.run_path(str(ENTITY.parent / "schedule.py"))}
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=chosen, type_ignores=[])),
                str(ENTITY), "exec"),
        namespace,
    )
    return namespace


class G1TCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_integral_g1t_portal_currents_accept_int_and_float(self):
        for current in (6, 14, 16, 6.0, 14.0, 16.0):
            with self.subTest(current=current, value_type=type(current).__name__):
                portal = FakeG1Portal()
                portal.settings["chargeCurrent"] = current
                before = copy.deepcopy(portal.configuration)
                await portal.async_update_wallbox_settings(charge_current=9)
                self.assertEqual(len(portal.patches), 1)
                expected = before
                expected["evCharger"][0]["g1T"]["chargeCurrent"] = 9
                self.assertEqual(portal.configuration, expected)
                self.assertIs(type(portal.settings["chargeCurrent"]), int)

    async def test_invalid_g1t_portal_currents_block_patch(self):
        invalid = (None, True, False, "14", 5, 17, 5.9, 16.1, 14.5,
                   float("nan"), float("inf"), -float("inf"), {}, [])
        for current in invalid:
            with self.subTest(current=current):
                portal = FakeG1Portal()
                portal.settings["chargeCurrent"] = current
                awaitable = portal.async_update_wallbox_settings(charge_current=9)
                with self.assertRaises(ValueError):
                    await awaitable
                self.assertEqual(portal.patches, [])

    async def test_missing_g1t_portal_current_blocks_patch(self):
        portal = FakeG1Portal()
        del portal.settings["chargeCurrent"]
        with self.assertRaises(ValueError):
            await portal.async_update_wallbox_settings(charge_current=9)
        self.assertEqual(portal.patches, [])

    async def test_two_periods_can_be_updated_without_creating_a_third(self):
        portal = FakeG1Portal()
        self.assertEqual(len(portal.settings["timePeriods"]), 2)
        first_period = copy.deepcopy(portal.settings["timePeriods"][0])
        await portal.async_update_time_period(1, start_time="20:17", end_time="22:39")
        self.assertEqual(len(portal.settings["timePeriods"]), 2)
        self.assertEqual(portal.settings["timePeriods"][0], first_period)
        self.assertEqual(portal.settings["timePeriods"][1]["startTime"], "20:17")
        self.assertEqual(portal.settings["timePeriods"][1]["endTime"], "22:39")
        self.assertEqual(len(portal.patches), 1)
        with self.assertRaises(PortalConnectionError):
            await portal.async_update_time_period(2, enabled=True)
        self.assertEqual(len(portal.settings["timePeriods"]), 2)
        self.assertEqual(len(portal.patches), 1)

    async def test_existing_g1t_period_flag_and_mode_can_be_changed(self):
        portal = FakeG1Portal()
        await portal.async_update_time_period(0, enabled=False, charge_mode=4, charge_current=11)
        self.assertFalse(portal.settings["timePeriods"][0]["isEnable"])
        self.assertEqual(portal.settings["timePeriods"][0]["chargeMode"], 4)
        self.assertEqual(portal.settings["timePeriods"][0]["chargeCurrent"], 11)

    async def test_incompatible_period_schema_blocks_any_patch(self):
        portal = FakeG1Portal()
        portal.settings["timePeriods"][0] = {"from": "00:00", "until": "23:59"}
        with self.assertRaises(ValueError):
            await portal.async_update_time_period(0, start_time="11:00")
        self.assertEqual(portal.patches, [])

    async def test_nonexistent_period_field_is_not_invented(self):
        portal = FakeG1Portal()
        portal.settings["timePeriods"][0].pop("chargeCurrent")
        with self.assertRaises(ValueError):
            await portal.async_update_time_period(0, charge_current=11)
        self.assertEqual(portal.patches, [])

    async def test_g1t_four_modes_but_not_unverified_eco_zero(self):
        portal = FakeG1Portal()
        await portal.async_update_wallbox_settings(charge_mode=3)
        self.assertEqual(portal.settings["chargeMode"], 3)
        with self.assertRaises(ValueError):
            await portal.async_update_wallbox_settings(charge_mode=0)
        self.assertEqual(len(portal.patches), 1)

    async def test_unknown_g1t_mode_or_strategy_not_written(self):
        portal = FakeG1Portal()
        del portal.settings["chargeMode"]
        with self.assertRaises(ValueError):
            await portal.async_update_wallbox_settings(charge_mode=1)
        del portal.settings["chargeStrategy"]
        with self.assertRaises(ValueError):
            await portal.async_update_wallbox_settings(charge_strategy=1)
        self.assertEqual(portal.patches, [])

    async def test_g1t_strategy_can_use_existing_matching_field(self):
        portal = FakeG1Portal()
        await portal.async_update_wallbox_settings(charge_strategy=1)
        self.assertEqual(portal.settings["chargeStrategy"], 1)

    async def test_g1t_obc_phase_writes_remain_blocked(self):
        portal = FakeG1Portal()
        with self.assertRaises(ValueError):
            await portal.async_update_wallbox_settings(obc_phase=1)
        self.assertEqual(portal.patches, [])

    async def test_period_schema_read_only_helpers(self):
        helpers = load_entity_helpers()
        portal = FakeG1Portal()
        self.assertEqual(helpers["time_period"](portal, 0)["startTime"], "08:00")
        self.assertEqual(helpers["time_period"](portal, 1)["endTime"], "21:00")
        self.assertEqual(helpers["time_period"](portal, 2), {})
        portal.settings["timePeriods"][0].pop("endTime")
        self.assertEqual(helpers["time_period"](portal, 0), {})
        self.assertEqual(helpers["time_period"](portal, 1), {})

    async def test_unexpected_third_period_blocks_reads_and_writes(self):
        portal = FakeG1Portal()
        portal.settings["timePeriods"].append({
            "isEnable": False, "startTime": "22:00", "endTime": "23:00",
        })
        before = copy.deepcopy(portal.configuration)
        helpers = load_entity_helpers()
        for index in range(3):
            self.assertEqual(helpers["time_period"](portal, index), {})
        with self.assertRaises(ValueError):
            await portal.async_update_time_period(0, enabled=False)
        with self.assertRaises(ValueError):
            await portal.async_update_wallbox_settings(charge_strategy=1)
        self.assertEqual(portal.configuration, before)
        self.assertEqual(portal.patches, [])

    async def test_legacy_mode_not_present_in_selectable_modes(self):
        source = ENTITY.read_text(encoding="utf-8")
        model = ast.parse(source)
        g1_modes = next(
            node for node in model.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "G1_MODES" for target in node.targets)
        )
        modes = ast.literal_eval(g1_modes.value)
        self.assertEqual(set(modes.values()), {1, 2, 3, 4})


if __name__ == "__main__":
    unittest.main()
