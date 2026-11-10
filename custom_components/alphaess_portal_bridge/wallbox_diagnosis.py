"""Bounded read-only diagnosis: portal, status reply and reported faults.

Only literal manufacturer fault names are translated for known models.
Numeric portal codes are NOT LED blink counts and have no verified mapping.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math

_MODELS = {'SMILE-EVCT11', 'SMILE-G3-EVCT11', 'SMILE-G3-EVCT11/S'}
# SMILE-EVCT11 V2.0 pp. 11-12; SMILE-G3-EVCT11 V04 pp. 21-22.
# Describe the reported category, never infer the wiring defect or a repair.
_FAULT_NAMES = {
    'OverVolt': 'Überspannung', 'UnderVolt': 'Unterspannung',
    'OverCurr': 'Überstrom', 'OverFreq': 'Netzfrequenz zu hoch',
    'UnderFreq': 'Netzfrequenz zu niedrig', 'OverTemp': 'Übertemperatur',
    'OverDCLeak': 'Fehlerstrom gegen Erde',
    'PhaseError': 'Phasen-/Anschlussfehler', 'CableRCError': 'Ladekabel-Anschlussfehler',
}
_ALIASES = {'Over DCLeak': 'OverDCLeak', 'Phase Error': 'PhaseError', 'CableRC Error': 'CableRCError'}
_NORMAL = {'NotInsertedGun', 'PendingStart', 'Charging', 'ChargingStopped',
           'CharingStopped', 'InsufficientPower', 'WaitingForChargingPile', 'Upgrading'}


def _fault_code(status, model):
    raw = status.get('faultCode') if isinstance(status, dict) else None
    code = raw.strip() if isinstance(raw, str) else raw
    canonical = _ALIASES.get(code, code) if isinstance(code, str) else None
    known_model = isinstance(model, str) and model.strip() in _MODELS
    known = known_model and isinstance(canonical, str) and canonical in _FAULT_NAMES
    kind = ('not_reported' if raw is None else 'number' if type(raw) in (int, float)
            else 'text' if isinstance(raw, str) else 'unexpected_type')
    if isinstance(raw, str):
        raw = raw[:128]
    elif type(raw) is int:
        raw = raw if -(2**63) <= raw <= 2**64 - 1 else None
    elif type(raw) is float:
        raw = raw if math.isfinite(raw) else None
    else:
        raw = None
    return {'raw_code': raw, 'code_kind': kind,
            'recognized_name': canonical if known else None,
            'fault_text': _FAULT_NAMES[canonical] if known else None}


def summarize_wallbox(*, profile, model, status, source, portal, age, stale_after):
    """Return fixed vocabulary; no values from unknown status fields in text."""
    portal = portal if isinstance(portal, str) and portal in {'Verbunden', 'Gestört', 'Getrennt'} else 'Unbekannt'
    source = source if isinstance(source, str) and source in {'real_status', 'system'} else 'unknown'
    fresh = (type(age) in (int, float) and math.isfinite(age)
             and 0 <= age <= stale_after and isinstance(profile, str) and profile in {'g1T', 'g2T'}
             and source != 'unknown' and isinstance(status, dict))
    code = _fault_code(status, model)
    raw_status = status.get('status') if isinstance(status, dict) else None
    if source == 'system' and raw_status in (None, '') and isinstance(status, dict):
        raw_status = status.get('chargingStatus', status.get('state'))
    fault = fresh and isinstance(raw_status, str) and raw_status in {'Fault', 'Error'}
    missing = fresh and source == 'real_status' and raw_status in (None, '')
    normal = fresh and isinstance(raw_status, str) and raw_status in _NORMAL
    disconnected = fresh and raw_status == 'Disconnected'
    communication = ('Nicht aktuell prüfbar' if not fresh else 'Keine Statusangabe' if missing
                     else 'Getrennt gemeldet' if disconnected
                     else 'Status empfangen' if source == 'real_status' and isinstance(raw_status, str) and raw_status
                     else 'Status aus Systemdaten' if isinstance(raw_status, str) and raw_status
                     else 'Statusformat nicht bestätigt')
    if not fresh:
        summary = 'Portal nicht erreichbar' if portal == 'Getrennt' else 'Status nicht aktuell prüfbar'
    elif fault:
        summary = 'Wallbox meldet Störung'
    elif missing:
        summary = 'Keine Statusrückmeldung'
    elif disconnected:
        summary = 'Geräteverbindung getrennt gemeldet'
    elif portal != 'Verbunden':
        summary = 'Portal-Verbindung eingeschränkt'
    elif normal:
        summary = 'Kein Fehlerstatus gemeldet'
    else:
        summary = 'Status nicht eindeutig'
    explanation = code['fault_text']
    if not explanation and code['code_kind'] != 'not_reported':
        explanation = 'Für diesen Portalcode ist keine Zuordnung bestätigt.'
    elif not explanation and fault:
        explanation = 'Störung ohne auswertbaren Fehlercode gemeldet.'
    return {**code, 'summary': summary, 'portal': portal, 'communication': communication,
            'source': source, 'fresh': bool(fresh), 'fault_reported': bool(fault),
            'status_age_seconds': min(315360000, int(age))
            if type(age) in (int, float) and math.isfinite(age) and age >= 0 else None,
            'fault_status': ('Nicht aktuell prüfbar' if not fresh else 'Störung gemeldet' if fault
                             else 'Kein Fehlerstatus gemeldet' if normal else 'Nicht eindeutig'),
            'fault_explanation': explanation}


def coordinator_diagnosis(coordinator, wallbox):
    """Read cached coordinator state only; no API calls or state changes."""
    data = coordinator.data or {}
    wallbox = wallbox if isinstance(wallbox, dict) else {}
    profile = next((p for p in ('g2T', 'g1T') if isinstance(wallbox.get(p), dict)), None)
    stamp = getattr(coordinator, '_last_status_success', None)
    now = datetime.now(timezone.utc)
    age = ((now - stamp).total_seconds()
           if isinstance(stamp, datetime) and stamp.tzinfo and not getattr(coordinator, '_stopped', False)
           else None)
    interval = coordinator.update_interval.total_seconds() if coordinator.update_interval else 30
    source = data.get('wallbox_status_source')
    limit = 25 if source == 'real_status' and getattr(coordinator, '_live_status_supported', None) is True else max(90, 3 * interval)
    return summarize_wallbox(profile=profile, model=wallbox.get('model'),
        status=data.get('wallbox_status'), source=source,
        portal=getattr(coordinator, 'api_connection_status', 'Unbekannt'), age=age, stale_after=limit)


def public_diagnosis(snapshot):
    """No arbitrary raw codes, model strings, timestamps or charging values."""
    return {key: snapshot[key] for key in (
        'summary', 'portal', 'communication', 'source', 'fresh', 'fault_reported',
        'fault_status', 'code_kind', 'recognized_name', 'fault_text', 'status_age_seconds')}


def public_write_feedback(api):
    state = getattr(getattr(api, 'settings_feedback', None), 'state', None)
    allowed = {'Keine Übertragung erfasst', 'Wird gesendet', 'Bestätigung ausstehend',
               'Nicht bestätigt', 'Im Portal bestätigt', 'Vom Portal abgelehnt', 'Übertragung unklar'}
    return state if isinstance(state, str) and state in allowed else 'Nicht verfügbar'
