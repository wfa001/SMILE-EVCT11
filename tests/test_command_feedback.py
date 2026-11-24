"""Commands must be observable without accepting cached or obsolete replies."""
from __future__ import annotations

import asyncio
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from test_authentication_recovery import make_api

ROOT = Path(__file__).resolve().parents[1] / "custom_components/alphaess_portal_bridge"
module = runpy.run_path(str(ROOT / "command_feedback.py"))
Feedback = module["ChargeCommandFeedback"]


class CommandFeedbackTests(unittest.IsolatedAsyncioTestCase):
    def feedback(self, command="START"):
        feedback = Feedback()
        self.addCleanup(feedback.close)
        feedback.begin(command)
        feedback.accepted()
        return feedback

    async def test_only_read_started_after_acceptance_confirms(self):
        feedback = Feedback()
        self.addCleanup(feedback.close)
        listener = Mock()
        feedback.set_listener(listener)
        feedback.begin("START")
        old_revision = feedback.revision
        feedback.accepted()
        feedback.observe({"status": "Charging", "power": 4000}, old_revision)
        self.assertEqual(feedback.state, "Vom Portal angenommen")
        # A fresh HTTP response may still contain a stale device timestamp.
        feedback.observe({"status": "Charging", "statusTs": "2020-01-01T00:00:00Z"},
                         feedback.revision)
        self.assertEqual(feedback.state, "Vom Portal angenommen")
        stamp = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        feedback.observe({"status": "Charging", "statusTs": stamp, "power": 4000},
                         feedback.revision)
        self.assertEqual(feedback.state, "Ausführung bestätigt")
        self.assertIsNotNone(feedback.confirmed_at)
        self.assertEqual(feedback.attributes()["Gemeldete Ladeleistung (W)"], 4000)
        self.assertEqual(listener.call_count, 3)

    async def test_zero_power_and_waiting_do_not_confirm_stop(self):
        feedback = self.feedback("STOP")
        for status in ("Charging", "PendingStart", "WaitingForChargingPile",
                       "InsufficientPower", "Disconnected", "Fault"):
            feedback.observe({"status": status, "power": 0}, feedback.revision)
            self.assertEqual(feedback.state, "Vom Portal angenommen")
        feedback.observe({"status": "ChargingStopped", "power": 3000}, feedback.revision)
        self.assertEqual(feedback.state, "Vom Portal angenommen")
        feedback.observe({"status": "CharingStopped", "power": 0}, feedback.revision)
        self.assertEqual(feedback.state, "Ausführung bestätigt")

    async def test_new_request_cannot_inherit_old_confirmation(self):
        feedback = self.feedback()
        old_revision, old_id = feedback.revision, feedback.request_id
        feedback.begin("STOP")
        self.assertNotEqual(feedback.request_id, old_id)
        self.assertIsNone(feedback.accepted_at)
        feedback.accepted()
        feedback.observe({"status": "ChargingStopped"}, old_revision)
        self.assertEqual(feedback.state, "Vom Portal angenommen")

    async def test_deadline_updates_listeners_even_without_api_replies(self):
        feedback = Feedback()
        self.addCleanup(feedback.close)
        listener = Mock()
        feedback.set_listener(listener)
        feedback.begin("START")
        with patch.dict(Feedback.accepted.__globals__, {"CONFIRMATION_SECONDS": 0}):
            feedback.accepted()
            await asyncio.sleep(0.01)
        self.assertEqual(feedback.state, "Nicht bestätigt")
        self.assertIn("abgelaufen", feedback.error)
        self.assertEqual(listener.call_count, 3)
        feedback.observe({"status": "Charging"}, feedback.revision)
        self.assertEqual(feedback.state, "Nicht bestätigt")

    async def test_unload_cancels_timer(self):
        feedback = self.feedback()
        timer = feedback._timer
        feedback.close()
        self.assertTrue(timer.cancelled())
        self.assertIsNone(feedback._listener)

    async def test_unload_during_request_does_not_start_new_timer(self):
        feedback = Feedback()
        feedback.begin("START")
        feedback.close()
        feedback.accepted()
        self.assertIsNone(feedback._timer)

    def prepared_api(self):
        api, session = make_api([])
        self.addCleanup(api.command_feedback.close)
        api._wallbox_serial = "wallbox"
        api._find_wallbox_data = Mock(return_value={})
        api._settings_from_wallbox = Mock(return_value=("g2T", {"chargeStrategy": 0}))
        api._async_get = AsyncMock(side_effect=[{}, {"status": "PendingStart"}])
        api._async_authenticated_post = AsyncMock()
        return api

    async def test_success_publishes_acceptance_and_invalidates_cache(self):
        api = self.prepared_api()
        listener = Mock()
        api.command_feedback.set_listener(listener)
        api._live_status_cache = {"status": "ChargingStopped"}
        await api.async_control_wallbox("START")
        self.assertEqual(api.command_feedback.state, "Vom Portal angenommen")
        self.assertIsNone(api._live_status_cache)
        self.assertEqual(api.command_feedback.command, "START")
        self.assertEqual(listener.call_count, 2)

    async def test_guard_failure_is_available_as_feedback(self):
        api = self.prepared_api()
        api._settings_from_wallbox.return_value = ("g2T", {"chargeStrategy": 1})
        with self.assertRaises(ValueError):
            await api.async_control_wallbox("START")
        self.assertEqual(api.command_feedback.state, "Abgelehnt")
        api._async_authenticated_post.assert_not_awaited()

    async def test_inflight_read_cannot_confirm_a_later_command(self):
        api = self.prepared_api()
        del api._async_get
        api._async_token = AsyncMock()
        entered, release = asyncio.Event(), asyncio.Event()

        class Response:
            status = 200

            async def __aenter__(self):
                entered.set()
                await release.wait()
                return self

            async def __aexit__(self, *args):
                pass

            async def json(self):
                return {"status": "Charging"}

        api._session = SimpleNamespace(get=lambda *args, **kwargs: Response())
        read = asyncio.create_task(api._async_get("/status", step="wallbox status"))
        await entered.wait()
        api.command_feedback.begin("START")
        api.command_feedback.accepted()
        release.set()
        await read
        self.assertEqual(api.command_feedback.state, "Vom Portal angenommen")
        await api._async_get("/status", step="wallbox status")
        self.assertEqual(api.command_feedback.state, "Ausführung bestätigt")

    async def test_commands_serialize_network_requests(self):
        api = self.prepared_api()
        entered, release = asyncio.Event(), asyncio.Event()
        controls = []

        async def execute(control):
            controls.append(control)
            if control == "START":
                entered.set()
                await release.wait()

        api._async_execute_wallbox_control = execute
        start = asyncio.create_task(api.async_control_wallbox("START"))
        await entered.wait()
        stop = asyncio.create_task(api.async_control_wallbox("STOP"))
        await asyncio.sleep(0)
        self.assertEqual(controls, ["START"])
        release.set()
        await asyncio.gather(start, stop)
        self.assertEqual(controls, ["START", "STOP"])
        self.assertEqual(api.command_feedback.command, "STOP")

    async def test_sensor_remains_available_on_cloud_failure(self):
        source = ast.parse((ROOT / "sensor.py").read_text())
        sensor = next(node for node in source.body
                      if isinstance(node, ast.ClassDef) and node.name == "AlphaESSChargeCommandSensor")
        sensor.bases = []
        ns = {}
        exec(compile(ast.Module(body=[sensor], type_ignores=[]), "command sensor", "exec"), ns)
        item = object.__new__(ns["AlphaESSChargeCommandSensor"])
        feedback = self.feedback()
        feedback.failed("Verbindung gestört", "Statusprüfung fehlgeschlagen")
        item.coordinator = SimpleNamespace(api=SimpleNamespace(command_feedback=feedback),
                                           last_update_success=False)
        self.assertTrue(item.available)
        self.assertEqual(item.native_value, "Verbindung gestört")
        self.assertEqual(item.extra_state_attributes["Vorgangsnummer"], feedback.request_id)


if __name__ == "__main__":
    unittest.main()
