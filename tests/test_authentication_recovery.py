"""Exercise real API/coordinator/flow methods with no network or HA install."""
from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "alphaess_portal_bridge"


def extract(filename, class_name, methods, namespace, *, include=()):
    """Use production bodies (as the repository's other standalone tests do)."""
    source = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    classes = {node.name: node for node in source.body if isinstance(node, ast.ClassDef)}
    cls = classes[class_name]
    cls.bases = []
    cls.keywords = []
    cls.body = [node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in methods]
    assert {node.name for node in cls.body} == set(methods)
    module = ast.fix_missing_locations(ast.Module(body=[*(classes[name] for name in include), cls], type_ignores=[]))
    exec(compile(module, str(ROOT / filename), "exec"), namespace)
    return namespace[class_name]


class Response:
    def __init__(self, status, data):
        self.status, self.data = status, data

    async def __aenter__(self):
        # Yield so multiple calls genuinely wait for the shared token lock.
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return self.data


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.logins = []
        self.gets = []

    def post(self, url, **kwargs):
        self.logins.append((url, kwargs["json"]))
        return Response(*self.responses.pop(0))

    def get(self, url, **kwargs):
        self.gets.append(url)
        if url.endswith("/region"):
            return Response(200, {"endPoint": "https://example.invalid/api"})
        return Response(*self.responses.pop(0))


API_NS = {
    "asyncio": asyncio, "time": time, "API_URL": "https://example.invalid/api",
    "PORTAL_HEADERS": {}, "CONF_USERNAME": "username", "CONF_PASSWORD": "password",
    "CONF_SYSTEM_SERIAL": "system_serial", "CONF_WALLBOX_SERIAL": "wallbox_serial",
    "CONF_AUTHENTICATION_PAUSED": "authentication_paused",
    "async_get_clientsession": lambda hass: hass.session,
    "aiohttp": SimpleNamespace(ClientTimeout=lambda **kwargs: None, ClientError=ConnectionError),
}
API = extract("api.py", "AlphaESSPortalApi", {
    "__init__", "_async_token", "_async_create_token", "_reject_authentication",
    "_async_post", "_async_select_region", "_async_get",
}, API_NS, include=("AuthenticationError", "PortalConnectionError"))
AuthenticationError = API_NS["AuthenticationError"]
PortalConnectionError = API_NS["PortalConnectionError"]


def make_api(responses):
    session = Session(responses)
    api = API(SimpleNamespace(session=session), {
        "username": "example", "password": "new-password", "system_serial": "TEST",
    })
    api._encrypt_password = lambda: "encrypted-test-value"
    return api, session


