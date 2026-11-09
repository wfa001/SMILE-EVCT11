"""Requested values, HTTP acceptance and read-back are separate evidence."""
from __future__ import annotations

import ast
import asyncio
import copy
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from test_settings_write_lock import FakePortal, PortalConnectionError

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/alphaess_portal_bridge'
helpers = runpy.run_path(str(ROOT / 'write_feedback.py'))
Feedback = helpers['SettingsWriteFeedback']
targets = helpers['settings_targets']


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.feedback = Feedback(clock=lambda: self.now)
        self.targets = {('g2T', 'chargeCurrent'): (11, 'Ladestrom')}

    def accept(self):
        ticket = self.feedback.begin(self.targets)
        self.feedback.accepted(ticket)
        return self.feedback.revision

    def test_matching_read_back_is_required_after_acceptance(self):
        old_revision = self.feedback.revision
        ticket = self.feedback.begin(self.targets)
        during_send = self.feedback.revision
        self.feedback.accepted(ticket)
        self.assertEqual(self.feedback.state, 'Bestätigung ausstehend')
        for revision in (old_revision, during_send):
            self.feedback.observe({'g2T': {'chargeCurrent': 11}}, revision)
            self.assertEqual(self.feedback.state, 'Bestätigung ausstehend')
        self.feedback.observe({'g2T': {'chargeCurrent': 10}}, self.feedback.revision)
        self.assertEqual(self.feedback.state, 'Bestätigung ausstehend')
        self.feedback.observe({'g2T': {'chargeCurrent': 11}}, self.feedback.revision)
        self.assertEqual(self.feedback.state, 'Im Portal bestätigt')

    def test_deadline_is_not_rejection_and_later_read_can_confirm(self):
        revision = self.accept()
        self.now = 121
        self.assertEqual(self.feedback.state, 'Nicht bestätigt')
        self.feedback.observe({}, revision)
        self.assertEqual(self.feedback.state, 'Nicht bestätigt')
        self.feedback.observe({'g2T': {'chargeCurrent': 11}}, revision)
        self.assertEqual(self.feedback.state, 'Im Portal bestätigt')

    def test_old_request_cannot_confirm_a_newer_request(self):
        revision = self.accept()
        ticket = self.feedback.begin({('g2T', 'chargeCurrent'): (12, 'Ladestrom')})
        self.feedback.accepted(ticket)
        self.feedback.observe({'g2T': {'chargeCurrent': 12}}, revision)
        self.assertEqual(self.feedback.state, 'Bestätigung ausstehend')
        self.feedback.observe({'g2T': {'chargeCurrent': 11}}, self.feedback.revision)
        self.assertEqual(self.feedback.state, 'Bestätigung ausstehend')

    def test_false_is_not_numeric_zero_and_missing_fields_do_not_confirm(self):
        ticket = self.feedback.begin({('g2T', 'smartMode'): (False, 'Smart Mode')})
        self.feedback.accepted(ticket)
        for box in ({}, {'g2T': {}}, {'g2T': {'smartMode': 0}}):
            self.feedback.observe(box, self.feedback.revision)
            self.assertEqual(self.feedback.state, 'Bestätigung ausstehend')
        self.feedback.observe({'g2T': {'smartMode': False}}, self.feedback.revision)
        self.assertEqual(self.feedback.state, 'Im Portal bestätigt')

    def test_every_requested_field_must_match_but_unrelated_fields_do_not_matter(self):
        ticket = self.feedback.begin({('houseHoldCurrent',): (40, 'Hausstromgrenze'),
                                      ('g1T', 'timePeriods', 1, 'startTime'): ('05:17', 'Beginn')})
        self.feedback.accepted(ticket)
        box = {'houseHoldCurrent': 40, 'g1T': {'timePeriods': [{}, {'startTime': '05:16'}]}}
        self.feedback.observe(box, self.feedback.revision)
        self.assertEqual(self.feedback.state, 'Bestätigung ausstehend')
        box['g1T']['timePeriods'][1]['startTime'] = '05:17'
        box['unrelated'] = 'ignored'
        self.feedback.observe(box, self.feedback.revision)
        self.assertEqual(self.feedback.state, 'Im Portal bestätigt')

    def test_only_requested_whitelisted_fields_are_retained_or_exposed(self):
        wallbox = {'sn': 'PRIVATE', 'token': 'SECRET', 'houseHoldCurrent': 40,
                   'g1T': {'chargeMode': 2, 'timePeriods': [{}, {'startTime': '05:17'}]}}
        selected = targets(('async_update_time_period', (1,), {'start_time': '05:17', 'password': 'SECRET'}), wallbox)
        self.assertEqual(set(selected), {('g1T', 'timePeriods', 1, 'startTime')})
        self.feedback.begin(selected)
        attrs = str(self.feedback.attributes())
        for private in ('PRIVATE', 'SECRET', '05:17'):
            self.assertNotIn(private, attrs)
        self.assertEqual(targets(('other_method', (), {'token': 'SECRET'}), wallbox), {})


