from __future__ import annotations

import logging
import time
import socket
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Tuple, Final

from pymodbus.client import ModbusTcpClient

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
    UpdateFailed,
)

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_UNIT_ID,
    CONF_INTERVAL,
    UPDATE_INTERVAL,
    CONF_KEYS,  # ✅ use this instead of DEFAULT_KEYS
    READ_REGS,
    WRITE_REGS,  # not used here but fine to keep
    MANUFACTURER,
    INTEGRATION_NAME,
    FAST_KEYS_DEFAULT_STR,
    ALL_READ_KEYS_STR,  # ✅ for sanitizing keys
    DEFAULT_PORT,  # ✅ for safe fallback
    DEFAULT_UNIT_ID,  # ✅ for safe fallback
    make_device_info,
    PLANT_STATUS_MAP,
    ENUM_MAPS,
)

_LOGGER = logging.getLogger(__name__)

# at module level
NO_MERGE_KEYS = {
    "glt_version",
    "plant_status_enum",  # 8013 (example)
    "request_type_enum",  # 8015
    "runtime_since_last_start_h",  # 8016
    "last_shutdown_reason_enum",  # 8017
}


# ------------- small helpers -------------
def _as_int(val: Any, default: int) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return int(default)


def _sanitize_keys(raw: Any) -> list[str]:
    """Keep only keys that exist in READ_REGS/ALL_READ_KEYS_STR."""
    valid = set(ALL_READ_KEYS_STR or READ_REGS.keys())
    if isinstance(raw, (list, tuple)):
        return [str(k) for k in raw if str(k) in valid]
    return list(FAST_KEYS_DEFAULT_STR)


# ------------- Modbus helpers -------------
def _group_blocks(keys: list[str]) -> list[tuple[int, int]]:
    """Merge only truly contiguous *and* allowed ranges; force single reads for NO_MERGE_KEYS."""
    # Build explicit spans per key first
    spans: list[tuple[int, int, str]] = []
    for k in keys:
        spec = READ_REGS[k]
        s = spec["ref"]
        e = s + spec["cnt"] - 1
        # Force no-merge by making start=end for these keys (cnt=1 blocks)
        if k in NO_MERGE_KEYS:
            e = s  # ensure single-register read
        spans.append((s, e, k))
    # sort by start
    spans.sort(key=lambda x: x[0])

    merged: list[tuple[int, int]] = []
    cur_s: int | None = None
    cur_e: int | None = None
    for s, e, k in spans:
        if cur_s is None:
            cur_s, cur_e = s, e
            continue
        # only merge if strictly contiguous and the next start is exactly previous end + 1
        if s == (cur_e + 1):
            cur_e = e
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    if cur_s is not None:
        merged.append((cur_s, cur_e))

    # split into ≤50-register chunks
    out: list[tuple[int, int]] = []
    for s, e in merged:
        cur = s
        while cur <= e:
            out_e = min(cur + 50 - 1, e)
            out.append((cur, out_e))
            cur = out_e + 1
    return out


def _fc4_read(client: ModbusTcpClient, addr: int, cnt: int, dev_id: int) -> List[int]:
    _LOGGER.debug("FC4 → addr=%s count=%s unit=%s", addr, cnt, dev_id)
    rr = client.read_input_registers(address=addr, count=cnt, slave=dev_id)
    if not rr:
        _LOGGER.debug("FC4 ← None @ addr=%s", addr)
        raise IOError(f"FC4 read returned None @ {addr} len {cnt}")
    if rr.isError():
        _LOGGER.debug("FC4 ← ERROR %s @ addr=%s", rr, addr)
        raise IOError(f"FC4 read failed @ {addr} len {cnt}: {rr}")
    _LOGGER.debug("FC4 ← %s regs @ %s: %s", len(rr.registers), addr, rr.registers)
    return rr.registers


def _slice(cache: Dict[int, List[int]], addr: int, cnt: int) -> List[int] | None:
    for s, data in cache.items():
        if s <= addr <= s + len(data) - cnt:
            i = addr - s
            return data[i : i + cnt]
    return None


def _combine(regs: List[int], signed: bool) -> int:
    # big-endian word order
    b = bytearray()
    for r in regs:
        b.extend([(r >> 8) & 0xFF, r & 0xFF])
    return int.from_bytes(b, "big", signed=signed)


def _scale(value: int, fmt: str) -> float | int:
    """
    Apply scaling based on fmt:
    - FIXn  -> divide by 10^n (supports FIX0..FIX9, with or without spaces)
    - TEMP  -> divide by 10 (°C with 0.1 resolution per Dachs PDFs)
    - DT/ENUM/RAW -> pass through
    """
    f = (fmt or "RAW").strip().upper()  # normalize
    if f.startswith("FIX"):
        # accept FIX, FIX0, FIX 1, FIX01 etc.
        digits = "".join(ch for ch in f[3:] if ch.isdigit())
        p = int(digits) if digits else 0
        return value / (10**p)
    if f == "TEMP":
        return round(value / 10.0, 1)
    # DT/ENUM/RAW fall-through
    return value


