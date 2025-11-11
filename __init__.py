from __future__ import annotations
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const_bhkw import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_UNIT_ID,
    CONF_GLT_PIN,
    DEFAULT_GLT_PIN,
    CONF_GLT_HEARTBEAT_INTERVAL,
    DEFAULT_GLT_HEARTBEAT_INTERVAL,
)
from custom_components.bhkw.coordinator import DachsClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor", "switch", "button", "number"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dachs from a config entry."""
    data = {**entry.data, **entry.options}

    host: str = data.get(CONF_HOST)
    port: int = int(data.get(CONF_PORT))
    unit: int = int(data.get(CONF_UNIT_ID))
    pin: str = str(data.get(CONF_GLT_PIN, DEFAULT_GLT_PIN)).strip()
    hb_every_s: int = int(
        data.get(CONF_GLT_HEARTBEAT_INTERVAL, DEFAULT_GLT_HEARTBEAT_INTERVAL)
    )

    store = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    store["hb_enabled"] = True
    store["glt_pin"] = pin

    client = DachsClient(host, port, unit)
    store["client"] = client

    async def _heartbeat_cb(_now) -> None:
        domain_store = hass.data.get(DOMAIN, {})
        store_entry = domain_store.get(entry.entry_id)
        if not store_entry:
            _LOGGER.debug(
                "No store for entry %s; skipping GLT heartbeat", entry.entry_id
            )
            return

        if not store_entry.get("hb_enabled", True):
            _LOGGER.debug("GLT heartbeat disabled; skipping scheduled run")
            return

        pin_str = str(store_entry.get("glt_pin", "")).strip()
        if not pin_str:
            _LOGGER.info("Skipping GLT heartbeat because no PIN is configured")
            return
        if not pin_str.isdigit():
            _LOGGER.warning(
                "Skipping GLT heartbeat because PIN '%s' is not numeric", pin_str
            )
            return

        try:
            pin_int = int(pin_str, 10)
        except ValueError as err:
            _LOGGER.warning("Skipping GLT heartbeat: %s", err)
            return

        try:
            await hass.async_add_executor_job(client.heartbeat, pin_int)
            _LOGGER.info("Scheduled GLT heartbeat sent (PIN=%s)", pin_str)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Scheduled GLT heartbeat failed: %s", err)

    # schedule heartbeat using configured interval
    unsub_hb = async_track_time_interval(
        hass, _heartbeat_cb, timedelta(seconds=hb_every_s)
    )
    entry.async_on_unload(unsub_hb)
    entry.async_on_unload(client.close)

    # reload platforms when options change
    entry.async_on_unload(entry.add_update_listener(_options_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates by fully reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)
