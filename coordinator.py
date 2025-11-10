# ------------- Lightweight sync client (per-key reads) -------------
from datetime import timedelta
from custom_components.bhkw.const_bhkw import ENUM_MAPS, READ_REGS
from custom_components.bhkw.descriptions import DachsDesc
from custom_components.bhkw.helper.processing import _combine, _scale
from custom_components.bhkw.helper.reading import _fc4_read
import logging


from pymodbus.client import ModbusTcpClient


import socket
from typing import Any, Dict, List

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from custom_components.bhkw.const_bhkw import WRITE_REGS

_LOGGER = logging.getLogger(__name__)


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

     def write_glt_pin(self, pin_value: int) -> None:
        """Heartbeat: schreibe GLT-PIN (FC=06) an 0x8300."""
        cli = self._conn()
        rr = cli.write_register(
            address=ADDR_GLT_HEARTBEAT, value=int(pin_value), slave=self._unit
        )
        if rr and not rr.isError():
            _log_hb(self._host, self._unit, int(pin_value), True)
        else:
            _log_hb(self._host, self._unit, int(pin_value), False, Exception(str(rr)))


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

    def write_glt_pin(self, pin_value: int) -> None:
        """Heartbeat: schreibe GLT-PIN (FC=06) an 0x8300."""
        ADDR_GLT_HEARTBEAT = WRITE_REGS["glt_pin"]
        cli = self._conn()
        rr = cli.write_register(
            address=ADDR_GLT_HEARTBEAT, value=int(pin_value), slave=self._unit
        )
        if rr and not rr.isError():
            _LOGGER.info(
                "✅ GLT heartbeat ok — host=%s slave=%s pin=%s",
                self.host,
                self.unit,
                self.pin,
            )
        else:
            _LOGGER.error(
                "❌ GLT heartbeat fail — host=%s slave=%s pin=%s",
                self.host,
                self.unit,
                self.pin,
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
