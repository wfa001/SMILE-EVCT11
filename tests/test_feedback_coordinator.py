"""A live or partial reply must not confirm settings or renew their age."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
import unittest

from test_fast_live_polling import FakeCoordinator
from test_write_feedback import Feedback


class CoordinatorFeedbackTests(unittest.IsolatedAsyncioTestCase):
    def coordinator(self):
        item = FakeCoordinator()
        item.api.settings_feedback = Feedback()
        item.api._find_wallbox_data = lambda config, serial: config if serial == 'example' else {}
        item._last_full_success = datetime(2026, 1, 1, tzinfo=timezone.utc)
        item._full_consecutive_errors = 0
        ticket = item.api.settings_feedback.begin({('g2T', 'chargeCurrent'): (11, 'Ladestrom')})
        item.api.settings_feedback.accepted(ticket)
        return item

    def reply(self, **extra):
        return {'wallbox_serial': 'example', 'configuration': {'g2T': {'chargeCurrent': 11}},
                'configuration_read_ok': True, **extra}

    async def test_successful_configuration_read_confirms_the_requested_value(self):
        item = self.coordinator()
        item.api.async_get_wallbox_data = AsyncMock(return_value=self.reply())
        await item._async_update_data()
        self.assertEqual(item.api.settings_feedback.state, 'Im Portal bestätigt')
        item.api.async_get_wallbox_data.assert_awaited_once()

    async def test_read_started_before_new_write_cannot_confirm_it(self):
        item = self.coordinator()
        feedback = item.api.settings_feedback
        async def concurrent_reply():
            ticket = feedback.begin({('g2T', 'chargeCurrent'): (11, 'Ladestrom')})
            feedback.accepted(ticket)
            return self.reply()
        item.api.async_get_wallbox_data = concurrent_reply
        await item._async_update_data()
        self.assertEqual(feedback.state, 'Bestätigung ausstehend')
        item.api.async_get_wallbox_data = AsyncMock(return_value=self.reply())
        await item._async_update_data()
        self.assertEqual(feedback.state, 'Im Portal bestätigt')

    async def test_partial_reply_does_not_renew_settings_timestamp_or_confirm(self):
        item = self.coordinator()
        old_stamp = item._last_full_success
        item.api.async_get_wallbox_data = AsyncMock(return_value=self.reply(configuration_read_ok=False))
        await item._async_update_data()
        self.assertEqual(item._last_full_success, old_stamp)
        self.assertEqual(item._full_success_count, 0)
        self.assertEqual(item._full_consecutive_errors, 1)
        self.assertEqual(item.api.settings_feedback.state, 'Bestätigung ausstehend')

    async def test_live_reply_cannot_confirm_a_setting(self):
        item = self.coordinator()
        item.api.statuses = [{'status': 'Charging', 'power': 2500, 'g2T': {'chargeCurrent': 11}}]
        await item._async_live_refresh(None)
        self.assertEqual(item.api.settings_feedback.state, 'Bestätigung ausstehend')

    async def test_unload_during_read_does_not_confirm(self):
        item = self.coordinator()
        async def reply_after_unload():
            item._stopped = True
            return self.reply()
        item.api.async_get_wallbox_data = reply_after_unload
        await item._async_update_data()
        self.assertEqual(item.api.settings_feedback.state, 'Bestätigung ausstehend')


if __name__ == '__main__':
    unittest.main()
