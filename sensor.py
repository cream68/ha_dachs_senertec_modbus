from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
    UpdateFailed,
)

from .coordinator import DachsClient
from .descriptions import DESCRIPTIONS, DachsDesc
from .helper.processing import _sanitize_keys, _as_int
from .const_bhkw import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_UNIT_ID,
    CONF_INTERVAL,
    UPDATE_INTERVAL,
    CONF_KEYS,  # use this for the “fast” set if you like
    FAST_KEYS_DEFAULT_STR,  # default list of keys
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    make_device_info,
    ENUM_MAPS,
)

_LOGGER = logging.getLogger(__name__)


# -------------------- Single coordinator (reads everything) --------------------
class DachsCoordinator(DataUpdateCoordinator[Dict[str, object]]):
    def __init__(
        self,
        hass: HomeAssistant,
        client: DachsClient,
        seconds: int,
    ) -> None:
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name="Dachs GLT",
            update_interval=timedelta(seconds=seconds),
        )
        self._client = client
        self._had_error = False

    async def _async_update_data(self) -> Dict[str, object]:
        """
        Fetch ALL data (fast + slow) from the single shared client in one cycle.
        Each group is attempted separately; if one fails we still keep the other.
        """

        def _read_all() -> Dict[str, object]:
            merged: Dict[str, object] = {}
            # try fast keys
            try:
                fast = self._client.get_fast_keys()
                if fast:
                    merged.update(fast)
            except Exception as e:
                _LOGGER.warning("Fast key read failed: %s", e)

            # try slow keys
            try:
                slow = self._client.get_slow_keys()
                if slow:
                    merged.update(slow)
            except Exception as e:
                _LOGGER.warning("Slow key read failed: %s", e)

            return merged

        try:
            data = await self.hass.async_add_executor_job(_read_all)
            if data:
                _LOGGER.debug("Dachs update OK: %s", data)
                if self._had_error:
                    _LOGGER.info("Dachs GLT data fetching recovered")
                    self._had_error = False
                return data

            # no data came back (both groups failed)
            self._had_error = True
            if self.data is not None:
                # keep last good data to avoid entities going unavailable
                return self.data
            raise UpdateFailed("No data from Dachs client")
        except Exception as err:  # truly catastrophic
            self._had_error = True
            _LOGGER.error("Dachs update failed: %s", err)
            if self.data is not None:
                return self.data
            raise UpdateFailed(str(err)) from err


# -------------------- Entity --------------------
class DachsSensor(CoordinatorEntity[DachsCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DachsCoordinator,
        description: DachsDesc,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._key = description.key
        self._attr_unique_id = f"dachs_{self._key}"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        val = data.get(self._key)

        # map enums to labels if available
        enum_map = ENUM_MAPS.get(self._key)
        if enum_map is not None and val is not None:
            try:
                return enum_map.get(int(val), f"Unbekannt ({val})")
            except (TypeError, ValueError):
                return f"Unbekannt ({val})"
        return val

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


# -------------------- Platform setup --------------------
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

    # Fast keys from config; default to FAST_KEYS_DEFAULT_STR
    wanted_fast_raw = data.get(CONF_KEYS, FAST_KEYS_DEFAULT_STR)
    fast_keys = _sanitize_keys(wanted_fast_raw)
    if not fast_keys:
        _LOGGER.warning("No valid fast keys configured; using defaults.")
        fast_keys = list(FAST_KEYS_DEFAULT_STR)

    # Optional: if you also want a slow group, put it in hass.data before setup
    # e.g., via options flow, or leave it empty. We’ll read both every cycle.
    store = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    slow_keys: List[str] = store.get("slow_keys", [])

    # single persistent client (created once and shared)
    client: DachsClient | None = store.get("client")
    if client is None:
        client = DachsClient(host, port, unit_id)
        store["client"] = client

    # program both key groups into the single client
    client.set_fast_keys(fast_keys)
    client.set_slow_keys(slow_keys)

    coordinator = DachsCoordinator(hass, client, interval)
    store["coordinator"] = coordinator

    device_info = make_device_info(entry.entry_id, host, port, unit_id)

    # Build entities for the union of both groups (duplicates removed)
    all_keys = list(dict.fromkeys([*fast_keys, *slow_keys]))
    entities: List[DachsSensor] = [
        DachsSensor(
            coordinator, DESCRIPTIONS.get(k, DachsDesc(key=k, name=k)), device_info
        )
        for k in all_keys
    ]

    # Non-blocking startup: add now, kick first refresh in background
    async_add_entities(entities, update_before_add=False)
    hass.async_create_task(coordinator.async_refresh())
