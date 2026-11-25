"""Regression cases from the G1T/G2T November diagnostic recordings."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from zipfile import ZipFile

import test_api_history as history_tests
History = history_tests.History
storage = history_tests.storage
from test_authentication_recovery import make_api, PortalConnectionError as APIError
from test_diagnostics_privacy import load_helpers
from test_fast_live_polling import FakeCoordinator, PortalConnectionError, calls
from test_wallbox_communication import NS, coordinator_with


class PollRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_g1t_busy_retries_and_returns_to_fast_poll(self):
        for warm in (False, True):
            calls.clear()
            co = FakeCoordinator('g1T')
            co.api.history = SimpleNamespace(record=Mock())
            co.api.statuses = ([{'status': 'Charging'}] if warm else []) + [
                PortalConnectionError(409), {'status': 'Charging', 'power': 4169}]
            co.start_live_polling()
            if warm:
                await calls[-1].execute()
            await calls[-1].execute()
            self.assertIsNot(co._live_status_supported, False)
            self.assertEqual(calls[-1].delay, 10)
            await calls[-1].execute()
            self.assertTrue(co._live_status_supported)
            self.assertEqual(calls[-1].delay, 5)
            modes = [c.kwargs['mode'] for c in co.api.history.record.call_args_list
                     if c.kwargs.get('event') == 'live_polling_mode']
            self.assertEqual(modes, ['normal', 'backoff', 'normal'])

    async def test_g1t_repeated_busy_bounded_backoff_without_disabling(self):
        calls.clear()
        co = FakeCoordinator('g1T')
        co.api.statuses = [PortalConnectionError(409) for _ in range(7)]
        co.start_live_polling()
        for _ in range(7):
            await calls[-1].execute()
        self.assertEqual(calls[-1].delay, 120)
        self.assertIsNot(co._live_status_supported, False)
        self.assertFalse(co.api._live_status_unavailable_serials)

    async def test_running_read_does_not_look_disabled_or_start_second_timer(self):
        calls.clear()
        co = FakeCoordinator('g2T')
        entered, finish = asyncio.Event(), asyncio.Event()
        async def read(_):
            entered.set()
            await finish.wait()
            return {'status': 'Charging'}
        co.api.async_get_live_status = read
        co.start_live_polling()
        task = asyncio.create_task(calls[-1].execute())
        await entered.wait()
        try:
            diag = load_helpers()['_polling_diagnostics'](co)
            self.assertEqual(diag['live_interval_seconds'], 5)
            self.assertEqual(diag['live_poll_state'], 'running')
            co.start_live_polling()
            self.assertEqual(len(calls), 1)
        finally:
            finish.set()
            await task
        self.assertFalse(co._live_refresh_running)
        self.assertEqual(calls[-1].delay, 5)


class ReportAndSourceTests(unittest.TestCase):
    def test_missing_zero_positive_and_invalid_reports_are_distinct(self):
        fn = load_helpers()['_report_diagnostics']
        day = '2026-11-24'
        self.assertFalse(fn([], day)['daily_report_value_available'])
        old = [{'beginDate': '2026-11-23 00:20:00', 'chargingCapacity': 12.85}]
        self.assertEqual(fn(old, day)['today_report_state'], 'no_report_for_day')
        for value, state in [(0, 'reported_zero'), ('0.0', 'reported_zero'), (1.01, 'reported_positive'),
                             (None, 'invalid_values'), (True, 'invalid_values'), ('nan', 'invalid_values')]:
            result = fn([{'beginDate': day + ' 13:13:00', 'chargingCapacity': value}], day)
            self.assertEqual(result['today_report_state'], state)
        result = fn([{'beginDate': day, 'chargingCapacity': 0},
                     {'beginDate': day, 'chargingCapacity': None}], day)
        self.assertEqual(result['today_report_state'], 'incomplete_values')

    def test_timestamp_age_is_separate_and_invalid_stamps_stay_unknown(self):
        fn = load_helpers()['_device_timestamp_age']
        self.assertGreaterEqual(fn({'statusTs': (datetime.now(timezone.utc)-timedelta(seconds=33)).isoformat()}), 33)
        for value in (None, 'broken', '2026-11-24T13:00:00', (datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()):
            self.assertIsNone(fn({'statusTs': value}))

    def test_g1t_trace_identifies_site_value_not_missing_live_counter(self):
        co = coordinator_with({'status': 'Charging'}, generation='g1T')
        day = NS['dt_util'].now().date().isoformat()
        co.data.update(site_daily_energy=(day, 8.07), site_daily_energy_fetched_at='2026-11-24T14:07:36+01:00')
        co.api.history = SimpleNamespace(enabled=True, record=Mock())
        sensor = NS['AlphaESSWallboxDailyEnergySensor'](co, None)
        self.assertEqual(sensor.native_value, 8.07)
        event = co.api.history.record.call_args.kwargs
        self.assertEqual(event['input'], 'missing')
        self.assertEqual(event['value_source'], 'site_energy')
        self.assertEqual(event['value_field'], 'evCharge.load')
        self.assertEqual(event['source_day'], day)
        self.assertEqual(event['source_fetched_at'], co.data['site_daily_energy_fetched_at'])


class RawEnergyTests(unittest.IsolatedAsyncioTestCase):
    async def test_energy_records_full_payload_but_not_private_url(self):
        for step in ('site daily energy', 'site energy seven days'):
            payload = {'ts': ['2026-11-24'], 'evCharge': {'load': [None]},
                       'futureField': {'items': list(range(80))}}
            api, _ = make_api([(200, payload)])
            api.history = SimpleNamespace(enabled=True, record=Mock())
            api._token, api._expires_at = 'test', float('inf')
            result = await api._async_get('/internal/v1/sites/PRIVATE-SITE/energy', step=step, supplemental=True)
            event = api.history.record.call_args.kwargs
            self.assertEqual(result, payload)
            self.assertEqual(event['response'], payload)
            self.assertNotIn('PRIVATE-SITE', event['endpoint'])

    async def test_energy_error_body_retained_without_affecting_auth_policy(self):
        api, _ = make_api([(409, {'code': 6026, 'futureReason': 'busy'})])
        api.history = SimpleNamespace(enabled=True, record=Mock())
        api._token, api._expires_at = 'test', float('inf')
        with self.assertRaises(APIError):
            await api._async_get('/internal/v1/sites/PRIVATE-SITE/energy', step='site daily energy', supplemental=True)
        event = api.history.record.call_args.kwargs
        self.assertEqual(event['response']['code'], 6026)
        self.assertNotIn('PRIVATE-SITE', json.dumps(event))


class ArchiveReliabilityTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = history_tests.ApiHistoryTests.asyncSetUp
    history = history_tests.ApiHistoryTests.history

    async def test_legacy_install_dates_removed_unknown_energy_preserved_and_runs_survive(self):
        old = self.history()
        # Simulate pre-filter rows already on disk.
        old._write([(self.now, 'api', {'method': 'GET', 'step': 'site daily energy', 'http_status': 200,
                   'response': {'installDate': 'PRIVATE-DATE', 'nested': {'install_datetime': 'PRIVATE-TIME'},
                                'newMetric': [1, None, {'parsedValue': 0}]}})], self.now - 86400)
        first = History(self.hass, 'test-entry', True, (), build={'code_fingerprint': 'first'})
        first.record('bridge', event='recording_started')
        await first.async_close()
        second = History(self.hass, 'test-entry', True, (), build={'code_fingerprint': 'second'})
        second.record('bridge', event='recording_started')
        with await second.async_export({}, {}) as output, ZipFile(output) as archive:
            raw = b'\n'.join(archive.read(n) for n in archive.namelist())
            self.assertNotIn(b'PRIVATE-DATE', raw)
            self.assertNotIn(b'PRIVATE-TIME', raw)
            responses = [json.loads(x)['response'] for x in archive.read('api-antworten.jsonl').splitlines()]
            self.assertEqual(responses[0]['newMetric'], [1, None, {'parsedValue': 0}])
            events = [json.loads(x) for x in archive.read('bridge-verlauf.jsonl').splitlines()]
            starts = [x for x in events if x.get('event') == 'recording_started']
            self.assertNotEqual(starts[0]['recording_run'], starts[1]['recording_run'])
            self.assertEqual([x['build_fingerprint'] for x in starts], ['first', 'second'])
            self.assertEqual(json.loads(archive.read('diagnose.json'))['recording_context']['build']['code_fingerprint'], 'second')

    async def test_build_fingerprint_has_no_local_path_or_device_identity(self):
        build = storage['diagnostic_build']()
        self.assertEqual(len(build['code_fingerprint']), 16)
        self.assertEqual(build, storage['diagnostic_build']())
        self.assertNotIn(str(self.root), json.dumps(build))
