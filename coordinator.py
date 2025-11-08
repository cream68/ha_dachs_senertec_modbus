from __future__ import annotations

import time
from typing import Dict, List, Tuple
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from datetime import timedelta

from pymodbus.client import ModbusTcpClient

from .const import (
    DOMAIN,
    READ_REGS,  # <-- import your read map
    # If you keep a write map, you can import it and use WRITE_REGS["glt_pin"]["ref"]
    # WRITE_REGS,
    CONF_GLT_PIN,  # only needed when you wire the value into the client
)

# If you prefer a fixed address:
ADDR_GLT_HEARTBEAT = 8300  # <-- TODO: set to your PDF's GLT PIN write register

NO_MERGE_ADDRS = {8000, 8013, 8015, 8016, 8017}

_LOGGER = logging.getLogger(__name__)


def _group_blocks(
    regs_map: Dict[str, dict], subset: List[str]
) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int, str]] = []
    defined_addrs: set[int] = set()
    for k in subset:
        spec = regs_map[k]
        s = int(spec["ref"])
        e = s + int(spec["cnt"]) - 1
        spans.append((s, e, k))
        defined_addrs.update(range(s, e + 1))
    spans.sort(key=lambda x: x[0])

    out: List[Tuple[int, int]] = []
    cur_s: int | None = None
    cur_e: int | None = None

    def _flush():
        nonlocal cur_s, cur_e
        if cur_s is not None:
            out.append((cur_s, cur_e))
        cur_s = cur_e = None

    for s, e, k in spans:
        # Force no merge for these addresses (or any span touching them)
        if any(a in NO_MERGE_ADDRS for a in range(s, e + 1)):
            _flush()
            out.append((s, e))
            continue

        if cur_s is None:
            cur_s, cur_e = s, e
            continue

        # Only merge if exactly contiguous and no holes
        if s == cur_e + 1:
            candidate_addrs = set(range(cur_s, e + 1))
            if candidate_addrs.issubset(defined_addrs):
                cur_e = e
                continue

        _flush()
        cur_s, cur_e = s, e

    _flush()

    # Split into ≤50-register chunks
    MAX_BLOCK = 50
    chunked: List[Tuple[int, int]] = []
    for s, e in out:
        cur = s
        while cur <= e:
            out_e = min(cur + MAX_BLOCK - 1, e)
            chunked.append((cur, out_e))
            cur = out_e + 1
    return chunked


def _read_block(
    client: ModbusTcpClient, addr: int, cnt: int, unit_id: int
) -> List[int]:
    rr = client.read_input_registers(
        address=addr, count=cnt, slave=unit_id
    )  # ← use unit=
    if not rr or rr.isError():
        raise IOError(f"FC4 read failed @ {addr} len {cnt}: {rr}")
    return rr.registers


def _slice(cache: Dict[int, List[int]], addr: int, cnt: int):
    for s, data in cache.items():
        if s <= addr <= s + len(data) - cnt:
            i = addr - s
            return data[i : i + cnt]
    return None


def _combine(regs: List[int], signed: bool) -> int:
    b = bytearray()
    for r in regs:
        b.extend([(r >> 8) & 0xFF, r & 0xFF])
    return int.from_bytes(b, "big", signed=signed)


def _scale(value: int, fmt: str):
    f = (fmt or "RAW").strip().upper()
    if f.startswith("FIX"):
        digits = "".join(ch for ch in f[3:] if ch.isdigit())
        p = int(digits) if digits else 0
        return value / (10**p)
    if f == "TEMP":
        return round(value / 10.0, 1)
    return value


class SMAModbusClient:
    """Shared sync client used in HA executor to keep it simple & robust."""

    def __init__(
        self, host: str, port: int, unit_id: int, glt_pin: str | None = None
    ) -> None:
        self._host = host
        self._port = port
        self._unit_id = unit_id
        self._client: ModbusTcpClient | None = None
        self._glt_pin = (glt_pin or "").strip()
        self._last_hb = 0.0
        self._hb_interval_s = 10.0  # throttle heartbeat to at most once each 10s

    def _conn(self) -> ModbusTcpClient:
        if self._client is None:
            self._client = ModbusTcpClient(
                host=self._host, port=self._port, timeout=3.0
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
            address=ADDR_GLT_HEARTBEAT, value=pin_val, slave=self._unit_id
        )
        _LOGGER.info("Test")
        # Don't raise on HB failures; just log and continue
        if rr and not rr.isError():
            self._last_hb = now

    def read_many(self, keys: List[str]) -> Dict[str, object]:
        cli = self._conn()

        # 🔸 send GLT heartbeat BEFORE the reads (throttled)
        try:
            self._send_heartbeat()
        except Exception as e:
            # keep reads going even if HB fails (avoid crashing the coordinator)
            pass

        regs_map = READ_REGS
        blocks = _group_blocks(regs_map, keys)
        cache: Dict[int, List[int]] = {}

        for s, e in blocks:
            cnt = e - s + 1
            cache[s] = _read_block(cli, s, cnt, self._unit_id)
            time.sleep(0.02)  # polite pacing

        out: Dict[str, object] = {}
        for k in keys:
            spec = regs_map[k]
            start, cnt, dtype, fmt = spec["ref"], spec["cnt"], spec["type"], spec["fmt"]
            regs = _slice(cache, start, cnt)
            if regs is None:
                out[k] = None
                continue
            signed = dtype in ("S16", "S32")
            raw = _combine(regs, signed)
            # If you use N/A sentinels, call your _is_na here; else just scale
            out[k] = _scale(raw, fmt)
        return out
