from __future__ import annotations
import logging
import time
from datetime import datetime
from pymodbus.client import ModbusTcpClient

_LOGGER = logging.getLogger(__name__)

ADDR_GLT_HEARTBEAT = 8300  # laut Dachs-Doku


def _log_hb(host: str, unit: int, pin: int, ok: bool, err: Exception | None = None):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if ok:
        _LOGGER.info(
            "[%s] ✅ GLT heartbeat ok — host=%s slave=%s pin=%s", ts, host, unit, pin
        )
    else:
        _LOGGER.error(
            "[%s] ❌ GLT heartbeat fail — host=%s slave=%s pin=%s%s",
            ts,
            host,
            unit,
            pin,
            f" err={err}" if err else "",
        )


class DachsClient:
    """Schlanker, persistenter Modbus-TCP Client für Dachs GLT."""

    def __init__(self, host: str, port: int, unit_id: int) -> None:
        self._host = host
        self._port = port
        self._unit = unit_id
        self._cli: ModbusTcpClient | None = None

    def _conn(self) -> ModbusTcpClient:
        if self._cli is None:
            cli = ModbusTcpClient(
                host=self._host, port=self._port, timeout=3.0, retries=1
            )
            if not cli.connect():
                raise ConnectionError(f"Cannot connect to {self._host}:{self._port}")
            self._cli = cli
        return self._cli

    def close(self) -> None:
        if self._cli:
            try:
                self._cli.close()
            finally:
                self._cli = None

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
