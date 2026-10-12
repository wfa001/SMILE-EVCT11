"""Privacy regression tests for the exported diagnostic helpers.

Run: python -m unittest discover -s tests
"""
import ast
from pathlib import Path
import unittest
from typing import Any


def load_helpers():
    """Compile the actual dependency-free helper functions from diagnostics.py."""
    source = Path(__file__).resolve().parents[1] / (
        "custom_components/alphaess_portal_bridge/diagnostics.py"
    )
    module = ast.parse(source.read_text(encoding="utf-8"))
    names = {"_present_fields", "_bool_capability", "_period_schema"}
    subset = ast.Module(
        body=[node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in names],
        type_ignores=[],
    )
    namespace = {"Any": Any}
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


if __name__ == "__main__":
    unittest.main()
