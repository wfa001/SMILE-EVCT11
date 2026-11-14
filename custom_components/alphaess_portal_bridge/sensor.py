"""Read-only wallbox entities for AlphaESS Wallbox Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe NOTICE.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from dataclasses import dataclass
from math import isfinite
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfElectricCurrent, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import AlphaESSWallboxCoordinator
from .wallbox_diagnosis import coordinator_diagnosis
from .entity import (
    G1_MODES,
    G2_MODES,
    STATUS_NAMES,
    AlphaESSWallboxEntity,
    settings_object,
    wallbox_communication_missing,
    wallbox_object,
)

_LOGGER = logging.getLogger(__name__)
_ENERGY_STATUS = (
    "NotInsertedGun", "PendingStart", "Charging", "ChargingStopped",
    "CharingStopped", "InsufficientPower", "WaitingForChargingPile",
)


def _finite_energy(raw: Any) -> float | None:
    if type(raw) not in (int, float, str):
        return None
    try:
        number = float(raw)
    except (ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _first_value(data: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(data, dict):
        return None
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up wallbox sensors."""
    coordinator: AlphaESSWallboxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AlphaESSWallboxStatusSensor(coordinator, entry),
            AlphaESSBridgeConnectionSensor(coordinator, entry),
            AlphaESSWallboxDiagnosisSensor(coordinator, entry),
            AlphaESSWallboxPowerSensor(coordinator, entry),
            AlphaESSYesNoSensor(coordinator, entry, "Fahrzeug angeschlossen", "vehicle_connected"),
            AlphaESSYesNoSensor(coordinator, entry, "Ladestecker verriegelt", "gun_locked"),
            AlphaESSWallboxDailyEnergySensor(coordinator, entry),
            AlphaESSWallboxEnergySensor(coordinator, entry, "Aktuelle / letzte Ladesitzung", "lastChargingAmount", "last_energy"),
            AlphaESSWallboxLastChargeSensor(coordinator, entry),
            AlphaESSWallboxModeSensor(coordinator, entry),
            AlphaESSWallboxGenerationSensor(coordinator, entry),
            AlphaESSWallboxInformationSensor(coordinator, entry, "Serialnummer", "sn"),
            AlphaESSWallboxInformationSensor(coordinator, entry, "Modell", "model"),
            AlphaESSHardwarePhaseSensor(coordinator, entry),
            AlphaESSWallboxInformationSensor(
                coordinator, entry, "Startleistung", "startUpPower", UnitOfPower.WATT
            ),
            AlphaESSWallboxInformationSensor(coordinator, entry, "Software", "softwareVersion"),
            AlphaESSWallboxInformationSensor(coordinator, entry, "Hardware", "hardwareVersion"),
        ]
    )


class AlphaESSBridgeConnectionSensor(AlphaESSWallboxEntity, SensorEntity):
    """Portal API health for G1T and G2T, independent of device availability."""

    _attr_name = "Wallbox Bridge Verbindung"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-check"

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "api_connection")

    @property
    def available(self) -> bool:
        # Must remain visible while the portal is unavailable.
        return True

    @property
    def native_value(self) -> str:
        return self.coordinator.api_connection_status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        coordinator = self.coordinator
        return {
            "Hinweis": (
                "Portal-Verbindung; Abfragezeit ist keine Messzeit der Wallbox. "
                "Portalbestätigung bestätigt nur gespeicherte Einstellungen, keine physische Ausführung."
            ),
            **(coordinator.api.settings_feedback.attributes()
               if getattr(coordinator.api, 'settings_feedback', None) else {}),
            "Letzte erfolgreiche Live-Abfrage": (
                coordinator._last_live_success.isoformat()
                if coordinator._last_live_success else None
            ),
            "Letzte erfolgreiche Konfigurationsabfrage": (
                coordinator._last_full_success.isoformat()
                if coordinator._last_full_success else None
            ),
            "Live-Abfragen erfolgreich": coordinator._live_success_count,
            "Live-Abfragen fehlgeschlagen": coordinator._live_failure_count,
            "Konfigurationsabfragen erfolgreich": coordinator._full_success_count,
            "Konfigurationsabfragen fehlgeschlagen": coordinator._full_failure_count,
            "Live-Fehler in Folge": coordinator._live_refresh_errors,
            "Konfigurationsfehler in Folge": coordinator._full_consecutive_errors,
            "Letzte Live-Antwortzeit (ms)": coordinator._live_last_duration_ms,
            "Letzte Konfigurationsantwortzeit (ms)": coordinator._full_last_duration_ms,
            "Letzter Live-HTTP-Fehler": coordinator._live_last_http_status,
            "Letzter API-Fehler": coordinator._last_api_error,
            "Live-Endpunkt unterstützt": coordinator._live_status_supported,
        }


