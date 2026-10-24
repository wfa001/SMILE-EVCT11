"""Read-only wallbox entities for AlphaESS Wallbox Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe NOTICE.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfElectricCurrent, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AlphaESSWallboxCoordinator
from .entity import (
    G1_MODES,
    G2_MODES,
    STATUS_NAMES,
    AlphaESSWallboxEntity,
    settings_object,
    wallbox_communication_missing,
    wallbox_object,
)


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
            AlphaESSWallboxPowerSensor(coordinator, entry),
            AlphaESSYesNoSensor(coordinator, entry, "Fahrzeug angeschlossen", "vehicle_connected"),
            AlphaESSYesNoSensor(coordinator, entry, "Ladestecker verriegelt", "gun_locked"),
            AlphaESSWallboxEnergySensor(coordinator, entry, "Heute geladen", "chargingAmount", "today_energy"),
            AlphaESSWallboxEnergySensor(coordinator, entry, "Aktueller / letzter Ladeabschnitt", "lastChargingAmount", "last_energy"),
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
            "Hinweis": "Verbindung zur AlphaESS-Portal-API, nicht Wallbox online/offline",
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
    """Energy value reported directly by the G2T live-status endpoint."""

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
        # Portal zero after midnight observed; aggregation across sessions still open.
        if key == "chargingAmount":
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        status = data.get("wallbox_status")
        if not isinstance(status, dict):
            return None
        # The G2T portal shows zero after midnight when a successful live reply
        # has a normal status but omits chargingAmount. Do not generalise this
        # to null/invalid fields, lastChargingAmount, G1T or failed reads.
        if self._key == "chargingAmount" and self._key not in status:
            generation, _settings = settings_object(self.coordinator)
            normal_states = {
                "NotInsertedGun", "PendingStart", "Charging", "ChargingStopped",
                "CharingStopped", "InsufficientPower", "WaitingForChargingPile",
            }
            if (
                generation == "g2T"
                and data.get("wallbox_status_source") == "real_status"
                and status.get("status") in normal_states
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

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        if self._key == "chargingAmount":
            return {
                "Quelle": "Portal real-status: chargingAmount",
                "Hinweis": (
                    "Portal-Anzeige nach Tageswechsel mit 0 bestätigt. Bei erfolgreicher G2T-Live-Antwort "
                    "mit normalem Status und fehlendem chargingAmount wird 0 angezeigt. Bei Lesefehlern "
                    "oder fehlendem Status wird keine 0 ergänzt. Mehrere Ladungen am selben Tag sind noch zu prüfen."
                ),
            }
        return {
            "Quelle": "Portal real-status: lastChargingAmount",
            "Hinweis": (
                "Energie des laufenden oder zuletzt abgeschlossenen Ladeabschnitts. "
                "Bei einer neuen Ladung beginnt der Wert erneut und kann zeitweise fehlen."
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
