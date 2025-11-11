from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
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

SETPOINT_STORE_KEY = "electrical_setpoint_W"
DEFAULT_SETPOINT_W = 0.0
MIN_SETPOINT_W = 0.0
MAX_SETPOINT_W = 20000.0  # 20 kW max
STEP_SETPOINT_W = 10.0  # device expects decawatt steps (10 W)


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
        update_before_add=True,
    )


class _ElectricalSetpointNumber(NumberEntity):
    _attr_has_entity_name = True
    _attr_name = "Electrical setpoint"
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_native_step = STEP_SETPOINT_W
    _attr_native_min_value = MIN_SETPOINT_W
    _attr_native_max_value = MAX_SETPOINT_W

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

        initial_w = float(store.get(SETPOINT_STORE_KEY, DEFAULT_SETPOINT_W))
        # Quantize to device step for a consistent starting value
        initial_w = int(round(initial_w / STEP_SETPOINT_W)) * STEP_SETPOINT_W
        self._attr_native_value = float(initial_w)

        # Cache register info for logging
        self._setpoint_spec = WRITE_REGS.get(
            "electrical_setpoint_W", {"ref": 8301, "fmt": "FIX-DAW"}
        )
        self._reg_addr = int(self._setpoint_spec.get("ref", 8301))

    @property
    def native_value(self) -> float:
        stored = self._store.get(SETPOINT_STORE_KEY, DEFAULT_SETPOINT_W)
        try:
            return float(stored)
        except (TypeError, ValueError):
            return DEFAULT_SETPOINT_W

    async def async_set_native_value(self, value_w: float) -> None:
        # 1) Clamp to allowed range
        vmin = self.native_min_value or MIN_SETPOINT_W
        vmax = self.native_max_value or MAX_SETPOINT_W
        clamped_w = max(vmin, min(vmax, value_w))

        # 2) Quantize to 10 W steps (raw = decawatt)
        raw = int(round(clamped_w / STEP_SETPOINT_W))  # decawatt
        quantized_w = raw * int(STEP_SETPOINT_W)

        # 3) Log exactly what we intend to send (both W and raw)
        _LOGGER.info(
            "Setpoint request: %.1f W → clamped %.1f W → quantized %.1f W (raw=%d decawatt) @ reg %s",
            value_w,
            clamped_w,
            float(quantized_w),
            raw,
            self._reg_addr,
        )

        try:
            # IMPORTANT:
            # Our DachsClient.write_register_key() expects a logical value in W
            # and will encode according to WRITE_REGS['electrical_setpoint_W']['fmt'].
            # We pass the QUANTIZED watts to ensure raw is an integer.
            await self.hass.async_add_executor_job(
                self._client.write_register_key,
                "electrical_setpoint_W",
                float(quantized_w),
            )
        except ValueError as err:
            raise HomeAssistantError(f"Invalid electrical setpoint: {err}") from err
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "Failed to write electrical setpoint %.1f W (raw=%d) to reg %s: %s",
                float(quantized_w),
                raw,
                self._reg_addr,
                err,
            )
            raise HomeAssistantError("Modbus write failed") from err

        # 4) Confirm what was sent (again, shows raw)
        _LOGGER.info(
            "Electrical setpoint written: %.1f W (raw=%d) → reg %s",
            float(quantized_w),
            raw,
            self._reg_addr,
        )

        # 5) Persist and update state
        self._store[SETPOINT_STORE_KEY] = float(quantized_w)
        self._attr_native_value = float(quantized_w)
        self.async_write_ha_state()