class AlphaESSWallboxDiagnosisSensor(AlphaESSWallboxEntity, SensorEntity):
    """Keep a bounded diagnosis visible when cloud/device state is uncertain."""

    _attr_name = 'Wallbox-Diagnose'
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = 'mdi:stethoscope'

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, 'diagnosis')

    @property
    def available(self):
        return True

    @property
    def native_value(self):
        return coordinator_diagnosis(self.coordinator, self.wallbox)['summary']

    @property
    def extra_state_attributes(self):
        result = coordinator_diagnosis(self.coordinator, self.wallbox)
        return {'Portal-Verbindung': result['portal'],
                'Statusrückmeldung': result['communication'],
                'Fehlerstatus': result['fault_status'],
                'Datenquelle': result['source'],
                'Status aktuell auswertbar': result['fresh'],
                'Alter der Statusantwort (s)': result['status_age_seconds'],
                'Fehlercode (Portal)': result['raw_code'],
                'Fehlerhinweis': result['fault_explanation'],
                'Code-Zuordnung': 'Hersteller-Fehlername' if result['recognized_name'] else 'Nicht bestätigt'}


class AlphaESSWallboxStatusSensor(AlphaESSWallboxEntity, SensorEntity):
    """Wallbox connection and charging status."""

    _attr_name = "Status"

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "status")

    @property
    def _status(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        status = data.get("wallbox_status")
        return status if isinstance(status, dict) else {}

    @property
    def native_value(self) -> str | int | None:
        if wallbox_communication_missing(self.coordinator):
            return "Keine Kommunikation zwischen Wallbox und Energiespeichersystem"
        value = _first_value(self._status, "status", "chargingStatus", "state")
        return STATUS_NAMES.get(value, value) if isinstance(value, str) else value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        data = self.coordinator.data or {}
        serial = data.get("wallbox_serial")
        if serial:
            attrs["wallbox_serial"] = serial
        source = data.get("wallbox_status_source")
        if source:
            attrs["data_source"] = source
        if wallbox_communication_missing(self.coordinator):
            attrs["Hinweis"] = (
                "Die Cloud hat geantwortet, liefert aber keinen aktuellen Wallboxstatus. "
                "Dies entspricht der Kommunikationsmeldung im AlphaESS-Webportal; "
                "vorhandene Energiezähler bestätigen keine aktive Verbindung."
            )
        allowed_keys = {
            "status", "chargingStatus", "state", "power", "chargingPower",
            "currentPower", "realPower", "mode", "chargeMode", "chargingMode",
            "strategy", "current", "voltage", "phase", "energy", "sessionEnergy",
            "chargingAmount", "lastChargingAmount", "gunIsLock", "startTime", "endTime",
            "faultCode",
        }
        for key in allowed_keys:
            value = self._status.get(key)
            if isinstance(value, (str, int, float, bool)):
                attrs[key] = value
        return attrs


class AlphaESSWallboxPowerSensor(AlphaESSWallboxEntity, SensorEntity):
    """Current charging power reported by the portal."""

    _attr_name = "Leistung"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "power")

    @property
    def native_value(self) -> float | None:
        status = (self.coordinator.data or {}).get("wallbox_status") or {}
        value = _first_value(status, "power", "chargingPower", "currentPower", "realPower")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None


