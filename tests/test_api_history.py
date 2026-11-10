"""Verify retention, restart, privacy and export of the rolling API archive."""
import asyncio
import json
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "alphaess_portal_bridge"
storage = runpy.run_path(str(ROOT / "api_history.py"))
History = storage["ApiHistory"]


class ApiHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / ".storage").mkdir()
        self.hass = SimpleNamespace(
            config=SimpleNamespace(path=lambda *parts: str(self.root.joinpath(*parts))),
            async_add_executor_job=asyncio.to_thread,
        )
        self.clock = SimpleNamespace(time=lambda: self.now)
        clock_patch = patch.dict(History.record.__globals__, {"time": self.clock})
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.now = 1_800_000_000

    def history(self, enabled=True):
        return History(self.hass, "test-entry", enabled, ("PRIVATE-SERIAL",), "PRIVATE-PASSWORD")

    async def test_complete_operational_data_expires_and_survives_restart(self):
        recorded = self.history()
        recorded.record("api", response={"expired": True})
        await recorded.async_flush()
        self.now += 24 * 60 * 60
        with await recorded.async_export({}, {}) as output, ZipFile(output) as archive:
            self.assertIn(b'"expired":true', archive.read("api-antworten.jsonl"))
        self.now += 1
        items = list(range(45))
        payload = {
            "chargingAmount": 0, "lastChargingAmount": None, "items": items,
            "account": {"accessToken": "PRIVATE-TOKEN", "sn": "PRIVATE-SERIAL"},
            "echo": "PRIVATE-PASSWORD",
        }
        recorded.record("api", response=payload, http_status=200)
        self.now += 5
        recorded.record("api", response=payload, http_status=200)
        recorded.record("api", response={**payload, "chargingAmount": "0", "newField": [True, None]})
        recorded.record("api", response=None, http_status=200)
        recorded.record("api", error="timeout")
        recorded.record("bridge", input="missing", sensor_kwh=35.73)
        recorded.record("control", method="PATCH", http_status=204)
        # Mutating the application payload must not change the captured response.
        items.append(999)
        await recorded.async_close()

        with await self.history().async_export({}, {}) as output, ZipFile(output) as archive:
            self.assertEqual(set(archive.namelist()), {
                "api-verlauf.jsonl", "bridge-verlauf.jsonl", "steuerung.jsonl", "diagnose.json",
                "api-antworten.jsonl",
            })
            raw = archive.read("api-antworten.jsonl")
            for private in (b"PRIVATE-TOKEN", b"PRIVATE-SERIAL", b"PRIVATE-PASSWORD", b"expired"):
                self.assertNotIn(private, raw)
            events = [json.loads(line) for line in archive.read("api-verlauf.jsonl").splitlines()]
            responses = dict((row["id"], row["response"]) for row in map(json.loads, raw.splitlines()))
            self.assertEqual(len(events), 5)
            self.assertEqual(len(responses), 3)
            self.assertNotEqual(events[0]["at"], events[1]["at"])
            self.assertEqual(events[0]["response_id"], events[1]["response_id"])
            self.assertNotEqual(events[0]["response_id"], events[2]["response_id"])
            self.assertEqual(events[0]["http_status"], 200)
            original = responses[events[0]["response_id"]]
            self.assertEqual(original["items"], list(range(45)))
            self.assertEqual(original["chargingAmount"], 0)
            self.assertIsNone(original["lastChargingAmount"])
            self.assertEqual(original["account"]["accessToken"], "[redacted]")
            changed = responses[events[2]["response_id"]]
            self.assertEqual(changed["chargingAmount"], "0")
            self.assertEqual(changed["newField"], [True, None])
            self.assertIsNone(responses[events[3]["response_id"]])
            self.assertNotIn("response_id", events[4])
            summary = json.loads(archive.read("diagnose.json"))
            self.assertEqual(summary["api_history"]["archive_format"], 2)
            self.assertEqual(summary["api_history"]["retention_hours"], 24)
            self.assertEqual(summary["api_history"]["unique_api_responses"], 3)
            self.assertEqual(summary["api_history"]["records"], {"api": 5, "bridge": 2, "control": 1})
            self.assertIsNotNone(summary["api_history"]["from"])
            self.assertIsNotNone(summary["api_history"]["to"])

    async def test_export_masks_sensitive_values_already_saved_in_the_history(self):
        recorded = self.history()
        legacy = {
            "basic": {"checkCode": "PRIVATE-CODE", "linkman": "PRIVATE-CONTACT"},
            "sysSn": "id-0123456789abcdef",
            "newPortalField": {"version": 3},
        }
        await asyncio.to_thread(recorded._write, [
            (self.now, "api", {"response": legacy}),
            (self.now, "control", {"request": {"configuration": legacy}}),
        ], self.now)
        recorded.record("api", response=legacy)
        with await recorded.async_export({}, {}) as output, ZipFile(output) as archive:
            [row] = map(json.loads, archive.read("api-antworten.jsonl").splitlines())
            [control] = map(json.loads, archive.read("steuerung.jsonl").splitlines())
            sanitized = {
                "basic": {"checkCode": "[redacted]", "linkman": "[redacted]"},
                "sysSn": "id-0123456789abcdef",
                "newPortalField": {"version": 3},
            }
            self.assertEqual(row["response"], sanitized)
            self.assertEqual(control["request"]["configuration"], sanitized)

    async def test_disabled_archive_exports_only_the_cached_fallback(self):
        recorder = self.history(enabled=False)
        recorder.record("api", response={"not_recorded": True})
        snapshot = {"status": "Charging", "newField": list(range(45)), "checkCode": "PRIVATE-CODE"}
        with await recorder.async_export({}, snapshot) as output, ZipFile(output) as archive:
            self.assertEqual(archive.read("api-verlauf.jsonl"), b"")
            self.assertEqual(archive.read("api-antworten.jsonl"), b"")
            self.assertEqual(
                json.loads(archive.read("api-momentaufnahme.json")),
                {**snapshot, "checkCode": "[redacted]"},
            )
        self.assertFalse(recorder.path.exists())


class ArchiveDownloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import ast
        from io import BytesIO

        class HttpError(Exception):
            def __init__(self, text=None):
                super().__init__(text)

        class Response:
            def __init__(self, headers):
                self.headers = headers
                self.data = b""

            async def prepare(self, request):
                pass

            async def write(self, chunk):
                self.data += chunk

            async def write_eof(self):
                pass

        async def summary(*args, **kwargs):
            return {}

        module = ast.parse((ROOT / "diagnostics_archive.py").read_text())
        node = next(node for node in module.body if isinstance(node, ast.ClassDef))
        ns = {
            "HomeAssistantView": object,
            "KEY_HASS_USER": "user",
            "DOMAIN": "bridge",
            "DIAGNOSTICS_ARCHIVE_PATH": "/api/bridge/archive",
            "web": SimpleNamespace(
                HTTPForbidden=HttpError, HTTPNotFound=HttpError, StreamResponse=Response
            ),
            "time": SimpleNamespace(monotonic=lambda: self.now),
            "async_get_config_entry_diagnostics": summary,
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<archive view>", "exec"), ns)

        async def export(*args):
            return BytesIO(b"zip")

        self.now = 100
        self.coordinator = SimpleNamespace(
            _advanced_diagnostics_until=200,
            data={},
            api=SimpleNamespace(
                history=SimpleNamespace(async_export=export),
                _find_wallbox_data=lambda *args: {},
            ),
        )
        self.view = ns[node.name](SimpleNamespace(
            data={"bridge": {"entry": self.coordinator}},
            config_entries=SimpleNamespace(async_get_entry=lambda entry_id: object()),
            config=SimpleNamespace(time_zone="Europe/Berlin", as_dict=lambda: {"version": "test"}),
            async_add_executor_job=asyncio.to_thread,
        ))
        self.HttpError = HttpError

    async def test_requires_admin_and_uses_the_grant_once(self):
        with self.assertRaises(self.HttpError):
            await self.view.get({"user": SimpleNamespace(is_admin=False)}, "entry")
        self.assertEqual(self.coordinator._advanced_diagnostics_until, 200)
        admin = {"user": SimpleNamespace(is_admin=True)}
        result = await self.view.get(admin, "entry")
        self.assertEqual(result.headers["Content-Type"], "application/zip")
        self.assertEqual(result.data, b"zip")
        with self.assertRaises(self.HttpError):
            await self.view.get(admin, "entry")
        self.coordinator._advanced_diagnostics_until = 200
        self.now = 201
        with self.assertRaises(self.HttpError):
            await self.view.get(admin, "entry")
