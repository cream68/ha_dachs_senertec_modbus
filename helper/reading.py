from pymodbus.client import ModbusTcpClient

import logging
from typing import List

_LOGGER = logging.getLogger(__name__)


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