# ------------- Lightweight sync client used in executor -------------
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
                host=self._host, port=self._port, timeout=3.0, retries=1
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
        """Write the GLT heartbeat PIN to its holding register."""
        reg = WRITE_REGS["glt_pin"]["ref"]
        cli = self._conn()
        rr = cli.write_register(address=reg, value=int(pin_value), slave=self._unit_id)
        if not rr or rr.isError():
            raise IOError(f"FC6 write failed @ {reg} val={pin_value}: {rr}")

    def read_keys(self, keys: List[str]) -> Dict[str, object]:
        """Read a set of Dachs READ_REGS keys efficiently via FC=04."""
        client = self._conn()
        cache: Dict[int, List[int]] = {}

        # Read merged blocks
        for s, e in _group_blocks(keys):
            cnt = e - s + 1
            try:
                cache[s] = _fc4_read(client, s, cnt, self._unit_id)
            except (OSError, socket.error) as net_err:
                # Try a single reconnect attempt
                _LOGGER.warning(
                    "Dachs GLT socket issue (%s). Reconnecting once…", net_err
                )
                try:
                    client.close()
                except Exception:
                    pass
                self._client = None
                client = self._conn()
                cache[s] = _fc4_read(client, s, cnt, self._unit_id)
            time.sleep(0.02)  # be polite to the GLT stack

        # Decode values
        out: Dict[str, object] = {}
        for k in keys:
            spec = READ_REGS[k]
            start, cnt, dtype, fmt = spec["ref"], spec["cnt"], spec["type"], spec["fmt"]
            regs = _slice(cache, start, cnt)
            if regs is None:
                out[k] = None
                continue
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
        try:
            return await self.hass.async_add_executor_job(
                self._client.read_keys, self._keys
            )
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err


# ------------- Entity descriptions (Dachs-focused) -------------
@dataclass(frozen=True)
class DachsDesc(SensorEntityDescription):
    key: str


DESCRIPTIONS: dict[str, DachsDesc] = {
    "plant_status_enum": DachsDesc(
        key="plant_status_enum",
        name="BHKW Status",
        icon="mdi:engine",
        device_class=SensorDeviceClass.ENUM,  # ✅ enum, not numeric
    ),
    "last_shutdown_reason_enum": DachsDesc(
        key="last_shutdown_reason_enum",
        name="Letzter Abschaltgrund",
        icon="mdi:engine",
        device_class=SensorDeviceClass.ENUM,  # ✅ enum, not numeric
    ),
    "request_type_enum": DachsDesc(
        key="request_type_enum",
        name="Letzte Anfrage",
        icon="mdi:engine",
        device_class=SensorDeviceClass.ENUM,  # ✅ enum, not numeric
    ),
    "electrical_power_kW": DachsDesc(
        key="electrical_power_kW",
        name="Elektrische Leistung",
        native_unit_of_measurement="kW",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "energy_el_total_kWh": DachsDesc(
        key="energy_el_total_kWh",
        name="Elektrische Energie gesamt",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "energy_th_total_kWh": DachsDesc(
        key="energy_th_total_kWh",
        name="Thermische Energie gesamt",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "temp_out_C": DachsDesc(
        key="temp_out_C",
        name="BHKW Vorlauf",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "temp_in_C": DachsDesc(
        key="temp_in_C",
        name="BHKW Rücklauf",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "outdoor_temp_C": DachsDesc(
        key="outdoor_temp_C",
        name="Außentemperatur",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "buffer_T1_C": DachsDesc(
        key="buffer_T1_C",
        name="Pufferspeichertemperatur 1",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "buffer_T2_C": DachsDesc(
        key="buffer_T2_C",
        name="Pufferspeichertemperatur 2",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "buffer_T3_C": DachsDesc(
        key="buffer_T3_C",
        name="Pufferspeichertemperatur 3",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "buffer_T4_C": DachsDesc(
        key="buffer_T4_C",
        name="Pufferspeichertemperatur 4",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "op_hours_total_h": DachsDesc(
        key="op_hours_total_h",
        name="Laufzeit",
        native_unit_of_measurement="h",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
}


# ------------- Platform setup -------------
async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    data = {**entry.data, **entry.options}

    host = data.get(CONF_HOST)
    port = _as_int(
        data.get(CONF_PORT, DEFAULT_PORT), DEFAULT_PORT
    )  # ✅ robust fallback
    unit_id = _as_int(
        data.get(CONF_UNIT_ID, DEFAULT_UNIT_ID), DEFAULT_UNIT_ID
    )  # ✅ robust fallback
    interval = _as_int(
        data.get(CONF_INTERVAL, UPDATE_INTERVAL), UPDATE_INTERVAL
    )  # ✅ robust fallback

    if not host:
        raise ValueError("Missing host in configuration")

    # Keys come as STRINGS; default is FAST_KEYS_DEFAULT_STR
    wanted_raw = data.get(CONF_KEYS, FAST_KEYS_DEFAULT_STR)  # ✅ use CONF_KEYS
    keys = _sanitize_keys(wanted_raw)
    if not keys:
        _LOGGER.warning("No valid keys configured; using defaults.")
        keys = list(FAST_KEYS_DEFAULT_STR)

    # Create / store client & coordinator
    store = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    client = _DachsClient(host, port, unit_id)
    coordinator = DachsFastCoordinator(hass, client, keys, interval)

    await coordinator.async_refresh()
    store["client"] = client
    store["coordinator"] = coordinator

    device_info = make_device_info(entry.entry_id, host, port, unit_id)

    entities: list[DachsSensor] = []
    for key in keys:
        desc = DESCRIPTIONS.get(key, DachsDesc(key=key, name=key))
        entities.append(DachsSensor(coordinator, desc, device_info))

    async_add_entities(entities, update_before_add=True)


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
