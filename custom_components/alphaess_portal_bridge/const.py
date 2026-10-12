"""Constants for the AlphaESS Portal Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe NOTICE.md im Paket.
# ---------------------------------------------------------------------------

DOMAIN = "alphaess_portal_bridge"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SYSTEM_SERIAL = "system_serial"
CONF_WALLBOX_SERIAL = "wallbox_serial"
CONF_UPDATE_INTERVAL = "update_interval_seconds"
DEFAULT_UPDATE_INTERVAL_SECONDS = 30
DEFAULT_G2T_UPDATE_INTERVAL_SECONDS = 30
UPDATE_INTERVAL_MIN_SECONDS = 30
UPDATE_INTERVAL_MAX_SECONDS = 300
UPDATE_INTERVAL_STEP_SECONDS = 30
UPDATE_INTERVAL_OPTIONS = tuple(
    range(
        UPDATE_INTERVAL_MIN_SECONDS,
        UPDATE_INTERVAL_MAX_SECONDS + 1,
        UPDATE_INTERVAL_STEP_SECONDS,
    )
)
PLATFORM_URL = "https://platform.alphaess.com"
API_URL = f"{PLATFORM_URL}/api"