class AlphaESSYesNoSensor(AlphaESSWallboxEntity, SensorEntity):
    """Human-readable yes/no state for connection and cable lock."""

    def __init__(
        self,
        coordinator: AlphaESSWallboxCoordinator,
        entry: ConfigEntry,
        name: str,
        unique_key: str,
    ) -> None:
        super().__init__(coordinator, entry, unique_key)
        self._attr_name = name
        self._kind = unique_key

    @property
    def native_value(self) -> str | None:
        status_data = (self.coordinator.data or {}).get("wallbox_status") or {}
        if not isinstance(status_data, dict):
            return None
        if self._kind == "vehicle_connected":
            status = status_data.get("status")
            if not isinstance(status, str) or not status or status in {
                "Disconnected", "Error", "Fault", "Upgrading",
            }:
                return None
            return "Nein" if status == "NotInsertedGun" else "Ja"
        value = status_data.get("gunIsLock")
        if isinstance(value, bool):
            return "Ja" if value else "Nein"
        return None


class AlphaESSWallboxEnergySensor(AlphaESSWallboxEntity, SensorEntity):
    """Energy value reported directly by the wallbox live-status endpoint."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(
        self,
        coordinator: AlphaESSWallboxCoordinator,
        entry: ConfigEntry,
        name: str,
        key: str,
        unique_key: str,
    ) -> None:
        super().__init__(coordinator, entry, unique_key)
        self._attr_name = name
        self._key = key
        self._last_energy_trace: tuple[str, str, str, float | None] | None = None

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        status = data.get("wallbox_status")
        if not isinstance(status, dict):
            return None
        value = self._energy_value(data, status)
        history = getattr(getattr(self.coordinator, "api", None), "history", None)
        if _LOGGER.isEnabledFor(logging.DEBUG) or (history and history.enabled):
            self._trace_energy(data, status, value, history)
        else:
            self._last_energy_trace = None
        return value

    def _energy_value(self, data: dict[str, Any], status: dict[str, Any]) -> float | None:
        # G2T omits zero energy counters, e.g. after midnight or at the start
        # of a new session. Both counters use the same guarded zero fallback.
        # Explicit null/invalid values, unknown profiles and failed reads remain unknown.
        if self._key in {"chargingAmount", "lastChargingAmount"} and self._key not in status:
            generation, _settings = settings_object(self.coordinator)
            if (
                generation == "g2T"
                and data.get("wallbox_status_source") == "real_status"
                and status.get("status") in _ENERGY_STATUS
                and getattr(self.coordinator, "last_update_success", True)
                and not getattr(self.coordinator, "_live_refresh_errors", 0)
                and not getattr(self.coordinator, "_full_consecutive_errors", 0)
            ):
                return 0.0
            return None
        value = status.get(self._key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _trace_energy(
        self, data: dict[str, Any], status: dict[str, Any], value: float | None, history
    ) -> None:
        """Log changes to the selected API field and its resulting sensor value."""
        raw = status.get(self._key)
        if self._key not in status:
            field = "missing"
        elif raw is None:
            field = "null"
        elif (number := _finite_energy(raw)) is None:
            field = "invalid"
        elif type(raw) in (int, float):
            field = f"number({raw!r})"
        else:
            field = f"numeric string({number!r})"

        source = data.get("wallbox_status_source")
        source = source if source in ("real_status", "system") else "unknown"
        raw_status = status.get("status")
        wallbox_status = (
            raw_status if isinstance(raw_status, str) and raw_status in STATUS_NAMES else "unknown"
        )
        trace = (source, wallbox_status, field, value)
        if trace != self._last_energy_trace:
            self._last_energy_trace = trace
            if history:
                history.record("bridge", event="energy_sensor", field=self._key,
                               sensor=type(self).__name__,
                               source=source, status=wallbox_status, input=field,
                               sensor_kwh=value)
            _LOGGER.debug(
                "Wallbox energy %s: source=%s status=%s api=%s sensor_kWh=%r",
                self._key, *trace,
            )

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {
            "Quelle": "Portal real-status: lastChargingAmount",
            "Hinweis": (
                "Energie der aktuellen oder letzten Ladesitzung; bleibt nach dem Abstecken zunächst erhalten. "
                "Beginnt bei einer neuen Sitzung erneut; auch nach Tageswechsel kann das Portal das Feld weglassen. "
                "Bei erfolgreicher G1T-/G2T-Live-Antwort mit normalem Status und fehlendem lastChargingAmount wird 0 angezeigt. "
                "Explizites null, Lesefehler und fehlender Status erhalten keinen Nullersatz. "
                "Kein dauerhaft gespeicherter letzter Ladevorgang über Tageswechsel hinweg."
            ),
        }


@dataclass
class LastChargeCheckpoint(ExtraStoredData):
    last_kwh: float | None
    session_kwh: float | None

    def as_dict(self) -> dict[str, Any]:
        return {"last_kwh": self.last_kwh, "session_kwh": self.session_kwh}


class AlphaESSWallboxLastChargeSensor(AlphaESSWallboxEnergySensor, RestoreEntity):
    """Retain the latest session energy as reported after charging stops."""

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Letzte Ladung", "lastChargingAmount", "last_completed_energy")
        self._last_kwh: float | None = None
        self._session_kwh: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if previous := await self.async_get_last_extra_data():
            saved = previous.as_dict()
            last = _finite_energy(saved.get("last_kwh"))
            session = _finite_energy(saved.get("session_kwh"))
            self._last_kwh = last if last and last > 0 else None
            self._session_kwh = session if session and session > 0 else None

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        return LastChargeCheckpoint(self._last_kwh, self._session_kwh)

    @property
    def native_value(self) -> float | None:
        if not isinstance((self.coordinator.data or {}).get("wallbox_status"), dict):
            return self._last_kwh
        return super().native_value

    def _energy_value(self, data: dict[str, Any], status: dict[str, Any]) -> float | None:
        if data.get("wallbox_status_source") != "real_status" or status.get("status") not in _ENERGY_STATUS:
            return self._last_kwh

        value = _finite_energy(status.get(self._key))
        if value is not None and value <= 0:
            value = None
        if status["status"] == "Charging":
            # The first reply for a new charge can still contain the previous value.
            if value is not None and (self._session_kwh is not None or value != self._last_kwh):
                self._session_kwh = value
        else:
            # The portal can deliver the final reading several minutes after power drops.
            self._last_kwh = value or self._session_kwh or self._last_kwh
            self._session_kwh = None
        return self._last_kwh

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "Quelle": "Portal real-status: lastChargingAmount, lokal gespeichert",
            "Aktuelle Ladung (kWh)": self._session_kwh,
        }


@dataclass
class DailyEnergyCheckpoint(ExtraStoredData):
    """Remember the last positive native value and its local day."""

    day: str
    kwh: float

    def as_dict(self) -> dict[str, Any]:
        return {"day": self.day, "kwh": self.kwh}


class AlphaESSWallboxDailyEnergySensor(AlphaESSWallboxEnergySensor, RestoreEntity):
    """Protect the G2T daily counter from spurious resets."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Heute geladen", "chargingAmount", "today_energy")
        self._checkpoint: DailyEnergyCheckpoint | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if previous := await self.async_get_last_extra_data():
            saved = previous.as_dict()
            day, kwh = saved.get("day"), saved.get("kwh")
            if isinstance(day, str) and type(kwh) in (int, float) and isfinite(kwh) and kwh > 0:
                self._checkpoint = DailyEnergyCheckpoint(day, kwh)

    @property
    def extra_restore_state_data(self) -> ExtraStoredData | None:
        return self._checkpoint

    def _energy_value(self, data: dict[str, Any], status: dict[str, Any]) -> float | None:
        generation, _ = settings_object(self.coordinator)
        if generation == "g1T":
            value = _finite_energy(status.get(self._key))
            if value is not None and value >= 0:
                return value
            return self._site_value(data)
        value = super()._energy_value(data, status)
        if value is None or not isfinite(value) or value < 0:
            return value
        if generation != "g2T":
            return value

        day = dt_util.now().date().isoformat()
        checkpoint = self._checkpoint
        if value == 0:
            if checkpoint is not None and checkpoint.day == day:
                return checkpoint.kwh
            self._checkpoint = None
        elif checkpoint is None or value != checkpoint.kwh:
            # An unchanged reading just after midnight can still be yesterday's
            # final reading. Do not let it suppress the incoming daily reset.
            self._checkpoint = DailyEnergyCheckpoint(day, value)
        return value

    @staticmethod
    def _site_value(data: dict[str, Any]) -> float | None:
        reading = data.get("site_daily_energy")
        if reading and reading[0] == dt_util.now().date().isoformat():
            return reading[1]
        return None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        generation, _ = settings_object(self.coordinator)
        if generation == "g1T":
            data = self.coordinator.data or {}
            status = data.get("wallbox_status")
            live = _finite_energy(status.get(self._key)) if isinstance(status, dict) else None
            source = "Wallbox-Status: chargingAmount"
            if live is None or live < 0:
                source = (
                    "Portal-Energiebilanz: evCharge.load"
                    if self._site_value(data) is not None else "Keine kWh-Daten"
                )
            return {"Quelle": source}
        return {
            "Quelle": "Portal real-status: chargingAmount",
            "Hinweis": (
                "Summe der heutigen Ladesitzungen. Bei einer gültigen Live-Antwort "
                "ohne Zählerfeld kann 0 angezeigt werden. Bei G2T bleibt ein bereits "
                "gelieferter Tageswert bei einem Nullsprung am selben Tag erhalten."
            ),
        }