class APITests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_pause_prevents_login_after_restart(self):
        session = Session([])
        api = API(SimpleNamespace(session=session), {
            "username": "example", "password": "old-password", "system_serial": "TEST",
            "authentication_paused": True,
        })
        with self.assertRaises(AuthenticationError):
            await api._async_token()
        self.assertEqual(session.logins, [])
        self.assertEqual(session.gets, [])

    async def test_rejected_login_stops_concurrent_and_later_attempts(self):
        for status in (400, 401, 403, 409, 429):
            with self.subTest(status=status):
                api, session = make_api([(status, {})])
                results = await asyncio.gather(*(api._async_token() for _ in range(5)), return_exceptions=True)
                self.assertTrue(all(isinstance(result, AuthenticationError) for result in results))
                self.assertTrue(all(result.status == status for result in results))
                with self.assertRaises(AuthenticationError):
                    await api._async_token()
                self.assertEqual(len(session.logins), 1)
                self.assertEqual(len(session.gets), 1)

    async def test_concurrent_success_uses_one_session(self):
        api, session = make_api([(201, {"token": "test-token"})])
        results = await asyncio.gather(*(api._async_token() for _ in range(5)))
        self.assertEqual(results, ["Bearer test-token"] * 5)
        self.assertEqual(len(session.logins), 1)

    async def test_rejected_refresh_does_not_fall_back_to_password(self):
        api, session = make_api([(409, {})])
        api._refresh_token = "expired-test-token"
        for _ in range(2):
            with self.assertRaises(AuthenticationError):
                await api._async_token()
        self.assertEqual(len(session.logins), 1)
        self.assertTrue(session.logins[0][0].endswith("/refresh"))
        self.assertEqual(session.gets, [])

    async def test_missing_token_is_also_paused(self):
        api, session = make_api([(200, {"data": {}})])
        for _ in range(2):
            with self.assertRaises(AuthenticationError):
                await api._async_token()
        self.assertEqual(len(session.logins), 1)

    async def test_server_failure_remains_retryable(self):
        api, session = make_api([(503, {}), (201, {"token": "test-token"})])
        with self.assertRaises(PortalConnectionError):
            await api._async_token()
        self.assertEqual(await api._async_token(), "Bearer test-token")
        self.assertEqual(len(session.logins), 2)

    async def test_live_409_is_not_a_login_failure(self):
        api, session = make_api([(409, {})])
        api._token, api._expires_at = "Bearer test-token", time.monotonic() + 300
        with self.assertRaises(PortalConnectionError):
            await api._async_get("/real-status", step="wallbox status")
        self.assertEqual(await api._async_token(), "Bearer test-token")
        self.assertEqual(session.logins, [])

    async def test_session_revocation_stops_subsequent_network_requests(self):
        api, session = make_api([(401, {})])
        api._token, api._expires_at = "Bearer test-token", time.monotonic() + 300
        for _ in range(2):
            with self.assertRaises(AuthenticationError):
                await api._async_get("/system", step="system check")
        self.assertEqual(len(session.gets), 1)
        self.assertEqual(session.logins, [])


class ConfigEntryAuthFailed(Exception):
    pass


COORD_NS = {
    "CONF_AUTHENTICATION_PAUSED": "authentication_paused",
    "AuthenticationError": AuthenticationError, "PortalConnectionError": PortalConnectionError,
    "ConfigEntryAuthFailed": ConfigEntryAuthFailed, "UpdateFailed": RuntimeError,
    "time": time, "datetime": datetime, "timezone": timezone,
    "_G2T_LIVE_INTERVAL_SECONDS": 5, "_LOGGER": Mock(),
}
Coordinator = extract("coordinator.py", "AlphaESSWallboxCoordinator", {
    "_async_update_data", "_async_live_refresh", "_authentication_failed",
    "stop_live_polling", "stop_followup_refresh",
}, COORD_NS)


def make_coordinator(api):
    obj = Coordinator()
    obj.api = api
    obj.hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))
    obj.data = {"wallbox_serial": "TEST"}
    obj._stopped = False
    obj._live_revision = 0
    obj._full_failure_count = obj._full_consecutive_errors = obj._live_failure_count = 0
    obj._cancel_followup_refresh, obj._live_refresh_cancel = Mock(), Mock()
    obj.config_entry = SimpleNamespace(async_start_reauth=Mock(), data={"password": "old-password"})
    obj.async_set_update_error = Mock()
    obj._schedule_live_refresh = Mock()
    return obj


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_refresh_raises_auth_failed_instead_of_retryable_failure(self):
        api = SimpleNamespace(async_get_wallbox_data=AsyncMock(side_effect=AuthenticationError(status=409)), set_settings_written_callback=Mock())
        coordinator = make_coordinator(api)
        followup, live = coordinator._cancel_followup_refresh, coordinator._live_refresh_cancel
        with self.assertRaises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()
        followup.assert_called_once()
        live.assert_called_once()
        self.assertTrue(coordinator._stopped)
        coordinator.hass.config_entries.async_update_entry.assert_called_once_with(
            coordinator.config_entry, data={"password": "old-password", "authentication_paused": True},
        )

    async def test_live_failure_stops_timers_and_starts_reauth(self):
        api = SimpleNamespace(async_get_live_status=AsyncMock(side_effect=AuthenticationError(status=409)), set_settings_written_callback=Mock())
        coordinator = make_coordinator(api)
        followup = coordinator._cancel_followup_refresh
        await coordinator._async_live_refresh(None)
        followup.assert_called_once()
        self.assertTrue(coordinator._stopped)
        coordinator._schedule_live_refresh.assert_not_called()
        coordinator.config_entry.async_start_reauth.assert_called_once_with(coordinator.hass)
        self.assertIsInstance(coordinator.async_set_update_error.call_args.args[0], ConfigEntryAuthFailed)


