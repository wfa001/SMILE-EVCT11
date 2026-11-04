"""Volatile feedback for the latest settings PATCH, not physical execution."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import time

_LOGGER = logging.getLogger(__name__)
_FIELDS = {
    'charge_mode': ('chargeMode', 'Lademodus'),
    'charge_current': ('chargeCurrent', 'Ladestrom'),
    'charge_strategy': ('chargeStrategy', 'Ladeeinstellung'),
    'obc_phase': ('obcPhase', 'Phasenwahl'),
    'smart_mode': ('smartMode', 'Smart Mode'),
    'household_current': ('houseHoldCurrent', 'Hausstromgrenze'),
    'installer_control_allowed': ('allowInstallersControl', 'Installateursteuerung'),
    'gun_line_self_lock_enabled': ('gunLineSelfLockEnable', 'Kabel-Selbstverriegelung'),
}
_PERIOD_FIELDS = {
    'enabled': ('isEnable', 'Freigabe'), 'start_time': ('startTime', 'Beginn'),
    'end_time': ('endTime', 'Ende'), 'charge_mode': ('chargeMode', 'Lademodus'),
    'charge_current': ('chargeCurrent', 'Ladestrom'),
}


def _value(document, path):
    try:
        for key in path:
            document = document[key]
        return document
    except (KeyError, IndexError, TypeError):
        return None


def settings_targets(request, wallbox):
    """Retain only requested, known fields, never the full portal document."""
    if not request or not isinstance(wallbox, dict):
        return {}
    method, args, kwargs = request
    profile = next((p for p in ('g2T', 'g1T') if isinstance(wallbox.get(p), dict)), None)
    targets = {}
    if method == 'async_update_wallbox_settings':
        for parameter, (field, label) in _FIELDS.items():
            if kwargs.get(parameter) is None:
                continue
            path = (field,) if parameter in ('household_current', 'installer_control_allowed') else (profile, field)
            value = _value(wallbox, path)
            if type(value) in (bool, int, float, str):
                targets[path] = (value, label)
    elif method == 'async_update_time_period' and profile:
        index = args[0] if args else kwargs.get('index')
        if type(index) is not int or index not in (0, 1, 2):
            return {}
        for parameter, (field, label) in _PERIOD_FIELDS.items():
            if kwargs.get(parameter) is None:
                continue
            path = (profile, 'timePeriods', index, field)
            value = _value(wallbox, path)
            if type(value) in (bool, int, float, str):
                targets[path] = (value, f'Zeitfenster {index + 1}: {label}')
    return targets


class SettingsWriteFeedback:
    """Only a GET started after acceptance may confirm the latest request."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._listener = None
        self.revision = 0
        self._state = 'Keine Übertragung erfasst'
        self._targets = {}
        self._deadline = None
        self.sent_at = None
        self.confirmed_at = None
        self.started_at = None

    def set_listener(self, listener):
        self._listener = listener

    def _notify(self):
        if self._listener:
            try:
                self._listener()
            except Exception:
                _LOGGER.exception('Unable to update settings feedback')

    @property
    def state(self):
        if (self._state == 'Bestätigung ausstehend' and self._deadline is not None
                and self._clock() >= self._deadline):
            return 'Nicht bestätigt'
        return self._state

    def begin(self, targets):
        if not targets:
            return None
        self.revision += 1
        self._targets = dict(targets)
        self._state = 'Wird gesendet'
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.sent_at = self.confirmed_at = self._deadline = None
        self._notify()
        return self.revision

    def accepted(self, ticket):
        if ticket is None or ticket != self.revision:
            return
        self.revision += 1  # Invalidate GETs started during the PATCH, too.
        self._state = 'Bestätigung ausstehend'
        self.sent_at = datetime.now(timezone.utc).isoformat()
        self._deadline = self._clock() + 120
        self._notify()

    def failed(self, ticket, *, rejected=False):
        if ticket is None or ticket != self.revision or self._state != 'Wird gesendet':
            return
        self._state = 'Vom Portal abgelehnt' if rejected else 'Übertragung unklar'
        self._notify()

    def observe(self, wallbox, revision):
        if (revision != self.revision or self._state != 'Bestätigung ausstehend'
                or not self._targets):
            return
        for path, (expected, _) in self._targets.items():
            actual = _value(wallbox, path)
            if type(expected) is bool:
                matches = type(actual) is bool and actual == expected
            elif type(expected) in (int, float):
                matches = type(actual) in (int, float) and actual == expected
            else:
                matches = type(actual) is type(expected) and actual == expected
            if not matches:
                return
        self._state = 'Im Portal bestätigt'
        self.confirmed_at = datetime.now(timezone.utc).isoformat()
        # The coordinator publishes the result after completing its update.

    def attributes(self):
        return {
            'Einstellungsübertragung': self.state,
            'Betroffene Einstellungen': [label for _, label in self._targets.values()],
            'Übertragung begonnen am': self.started_at,
            'Übertragung angenommen am': self.sent_at,
            'Im Portal bestätigt am': self.confirmed_at,
        }