tree = ast.parse((ROOT / 'api.py').read_text())
api_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AlphaESSPortalApi')
patch_method = next(n for n in api_class.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_async_authenticated_patch')
namespace = {'Any': object, 'asyncio': asyncio, 'settings_targets': targets,
             'aiohttp': SimpleNamespace(ClientTimeout=lambda **kw: None, ClientError=ConnectionError),
             'PortalConnectionError': PortalConnectionError, 'PORTAL_HEADERS': {},
             '_LOGGER': SimpleNamespace(exception=lambda *a: None)}
patch_class = ast.ClassDef(name='Patch', bases=[], keywords=[],body=[patch_method],decorator_list=[])
exec(compile(ast.fix_missing_locations(ast.Module(body=[patch_class],type_ignores=[])), str(ROOT / 'api.py'), 'exec'), namespace)


class Response:
    def __init__(self, portal, payload):
        self.portal, self.payload, self.status = portal, payload, portal.http_status

    async def __aenter__(self):
        if self.portal.transport_error:
            raise self.portal.transport_error
        if self.status in (200, 201, 204):
            self.portal.configuration = copy.deepcopy(self.payload)
        return self

    async def __aexit__(self, *args):
        pass


class Portal(FakePortal):
    _async_authenticated_patch = namespace['Patch']._async_authenticated_patch

    def __init__(self):
        super().__init__()
        self.settings_feedback = Feedback()
        self.http_status = 204
        self.transport_error = None
        self.sent = []
        self._session = SimpleNamespace(patch=self.patch)
        self._api_url, self._token = 'https://example.invalid', 'TEST'
        self._async_token = AsyncMock()
        self._settings_written_callback = lambda: self.sent.append('readback scheduled')

    def patch(self, url, **kwargs):
        return Response(self, kwargs['json'])

    def _reject_authentication(self, step, status):
        return PortalConnectionError(status, step)


class PatchFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_success_means_pending_not_confirmed(self):
        portal = Portal()
        await portal.async_update_wallbox_settings(charge_current=11)
        self.assertEqual(portal.settings_feedback.state, 'Bestätigung ausstehend')
        self.assertEqual(portal.sent, ['readback scheduled'])
        self.assertIsNone(portal._settings_request_context)

    async def test_no_op_and_validation_error_do_not_create_transmission(self):
        portal = Portal()
        await portal.async_update_wallbox_settings(charge_current=6)
        with self.assertRaises(ValueError):
            await portal.async_update_wallbox_settings(charge_current=17)
        self.assertEqual(portal.settings_feedback.state, 'Keine Übertragung erfasst')
        self.assertEqual(portal.sent, [])

    async def test_transport_error_or_cancellation_does_not_claim_rejection(self):
        for error in (TimeoutError(), asyncio.CancelledError()):
            portal = Portal()
            portal.transport_error = error
            with self.assertRaises((PortalConnectionError, asyncio.CancelledError)):
                await portal.async_update_wallbox_settings(charge_current=11)
            self.assertEqual(portal.settings_feedback.state, 'Übertragung unklar')
            self.assertEqual(portal.sent, [])

    async def test_rejected_http_response_does_not_confirm_or_schedule_readback(self):
        for status in (400, 401, 403, 409, 429, 503):
            portal = Portal()
            portal.http_status = status
            with self.assertRaises(PortalConnectionError):
                await portal.async_update_wallbox_settings(charge_current=11)
            expected = 'Vom Portal abgelehnt' if status < 500 else 'Übertragung unklar'
            self.assertEqual(portal.settings_feedback.state, expected)
            self.assertEqual(portal.sent, [])

    async def test_period_write_does_not_track_unrelated_configuration(self):
        portal = Portal()
        await portal.async_update_time_period(0, start_time='08:07')
        self.assertEqual(set(portal.settings_feedback._targets), {('g2T', 'timePeriods', 0, 'startTime')})


if __name__ == '__main__':
    unittest.main()
