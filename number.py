from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode, NumberDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo

from .const_bhkw import (
    CONF_HOST,
    CONF_PORT,
    CONF_UNIT_ID,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    DOMAIN,
    make_device_info,
    WRITE_REGS,
)
from .coordinator import DachsClient  # <-- correct import

_LOGGER = logging.getLogger(__name__)

# interner Store-Schlüssel: wir speichern in **Watt**, UI zeigt **kW**
SETPOINT_STORE_KEY = "electrical_setpoint_W"

# Gerätegrenzen (W)
MIN_SETPOINT_W = 0.0
MAX_SETPOINT_W = 5.5  # 20 kW
STEP_W = 10.0  # 10 W Schritte
# abgeleitet für UI (kW)
MIN_KW = MIN_SETPOINT_W / 1000.0
MAX_KW = MAX_SETPOINT_W / 1000.0
STEP_KW = STEP_W / 1000.0

DEFAULT_SETPOINT_W = 0.0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    store = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    client: DachsClient | None = store.get("client")
    if client is None:
        _LOGGER.error(
            "Cannot set up number platform for %s because client is missing",
            entry.entry_id,
        )
        return

    data = {**entry.data, **entry.options}
    host = data.get(CONF_HOST)
    port = int(data.get(CONF_PORT, DEFAULT_PORT))
    unit_id = int(data.get(CONF_UNIT_ID, DEFAULT_UNIT_ID))
    device_info: DeviceInfo = make_device_info(entry.entry_id, host, port, unit_id)

    async_add_entities(
        [_ElectricalSetpointNumber(hass, entry, store, client, device_info)],
        update_before_add=False,
    )


class _ElectricalSetpointNumber(NumberEntity):
    """Setpoint in kW (UI), schreibt intern in W (raw)."""

    _attr_has_entity_name = True
    _attr_name = "Angeforderte elektrische Leistung"
    _attr_mode = NumberMode.BOX
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT  # UI in kW
    _attr_native_step = STEP_KW
    _attr_native_min_value = MIN_KW
    _attr_native_max_value = MAX_KW

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: dict[str, Any],
        client: DachsClient,
        device_info: DeviceInfo,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self._store = store
        self._client = client
        self._attr_device_info = device_info
        self._attr_unique_id = f"{DOMAIN}:{entry.entry_id}:electrical_setpoint"

        # initial aus Store (W) lesen → in kW darstellen
        initial_w = float(store.get(SETPOINT_STORE_KEY, DEFAULT_SETPOINT_W))
        initial_w = int(round(initial_w / STEP_W)) * STEP_W  # auf 10 W quantisieren
        self._attr_native_value = initial_w / 1000.0  # kW

        # nur für Logging
        spec = WRITE_REGS.get("electrical_setpoint_W", {"ref": 8301, "fmt": "FIX-W"})
        self._reg_addr = int(spec.get("ref", 8301))
        self._fmt = str(spec.get("fmt", "FIX-W"))

    @property
    def native_value(self) -> float:
        """UI-Wert in kW (aus Store in W umgerechnet)."""
        stored_w = self._store.get(SETPOINT_STORE_KEY, DEFAULT_SETPOINT_W)
        try:
            return float(stored_w) / 1000.0
        except (TypeError, ValueError):
            return DEFAULT_SETPOINT_W / 1000.0

    async def async_set_native_value(self, value_kw: float) -> None:
        """User setzt kW → clamp, quantize in **W**, dann schreiben."""
        # 1) in W umrechnen
        req_w = float(value_kw) * 1000.0

        # 2) auf Gerätegrenzen (in W) clampen
        clamped_w = max(MIN_SETPOINT_W, min(MAX_SETPOINT_W, req_w))

        # 3) auf 10 W quantisieren
        raw_w = int(round(clamped_w / STEP_W)) * int(STEP_W)  # ganzzahlig in W
        quantized_kw = raw_w / 1000.0

        _LOGGER.info(
            "Setpoint request: %.3f kW (%.1f W) → clamped %.3f kW (%.1f W) → "
            "quantized %.3f kW (raw=%d W) @ reg %s fmt=%s",
            value_kw,
            req_w,
            clamped_w / 1000.0,
            clamped_w,
            quantized_kw,
            raw_w,
            self._reg_addr,
            self._fmt,
        )

        try:
            # Client erwartet **logischen Wert in W**; Encoding übernimmt der Client gemäß fmt.
            await self.hass.async_add_executor_job(
                self._client.write_register_key,
                "electrical_setpoint_W",
                float(raw_w),  # <-- RAW IN W
            )
        except ValueError as err:
            raise HomeAssistantError(f"Invalid electrical setpoint: {err}") from err
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "Failed to write electrical setpoint %.3f kW (raw=%d W) to reg %s: %s",
                quantized_kw,
                raw_w,
                self._reg_addr,
                err,
            )
            raise HomeAssistantError("Modbus write failed") from err

        _LOGGER.info(
            "Electrical setpoint written: %.3f kW (raw=%d W) → reg %s",
            quantized_kw,
            raw_w,
            self._reg_addr,
        )

        # 4) Persistiere in **W** und aktualisiere UI (kW)
        self._store[SETPOINT_STORE_KEY] = float(raw_w)
        self._attr_native_value = quantized_kw
        self.async_write_ha_state()
