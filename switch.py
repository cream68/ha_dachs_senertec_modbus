from __future__ import annotations

from typing import Any
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

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

    # Per-Entry-Store + Default-Zustand
    store = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    store.setdefault("hb_enabled", True)

    device_info: DeviceInfo = make_device_info(entry.entry_id, host, port, unit_id)
    async_add_entities(
        [_NoopHeartbeatSwitch(hass, entry, device_info)], update_before_add=False
    )


class _NoopHeartbeatSwitch(SwitchEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "GLT Heartbeat"

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, device_info: DeviceInfo
    ):
        self.hass = hass
        self.entry = entry
        self._attr_device_info = device_info
        # pro Entry eindeutig
        self._attr_unique_id = f"{entry.entry_id}_dachs_glt_heartbeat"

    async def async_added_to_hass(self) -> None:
        """Vorherigen Zustand nach HA-Neustart wiederherstellen."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            restored = last.state == "on"
            store = self.hass.data[DOMAIN][self.entry.entry_id]
            if store.get("hb_enabled", True) != restored:
                store["hb_enabled"] = restored
                _LOGGER.info("Heartbeat restored to %s", "on" if restored else "off")
        # direkt UI-Status schreiben
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
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