FLOW_NS = {
    "CONF_AUTHENTICATION_PAUSED": "authentication_paused",
    "AuthenticationError": AuthenticationError, "PortalConnectionError": PortalConnectionError,
    "CONF_USERNAME": "username", "CONF_PASSWORD": "password",
    "vol": SimpleNamespace(Schema=lambda data: data, Required=lambda key, **kwargs: key),
}
Flow = extract("config_flow.py", "AlphaESSPortalBridgeConfigFlow", {
    "async_step_reauth", "async_step_reauth_confirm",
}, FLOW_NS)


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.entry = SimpleNamespace(data={"username": "example", "password": "old-password", "system_serial": "TEST", "wallbox_serial": "WALLBOX", "authentication_paused": True}, entry_id="same-entry")
        self.flow = Flow()
        self.flow.hass = object()
        self.flow._get_reauth_entry = lambda: self.entry
        self.flow.async_show_form = lambda **kwargs: kwargs
        self.flow.async_update_reload_and_abort = Mock(return_value={"type": "abort", "reason": "reauth_successful"})
        self.api = SimpleNamespace(async_validate_login=AsyncMock())
        self.factory = Mock(return_value=self.api)
        FLOW_NS["AlphaESSPortalApi"] = self.factory

    async def test_opening_reauth_does_not_attempt_login(self):
        result = await self.flow.async_step_reauth(self.entry.data)
        self.assertEqual(result["step_id"], "reauth_confirm")
        self.factory.assert_not_called()
        self.assertNotIn("old-password", repr(result))

    async def test_success_updates_credentials_on_same_entry(self):
        result = await self.flow.async_step_reauth_confirm({"username": "example", "password": "new-password"})
        self.assertEqual(result["reason"], "reauth_successful")
        self.api.async_validate_login.assert_awaited_once()
        self.flow.async_update_reload_and_abort.assert_called_once_with(self.entry, data_updates={"username": "example", "password": "new-password", "authentication_paused": False})
        self.assertEqual(self.factory.call_args.args[1]["system_serial"], "TEST")
        self.assertEqual(self.factory.call_args.args[1]["wallbox_serial"], "WALLBOX")
        self.assertFalse(self.factory.call_args.args[1]["authentication_paused"])

    async def test_rejected_submission_stays_on_form_without_saving_or_retrying(self):
        for status in (401, 409, 429):
            with self.subTest(status=status):
                self.api.async_validate_login.reset_mock()
                self.api.async_validate_login.side_effect = AuthenticationError(status=status)
                result = await self.flow.async_step_reauth_confirm({"username": "example", "password": "wrong-password"})
                self.assertEqual(result["errors"]["base"], "invalid_auth" if status == 401 else "login_paused")
                self.api.async_validate_login.assert_awaited_once()
                self.flow.async_update_reload_and_abort.assert_not_called()
                self.assertEqual(self.entry.data["password"], "old-password")
                self.assertTrue(self.entry.data["authentication_paused"])

    async def test_network_failure_does_not_save_credentials(self):
        self.api.async_validate_login.side_effect = PortalConnectionError()
        result = await self.flow.async_step_reauth_confirm({"username": "example", "password": "new-password"})
        self.assertEqual(result["errors"]["base"], "cannot_connect")
        self.flow.async_update_reload_and_abort.assert_not_called()


if __name__ == "__main__":
    unittest.main()
