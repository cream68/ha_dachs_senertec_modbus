from __future__ import annotations

import logging
import time


from custom_components.bhkw.coordinator import (
    _DachsClient,
    DachsFastCoordinator,
    DachsSensor,
)
from custom_components.bhkw.descriptions import DESCRIPTIONS, DachsDesc
from custom_components.bhkw.helper.processing import (
    _sanitize_keys,
    _as_int,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const_bhkw import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_UNIT_ID,
    CONF_INTERVAL,
    UPDATE_INTERVAL,
    CONF_KEYS,
    FAST_KEYS_DEFAULT_STR,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    make_device_info,
    PLANT_STATUS_MAP,
)

_LOGGER = logging.getLogger(__name__)


# ------------- Entity descriptions (Dachs-focused) -------------
# ------------- Platform setup -------------
async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    data = {**entry.data, **entry.options}

    host = data.get(CONF_HOST)
    port = _as_int(data.get(CONF_PORT, DEFAULT_PORT), DEFAULT_PORT)
    unit_id = _as_int(data.get(CONF_UNIT_ID, DEFAULT_UNIT_ID), DEFAULT_UNIT_ID)
    interval = _as_int(data.get(CONF_INTERVAL, UPDATE_INTERVAL), UPDATE_INTERVAL)

    if not host:
        raise ValueError("Missing host in configuration")

    # Keys come as STRINGS; default is FAST_KEYS_DEFAULT_STR
    wanted_raw = data.get(CONF_KEYS, FAST_KEYS_DEFAULT_STR)
    keys = _sanitize_keys(wanted_raw)
    if not keys:
        _LOGGER.warning("No valid keys configured; using defaults.")
        keys = list(FAST_KEYS_DEFAULT_STR)

    # Create / store client & coordinator
    store = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    client = _DachsClient(host, port, unit_id)
    coordinator = DachsFastCoordinator(hass, client, keys, interval)

    device_info = make_device_info(entry.entry_id, host, port, unit_id)

    entities: list[DachsSensor] = []
    for key in keys:
        desc = DESCRIPTIONS.get(key, DachsDesc(key=key, name=key))
        entities.append(DachsSensor(coordinator, desc, device_info))

    # (optional improvement — non-blocking startup)
    async_add_entities(entities, update_before_add=False)
    hass.async_create_task(coordinator.async_refresh())
