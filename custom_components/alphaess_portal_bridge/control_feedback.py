"""Short explanations derived only from known control guards."""
from __future__ import annotations


def control_reason(control, profile, settings, status, portal_available):
    if not portal_available:
        return 'Keine aktuelle Portal-Verbindung; Steuerung derzeit nicht verfügbar.'
    if profile == 'g2T' and settings.get('chargeStrategy') != 0:
        if settings.get('chargeStrategy') in (1, 2):
            return 'Start/Stopp ist nur bei Ladeeinstellung Manuell verfügbar.'
        return 'Ladeeinstellung derzeit nicht bestätigt.'
    allowed = ({'PendingStart', 'ChargingStopped', 'CharingStopped'} if control == 'START'
               else {'Charging', 'WaitingForChargingPile'})
    if not isinstance(status, str) or not status:
        return 'Kein aktueller Wallboxstatus verfügbar.'
    if status in allowed:
        return None
    if status == 'NotInsertedGun':
        return 'Zum Laden ein Fahrzeug anschließen.'
    if status == 'InsufficientPower':
        return 'Die Wallbox meldet unzureichende Leistung.'
    if status in {'Error', 'Fault', 'Disconnected'}:
        return 'Start/Stopp ist beim gemeldeten Fehlerstatus nicht verfügbar.'
    return 'Start/Stopp ist für den gemeldeten Status nicht freigegeben.'
