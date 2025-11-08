from __future__ import annotations
import logging
from typing import Any
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from .const import (
    DOMAIN,
    make_device_info,
    CONF_HOST,
    CONF_PORT,
    CONF_UNIT_ID,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    store = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    data = {**entry.data, **entry.options}
    host = data.get(CONF_HOST)
    port = int(data.get(CONF_PORT, DEFAULT_PORT))
    unit_id = int(data.get(CONF_UNIT_ID, DEFAULT_UNIT_ID))
    device_info: DeviceInfo = make_device_info(entry.entry_id, host, port, unit_id)
    async_add_entities(
        [_HeartbeatNowButton(hass, entry, device_info)], update_before_add=True
    )


class _HeartbeatNowButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Send GLT Heartbeat now"

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo
    ) -> None:
        self.hass = hass
        self.entry = entry
        self._attr_device_info = device_info
        self._attr_unique_id = f"{DOMAIN}:{entry.entry_id}:heartbeat_now"

    async def async_press(self) -> None:
        store = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        client = store.get("client")
        pin = (store.get("glt_pin") or "").strip()
        if not client or not pin:
            _LOGGER.warning("GLT heartbeat client or PIN not available")
            return
        try:
            await self.hass.async_add_executor_job(client.write_glt_pin, int(pin))
            _LOGGER.info("✅ Manual GLT heartbeat sent (PIN=%s)", pin)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("❌ Manual GLT heartbeat failed: %s", err)
