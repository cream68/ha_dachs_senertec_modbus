from __future__ import annotations

from typing import Any
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

import logging

from .const_bhkw import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_UNIT_ID,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    make_device_info,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    data = {**entry.data, **entry.options}
    host = data.get(CONF_HOST)
    port = int(data.get(CONF_PORT, DEFAULT_PORT))
    unit_id = int(data.get(CONF_UNIT_ID, DEFAULT_UNIT_ID))

    # Ensure per-entry store exists (and a default heartbeat flag)
    store = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    store.setdefault("hb_enabled", True)

    device_info: DeviceInfo = make_device_info(entry.entry_id, host, port, unit_id)
    async_add_entities([_NoopHeartbeatSwitch(hass, entry, device_info)], True)


class _NoopHeartbeatSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = "GLT Heartbeat"
    _attr_unique_id = "dachs_glt_heartbeat"

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo
    ):
        self.hass = hass
        self.entry = entry
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool:
        # simple in-memory flag
        store = self.hass.data[DOMAIN][self.entry.entry_id]
        return bool(store.get("hb_enabled", True))

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hass.data[DOMAIN][self.entry.entry_id]["hb_enabled"] = True
        _LOGGER.info("Heartbeat turned on")
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hass.data[DOMAIN][self.entry.entry_id]["hb_enabled"] = False
        _LOGGER.info("Heartbeat turned off")
        self.async_write_ha_state()
