"""Feedback for requested charging commands and subsequent portal observations."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from math import isfinite
from uuid import uuid4

_LOGGER = logging.getLogger(__name__)
CONFIRMATION_SECONDS = 120


class ChargeCommandFeedback:
    """Track one command using a fresh read after the portal accepted it."""

    def __init__(self):
        self.revision = 0
        self.state = "Kein Ladebefehl erfasst"
        self.command = None
        self.request_id = None
        self.requested_at = None
        self.accepted_at = None
        self.confirmed_at = None
        self.error = None
        self.power = None
        self._listener = None
        self._timer = None
        self._closed = False

    def set_listener(self, listener):
        self._listener = listener

    def _notify(self):
        if self._listener:
            try:
                self._listener()
            except Exception:
                _LOGGER.exception("Unable to publish charge command feedback")

    def close(self):
        self._closed = True
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self._listener = None

    def begin(self, command):
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self.revision += 1
        self.command = command
        self.request_id = uuid4().hex
        self.requested_at = datetime.now(timezone.utc).isoformat()
        self.accepted_at = self.confirmed_at = self.error = self.power = None
        self.state = "Wird gesendet"
        self._notify()

    def accepted(self):
        if self._closed:
            return
        self.revision += 1
        self.accepted_at = datetime.now(timezone.utc).isoformat()
        self.state = "Vom Portal angenommen"
        self._timer = asyncio.get_running_loop().call_later(
            CONFIRMATION_SECONDS, self.failed, "Nicht bestätigt", "Bestätigungsfrist abgelaufen"
        )
        self._notify()

    def failed(self, state, reason):
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self.state = state
        self.error = reason
        self._notify()

    def observe(self, status, revision):
        if (revision != self.revision or self.state != "Vom Portal angenommen"
                or not isinstance(status, dict)):
            return
        # statusTs belongs to the device reading, so a stale cloud result
        # cannot confirm a command merely because the HTTP response is new.
        if "statusTs" in status:
            try:
                stamp = datetime.fromisoformat(status["statusTs"].replace("Z", "+00:00"))
                if stamp.tzinfo is None or stamp <= datetime.fromisoformat(self.accepted_at):
                    return
            except (AttributeError, TypeError, ValueError):
                return
        raw_power = status.get("power")
        self.power = (raw_power if type(raw_power) in (int, float)
                      and isfinite(raw_power) and raw_power >= 0 else None)
        target = ({"Charging"} if self.command == "START"
                  else {"ChargingStopped", "CharingStopped"})
        if status.get("status") not in target:
            return
        if self.command == "STOP" and self.power is not None and self.power > 0:
            return
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self.state = "Ausführung bestätigt"
        self.confirmed_at = datetime.now(timezone.utc).isoformat()
        self._notify()

    def attributes(self):
        return {
            "Befehl": self.command,
            "Vorgangsnummer": self.request_id,
            "Angefordert am": self.requested_at,
            "Vom Portal angenommen am": self.accepted_at,
            "Ausführung bestätigt am": self.confirmed_at,
            "Fehlergrund": self.error,
            "Gemeldete Ladeleistung (W)": self.power,
            "Bestätigungsfrist (s)": CONFIRMATION_SECONDS,
            "Hinweis": "Bestätigung anhand einer neuen Portal-Statusantwort nach dem Befehl.",
        }