class AlphaESSWallboxModeSensor(AlphaESSWallboxEntity, SensorEntity):
    """Configured charging mode; retained for compatibility with older versions."""

    _attr_name = "Lademodus"

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "mode")

    @property
    def native_value(self) -> str | None:
        generation, settings = settings_object(self.coordinator)
        modes = G2_MODES if generation == "g2T" else G1_MODES
        # In G2T schedule mode there is intentionally no global chargeMode;
        # every time period owns its own mode.
        if generation == "g2T" and settings.get("chargeStrategy") == 1:
            return "Zeitplanabhängig"
        value = settings.get("chargeMode")
        return next((name for name, mode in modes.items() if mode == value), None)


class AlphaESSWallboxGenerationSensor(AlphaESSWallboxEntity, SensorEntity):
    """Portal settings generation used by this wallbox."""

    _attr_translation_key = "portal_profile"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "portal_profile")

    @property
    def native_value(self) -> str | None:
        return settings_object(self.coordinator)[0]

    @property
    def entity_picture(self) -> str | None:
        """Show the image matching the detected portal profile."""
        generation = settings_object(self.coordinator)[0]
        image = {"g1T": "g1t.png", "g2T": "g2t.png"}.get(generation)
        return f"/api/{DOMAIN}/profiles/{image}" if image else None


class AlphaESSWallboxInformationSensor(AlphaESSWallboxEntity, SensorEntity):
    """One read-only item from the portal wallbox configuration."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: AlphaESSWallboxCoordinator,
        entry: ConfigEntry,
        name: str,
        key: str,
        unit: str | None = None,
    ) -> None:
        super().__init__(coordinator, entry, f"information_{key}")
        self._attr_name = name
        self._key = key
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self) -> str | int | float | None:
        return wallbox_object(self.coordinator).get(self._key)



class AlphaESSHardwarePhaseSensor(AlphaESSWallboxEntity, SensorEntity):
    """Hardware phase count reported by the portal, normalized to 1/2/3."""

    _attr_name = "Hardware-Phasen"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "information_phase")

    @property
    def native_value(self) -> int | None:
        value = wallbox_object(self.coordinator).get("phase")
        if isinstance(value, int) and value in {1, 2, 3}:
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            return {
                "one": 1,
                "single": 1,
                "1": 1,
                "two": 2,
                "2": 2,
                "three": 3,
                "3": 3,
            }.get(normalized)
        return None
