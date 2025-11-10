from __future__ import annotations

import logging
import time
import socket
from datetime import timedelta
from typing import Any, Dict, List

from pymodbus.client import ModbusTcpClient

from custom_components.bhkw.descriptions import DESCRIPTIONS, DachsDesc
from custom_components.bhkw.helper.processing import (
    _sanitize_keys,
    _combine,
    _as_int,
    _scale,
)
from custom_components.bhkw.helper.reading import _fc4_read
from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
    UpdateFailed,
)

from .const_bhkw import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_UNIT_ID,
    CONF_INTERVAL,
    UPDATE_INTERVAL,
    CONF_KEYS,
    READ_REGS,
    FAST_KEYS_DEFAULT_STR,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    make_device_info,
    PLANT_STATUS_MAP,
    ENUM_MAPS,
)

_LOGGER = logging.getLogger(__name__)


# ------------- Lightweight sync client (per-key reads) -------------
class _DachsClient:
    """Simple persistent Modbus-TCP client tailored for Dachs GLT (FC=04)."""

    def __init__(self, host: str, port: int, unit_id: int) -> None:
        self._host = host
        self._port = port
        self._unit_id = unit_id
        self._client: ModbusTcpClient | None = None

    def _conn(self) -> ModbusTcpClient:
        if self._client is None:
            cli = ModbusTcpClient(
                host=self._host, port=self._port, timeout=5.0, retries=1
            )
            if not cli.connect():
                raise ConnectionError(f"Cannot connect to {self._host}:{self._port}")
            self._client = cli
        return self._client

    def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            finally:
                self._client = None

    def read_keys(self, keys: List[str]) -> Dict[str, object]:
        """Read a set of Dachs READ_REGS keys using *individual* FC=04 requests."""
        client = self._conn()
        out: Dict[str, object] = {}

        for k in keys:
            spec = READ_REGS[k]
            start, cnt, dtype, fmt = spec["ref"], spec["cnt"], spec["type"], spec["fmt"]

            try:
                regs = _fc4_read(client, start, cnt, self._unit_id)
            except (OSError, socket.error) as net_err:
                # single reconnect attempt per key
                _LOGGER.warning(
                    "Dachs GLT socket issue (%s). Reconnecting once…", net_err
                )
                try:
                    client.close()
                except Exception:
                    pass
                self._client = None
                client = self._conn()
                regs = _fc4_read(client, start, cnt, self._unit_id)

            signed = dtype in ("S16", "S32")
            raw = _combine(regs, signed)
            out[k] = _scale(raw, fmt)

        return out


# ------------- Coordinator -------------
class DachsFastCoordinator(DataUpdateCoordinator[Dict[str, object]]):
    def __init__(
        self, hass: HomeAssistant, client: _DachsClient, keys: List[str], seconds: int
    ) -> None:
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name="Dachs GLT Fast",
            update_interval=timedelta(seconds=seconds),
        )
        self._client = client
        self._keys = keys

    async def _async_update_data(self) -> Dict[str, object]:
        """Fetch new data from the Dachs GLT via Modbus."""
        try:
            data = await self.hass.async_add_executor_job(
                self._client.read_keys, self._keys
            )

            # 🔹 Log the entire data dict for debugging / timing visibility
            _LOGGER.debug("Dachs update OK: %s", data)

            return data

        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Dachs update failed: %s", err)
            raise UpdateFailed(str(err)) from err


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

    hass.async_create_task(coordinator.async_refresh())


# ------------- Entity -------------
class DachsSensor(CoordinatorEntity[DachsFastCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DachsFastCoordinator,
        description: DachsDesc,
        device_info: DeviceInfo,
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        SensorEntity.__init__(self)
        self.entity_description = description
        self._key = description.key
        self._attr_unique_id = f"dachs_{self._key}"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        val = data.get(self._key)

        # Generic enum -> label mapping
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
