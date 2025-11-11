# custom_components/bhkw/client.py
from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Dict, Iterable, List, Optional

from pymodbus.client import ModbusTcpClient

from .const_bhkw import READ_REGS, WRITE_REGS
from .helper.reading import _fc4_read
from .helper.processing import _combine, _scale, _encode_for_write

__all__ = ["DachsClient"]

_LOGGER = logging.getLogger(__name__)

# GLT heartbeat register (FC=06)
_GLT_PIN_REG = WRITE_REGS["glt_pin"]["ref"]

# Retry/backoff for transient socket drops
_RETRY_ATTEMPTS = 3
_RETRY_BASE_SLEEP = 0.05  # seconds
_PER_KEY_PAUSE = 0.02  # seconds between successive reads (be gentle)


class DachsClient:
    """
    One persistent Modbus-TCP client for the Dachs GLT.

    - Reads use FC=04 (input registers) per GLT spec.
    - Writes use FC=06 (single holding register) for PIN / setpoints.
    - A single TCP connection is shared for all operations (guarded by a lock).
    - On reconnect, the last-known heartbeat PIN is sent again automatically.

    Public API:
      set_fast_keys(keys)
      set_slow_keys(keys)
      get_fast_keys() -> dict
      get_slow_keys() -> dict
      heartbeat(pin: Optional[int] = None) -> None
      write_register_key(key: str, logical_value: float | int) -> None
      close() -> None
    """

    def __init__(
        self,
        host: str,
        port: int,
        unit_id: int,
        *,
        fast_keys: Optional[Iterable[str]] = None,
        slow_keys: Optional[Iterable[str]] = None,
        timeout: float = 5.0,
        retries: int = 1,
        initial_pin: Optional[int] = None,
    ) -> None:
        self._host = host
        self._port = int(port)
        self._unit_id = int(unit_id)
        self._timeout = float(timeout)
        self._retries = int(retries)

        self._client: Optional[ModbusTcpClient] = None
        self._lock = threading.RLock()

        self._fast_keys = list(fast_keys or [])
        self._slow_keys = list(slow_keys or [])
        self._pin: Optional[int] = int(initial_pin) if initial_pin is not None else None

    # ---------------------- connection helpers ----------------------

    def _conn(self) -> ModbusTcpClient:
        """Ensure a connected Modbus client and return it."""
        if self._client is None:
            cli = ModbusTcpClient(
                host=self._host,
                port=self._port,
                timeout=self._timeout,
                retries=self._retries,
            )
            if not cli.connect():
                raise ConnectionError(f"Cannot connect to {self._host}:{self._port}")
            self._client = cli
            _LOGGER.debug("Modbus TCP connected to %s:%s", self._host, self._port)
            if self._pin is not None:
                try:
                    self._write_register(address=_GLT_PIN_REG, value=int(self._pin))
                    _LOGGER.info(
                        "Re-sent GLT heartbeat after connect (PIN=%s)", self._pin
                    )
                except Exception as err:
                    _LOGGER.warning("Heartbeat after connect failed: %s", err)
        return self._client

    def _reconnect_and_reheart(self) -> ModbusTcpClient:
        """Reconnect the socket and, if known, re-send the GLT heartbeat PIN."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            finally:
                self._client = None

        cli = self._conn()

        if self._pin is not None:
            try:
                self._write_register(address=_GLT_PIN_REG, value=int(self._pin))
                _LOGGER.info(
                    "Re-sent GLT heartbeat after reconnect (PIN=%s)", self._pin
                )
            except Exception as err:
                _LOGGER.warning("Heartbeat after reconnect failed: %s", err)
        return cli

    # ---------------------- low-level read/write ----------------------

    def _write_register(self, *, address: int, value: int | str):
        """
        FC=06 write with unit/slave compatibility and response validation.
        Accepts int-like strings; validates Modbus response.
        """
        cli = self._conn()
        v = int(value)

        try:
            _LOGGER.debug(
                "Writing %s to address %s (unit=%s)", v, address, self._unit_id
            )
            rr = cli.write_register(address=address, value=v, unit=self._unit_id)
        except TypeError:
            # Older pymodbus versions use 'slave' instead of 'unit'
            _LOGGER.debug(
                "Writing %s to address %s (slave=%s)", v, address, self._unit_id
            )
            rr = cli.write_register(address=address, value=v, slave=self._unit_id)

        if not rr:
            raise IOError(f"No response writing @{address}")
        if rr.isError():
            raise IOError(f"FC6 write failed @{address}: {rr}")
        return rr

    def _read_keys_once(
        self, cli: ModbusTcpClient, keys: List[str]
    ) -> Dict[str, object]:
        """One pass of FC=04 key reads (no reconnect here)."""
        out: Dict[str, object] = {}
        for key in keys:
            spec = READ_REGS[key]
            addr, cnt, dtype, fmt = spec["ref"], spec["cnt"], spec["type"], spec["fmt"]

            regs = _fc4_read(cli, addr, cnt, self._unit_id)  # raises on error
            signed = dtype in ("S16", "S32")
            raw = _combine(regs, signed)
            out[key] = _scale(raw, fmt)

            time.sleep(_PER_KEY_PAUSE)
        return out

    def _read_keys(self, keys: List[str]) -> Dict[str, object]:
        """
        Read keys with retry + reconnect. If reconnect happens, we re-heartbeat first.
        Entire operation is serialized by a lock so reads/writes never collide.
        """
        if not keys:
            return {}

        with self._lock:
            cli = self._conn()
            attempt = 0
            while True:
                try:
                    return self._read_keys_once(cli, keys)
                except (OSError, socket.error, IOError) as err:
                    attempt += 1
                    if attempt > _RETRY_ATTEMPTS:
                        _LOGGER.error(
                            "Read keys failed after %s attempts: %s",
                            _RETRY_ATTEMPTS,
                            err,
                        )
                        raise
                    _LOGGER.warning(
                        "Socket/read issue (%s). Reconnecting (try %s/%s)…",
                        err,
                        attempt,
                        _RETRY_ATTEMPTS,
                    )
                    cli = self._reconnect_and_reheart()
                    time.sleep(_RETRY_BASE_SLEEP * attempt * attempt)

    # ------------------------- public API -------------------------

    def set_fast_keys(self, keys: Iterable[str]) -> None:
        self._fast_keys = list(keys or [])

    def set_slow_keys(self, keys: Iterable[str]) -> None:
        self._slow_keys = list(keys or [])

    def get_fast_keys(self) -> Dict[str, object]:
        """Read the configured 'fast' keys through the persistent connection."""
        return self._read_keys(self._fast_keys)

    def get_slow_keys(self) -> Dict[str, object]:
        """Read the configured 'slow' keys through the persistent connection."""
        return self._read_keys(self._slow_keys)

    def heartbeat(self, pin: Optional[int] = None) -> None:
        """
        Send/refresh the GLT heartbeat (FC=06). If 'pin' is provided, remember it and
        use it after future reconnects. Serialized via the same lock as reads.
        """
        with self._lock:
            if pin is not None:
                self._pin = int(pin)

            if self._pin is None:
                raise ValueError("GLT PIN not set for heartbeat()")

            try:
                self._write_register(address=_GLT_PIN_REG, value=int(self._pin))
                _LOGGER.info("GLT heartbeat sent (PIN=%s)", self._pin)
            except (OSError, socket.error, IOError) as err:
                _LOGGER.warning("Heartbeat failed (%s). Reconnecting + retry…", err)
                self._reconnect_and_reheart()
                self._write_register(address=_GLT_PIN_REG, value=int(self._pin))
                _LOGGER.info("GLT heartbeat sent after reconnect (PIN=%s)", self._pin)

    def write_register_key(self, key: str, logical_value: float | int) -> None:
        """
        Generic FC=06 writer using WRITE_REGS spec and _encode_for_write().
        Example: electrical setpoint in W -> encodes to decawatt etc. per 'fmt'.
        Retries once after reconnect + re-heartbeat on socket error.
        """
        spec = WRITE_REGS[key]
        raw_value = _encode_for_write(logical_value, spec["fmt"])

        with self._lock:
            try:
                self._write_register(address=spec["ref"], value=raw_value)
            except (OSError, socket.error, IOError):
                self._reconnect_and_reheart()
                self._write_register(address=spec["ref"], value=raw_value)

    def close(self) -> None:
        """Close the TCP socket (e.g., on HA unload)."""
        with self._lock:
            if self._client:
                try:
                    self._client.close()
                except Exception:
                    pass
                finally:
                    self._client = None
