from custom_components.bhkw.const_bhkw import (
    ALL_READ_KEYS_STR,
    FAST_KEYS_DEFAULT_STR,
    READ_REGS,
)


from typing import Any, List


def _sanitize_keys(raw: Any) -> list[str]:
    """Keep only keys that exist in READ_REGS/ALL_READ_KEYS_STR."""
    valid = set(ALL_READ_KEYS_STR or READ_REGS.keys())
    if isinstance(raw, (list, tuple)):
        return [str(k) for k in raw if str(k) in valid]
    return list(FAST_KEYS_DEFAULT_STR)


def _combine(regs: List[int], signed: bool) -> int:
    # big-endian word order
    b = bytearray()
    for r in regs:
        b.extend([(r >> 8) & 0xFF, r & 0xFF])
    return int.from_bytes(b, "big", signed=signed)


# ------------- small helpers -------------
def _as_int(val: Any, default: int) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return int(default)


def _scale(value: int, fmt: str) -> float | int:
    """
    Apply scaling based on fmt:
    - FIXn  -> divide by 10^n (supports FIX0..FIX9, with or without spaces)
    - TEMP  -> divide by 10 (°C with 0.1 resolution per Dachs PDFs)
    - DT/ENUM/RAW -> pass through
    """
    f = (fmt or "RAW").strip().upper()
    if f.startswith("FIX"):
        digits = "".join(ch for ch in f[3:] if ch.isdigit())
        p = int(digits) if digits else 0
        return value / (10**p)
    if f == "TEMP":
        return round(value / 10.0, 1)
    return value
