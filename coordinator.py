from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from datetime import timedelta  # kept if HA references this elsewhere

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

from homeassistant.core import HomeAssistant  # kept for HA context
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const_bhkw import (
    DOMAIN,
    READ_REGS,
    ENUM_MAPS,  # <- mirror your utility
    CONF_GLT_PIN,  # if you wire PIN in via HA config
)

# If you prefer a fixed address:
ADDR_GLT_HEARTBEAT = 8300  # TODO: set to your PDF's GLT PIN write register

_LOGGER = logging.getLogger(__name__)

# ---- decoding helpers mirrored from your working script ----

SCALE_MAP: Dict[str, int] = {
    "FIX0": 1,
    "FIX1": 10,
    "FIX2": 100,
    "FIX3": 1000,
    "FIX4": 10000,
    "TEMP": 10,
}
SIGNED_TYPES = {"S16", "S32", "S64"}


def _combine_words(words: Sequence[int], signed: bool) -> int:
    value = 0
    for word in words:
        value = (value << 16) | (word & 0xFFFF)
    if signed:
        bits = len(words) * 16
        value = _twos_complement(value, bits)
    return value


def _twos_complement(value: int, bits: int) -> int:
    sign_bit = 1 << (bits - 1)
    mask = (1 << bits) - 1
    value &= mask
    if value & sign_bit:
        return value - (1 << bits)
    return value


def _decode_register(definition: Dict[str, Any], registers: Sequence[int]) -> Any:
    if not registers:
        raise ValueError(f"No data returned for register {definition['ref']}")

    reg_type = definition["type"]
    fmt = definition["fmt"]

    if fmt == "RAW":
        return list(registers)

    if len(registers) == 1:
        value = registers[0]
    else:
        value = _combine_words(registers, signed=reg_type in SIGNED_TYPES)

    if reg_type in SIGNED_TYPES and len(registers) == 1:
        value = _twos_complement(value, bits=16)

    if fmt == "ENUM":
        return value
    if fmt in SCALE_MAP:
        return value / SCALE_MAP[fmt]
    if fmt == "DT":
        # pass-through; caller can interpret as timestamp if desired
        return value

    return value


def _apply_enum_label(key: str, value: Any) -> Any:
    mapping = ENUM_MAPS.get(key)
    if not mapping:
        return value
    try:
        return {"raw": int(value), "label": mapping.get(int(value))}
    except Exception:
        return value


# ---- Modbus client using "fetch many" (one call per spec) ----


class SMAModbusClient:
    """Sync client used in HA executor, using 'fetch many' per key."""

    def __init__(
        self,
        host: str,
        port: int,
        unit_id: int,
        glt_pin: str | None = None,
        timeout: float = 5.0,
        polite_delay_s: float = 0.02,
    ) -> None:
        self._host = host
        self._port = port
        self._unit_id = unit_id
        self._timeout = timeout
        self._polite_delay_s = polite_delay_s
        self._client: ModbusTcpClient | None = None
        self._glt_pin = (glt_pin or "").strip()
        self._last_hb = 0.0
        self._hb_interval_s = 10.0  # throttle heartbeat to at most once each 10s

    # --- connection mgmt ---

    def _conn(self) -> ModbusTcpClient:
        if self._client is None:
            self._client = ModbusTcpClient(
                host=self._host,
                port=self._port,
                timeout=self._timeout,
            )
            if not self._client.connect():
                raise ConnectionError(f"Cannot connect to {self._host}:{self._port}")
        return self._client

    def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            finally:
                self._client = None

    # --- GLT heartbeat ---

    def _send_heartbeat(self) -> None:
        """Write the GLT PIN as heartbeat (FC=06). Safe/no-op if no PIN."""
        if not self._glt_pin or not self._glt_pin.isdigit():
            return
        now = time.monotonic()
        if now - self._last_hb < self._hb_interval_s:
            return  # throttle
        cli = self._conn()
        pin_val = int(self._glt_pin)
        rr = cli.write_register(
            address=ADDR_GLT_HEARTBEAT,
            value=pin_val,
            slave=self._unit_id,  # mirrors your working utility
        )
        # Don't raise on HB failures; just log and continue
        if rr and not rr.isError():
            self._last_hb = now
        else:
            _LOGGER.debug("Heartbeat write failed or not acknowledged: %s", rr)

    # --- fetch-many reads ---

    def _fetch_key(self, key: str) -> Any:
        """Read and decode one key using FC=4."""
        spec = READ_REGS[key]
        cli = self._conn()
        resp = cli.read_input_registers(
            address=spec["ref"],
            count=spec["cnt"],
            slave=self._unit_id,  # stays consistent with your working code
        )
        if not resp or resp.isError():
            raise ModbusException(
                f"FC4 read failed @{spec['ref']} len {spec['cnt']}: {resp}"
            )
        decoded = _decode_register(spec, resp.registers)
        return _apply_enum_label(key, decoded)

    def read_many(self, keys: List[str]) -> Dict[str, Any]:
        """
        Fetch many by iterating the requested keys.
        One FC=4 call per key (keeps logic identical to your proven utility).
        """
        # Heartbeat first (throttled)
        try:
            self._send_heartbeat()
        except Exception as hb_err:  # keep reads going even if HB fails
            _LOGGER.debug("Heartbeat error (ignored): %s", hb_err)

        out: Dict[str, Any] = {}
        for key in keys:
            try:
                out[key] = self._fetch_key(key)
            except Exception as exc:
                _LOGGER.debug("Key '%s' read failed: %s", key, exc)
                out[key] = None
            time.sleep(self._polite_delay_s)  # polite pacing between requests
        return out
