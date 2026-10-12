"""Privacy regression tests for the exported diagnostic helpers.

Run: python -m unittest discover -s tests
"""
import ast
import asyncio
import json
from types import SimpleNamespace
from pathlib import Path
import unittest
from typing import Any


def load_helpers():
    """Compile the actual dependency-free helper functions from diagnostics.py."""
    source = Path(__file__).resolve().parents[1] / (
        "custom_components/alphaess_portal_bridge/diagnostics.py"
    )
    module = ast.parse(source.read_text(encoding="utf-8"))
    names = {"_present_fields", "_bool_capability", "_period_schema", "async_get_config_entry_diagnostics"}
    subset = ast.Module(
        body=[node for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names],
        type_ignores=[],
    )
    class FakePortal:
        @staticmethod
        def _settings_from_wallbox(wallbox):
            for profile in ("g1T", "g2T"):
                if isinstance(wallbox.get(profile), dict):
                    return profile, wallbox[profile]
            return None, None

    namespace = {"Any": Any, "AlphaESSPortalApi": FakePortal, "DOMAIN": "alphaess_portal_bridge"}
    exec(compile(ast.fix_missing_locations(subset), str(source), "exec"), namespace)
    return namespace


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.functions = load_helpers()

    def test_only_explicitly_permitted_schema_names(self):
        f = self.functions["_present_fields"]
        raw = {
            "chargeMode": 2,
            "password": "TOP-SECRET",
            "token": "TOP-SECRET",
            "serial": "ALP123456789",
            "email": "someone@example.com",
            "chargingAmount": 4.2,
        }
        result = f(raw, ("chargeMode", "chargingAmount"))
        self.assertEqual(result, ["chargeMode", "chargingAmount"])
        self.assertNotIn("TOP-SECRET", str(result))
        self.assertNotIn("ALP123456789", str(result))

    def test_bool_reports_capability_not_current_value(self):
        f = self.functions["_bool_capability"]
        self.assertEqual(f({"supported": True}, "supported"), "supported")
        self.assertEqual(f({"supported": False}, "supported"), "not_supported")
        self.assertEqual(f({"supported": "private"}, "supported"), "unexpected_type")

    def test_periods_never_export_times_or_identifiers(self):
        f = self.functions["_period_schema"]
        raw = {
            "timePeriods": [
                {"startTime": "08:07", "endTime": "09:23", "chargeMode": 2,
                 "serial": "ALP123456789", "token": "TOP-SECRET"}
            ]
        }
        result = f(raw)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["fields"], ["chargeMode", "endTime", "startTime"])
        self.assertNotIn("08:07", str(result))
        self.assertNotIn("TOP-SECRET", str(result))
        self.assertNotIn("ALP123456789", str(result))

    def test_complete_diagnostics_never_exposes_private_values(self):
        secret = "PRIVATE-VERY-SENSITIVE-TOKEN"
        serial = "ALP123456789"
        email = "private@example.com"

        class FakeAPI:
            @staticmethod
            def _find_wallbox_data(document, key):
                return document["wallbox"]

        data = {
            "wallbox_serial": serial,
            "configuration": {
                "password": secret,
                "wallbox": {
                    "serial": serial,
                    "email": email,
                    "accessToken": secret,
                    "g2T": {
                        "chargeMode": 2,
                        "chargeCurrent": 16,
                        "smartMode": True,
                        "timePeriods": [{
                            "startTime": "08:07",
                            "endTime": "09:23",
                            "token": secret,
                        }],
                    },
                    "softwareVersion": "private-firmware-serial",
                },
            },
            "wallbox_status": {
                "status": "Charging",
                "chargingAmount": 5.25,
                "email": email,
                "token": secret,
            },
            "wallbox_status_source": "real_status",
            "latest_report": {
                "beginDate": "2026-10-12T08:07:00",
                "chargingCapacity": 4.5,
                "token": secret,
            },
            "today_report_energy": 4.5,
        }
        coordinator = SimpleNamespace(
            data=data,
            api=FakeAPI(),
            update_interval=SimpleNamespace(total_seconds=lambda: 30),
            _live_refresh_cancel=None,
            _live_status_supported=True,
            _live_refresh_errors=0,
            _live_success_count=20,
            _live_failure_count=1,
            _full_success_count=10,
            _full_failure_count=0,
            _live_last_duration_ms=300,
            _full_last_duration_ms=500,
            _live_last_http_status=429,
            last_update_success=True,
        )
        entry = SimpleNamespace(entry_id="fake-entry-id")
        hass = SimpleNamespace(data={"alphaess_portal_bridge": {"fake-entry-id": coordinator}})
        diag = asyncio.run(self.functions["async_get_config_entry_diagnostics"](hass, entry))
        serialized = json.dumps(diag, sort_keys=True)
        for forbidden in (secret, serial, email, "08:07", "09:23", "5.25", "4.5", "private-firmware-serial"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(diag["portal_profile"], "g2T")
        self.assertEqual(diag["integration"]["live_last_http_status"], 429)
        self.assertEqual(diag["wallbox_schema"]["time_periods"]["count"], 1)
        self.assertIn("chargingAmount", diag["live_data"]["available_fields"])


if __name__ == "__main__":
    unittest.main()
