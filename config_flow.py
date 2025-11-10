# config_flow.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import (
    config_validation as cv,
    selector as sel,  # ← Klassen-Selectoren (sicher für voluptuous_serialize)
)

from .const_bhkw import (
    ALL_READ_KEYS_STR,  # list[str]
    CONF_GLT_HEARTBEAT_INTERVAL,
    # GLT Heartbeat
    CONF_GLT_PIN,
    # Netzwerk/Identität
    CONF_HOST,
    # NEW: Sensor-Optionen
    # Polling / Keys
    CONF_INTERVAL,
    CONF_KEYS,
    CONF_PORT,
    CONF_UNIT_ID,
    DEFAULT_GLT_HEARTBEAT_INTERVAL,
    DEFAULT_GLT_PIN,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    DOMAIN,
    FAST_KEYS_DEFAULT_STR,  # list[str]
    UPDATE_INTERVAL,
)

assert hasattr(sel, "SelectSelector") and hasattr(sel, "SelectSelectorConfig")
# ---------- Selector (nur Klassen, keine Roh-Dicts!) ----------

unit_id_selector = sel.NumberSelector(
    sel.NumberSelectorConfig(
        min=0,
        max=255,
        step=1,
        mode=sel.NumberSelectorMode.BOX,  # Eingabebox statt Slider
    )
)

# inside_temps_selector = sel.EntitySelector(
#     sel.EntitySelectorConfig(
#         multiple=True,
#         filter=[{"domain": "sensor", "device_class": "temperature"}],
#     )
# )

# outside_temp_selector = sel.EntitySelector(
#     sel.EntitySelectorConfig(
#         multiple=False,
#         filter=[{"domain": "sensor", "device_class": "temperature"}],
#     )
# )

# accuweather_selector = sel.EntitySelector(
#     sel.EntitySelectorConfig(
#         multiple=False,
#         filter=[{"domain": "weather"}],
#     )
# )

# ---------- Helpers (strings only, no Enums!) ----------


def _select_options() -> List[dict[str, str]]:
    """Options für den SelectSelector: ausschließlich Strings."""
    return [{"label": k, "value": k} for k in list(ALL_READ_KEYS_STR)]


def _sanitize_default_keys(source: Dict[str, Any] | None) -> List[str]:
    """Stelle sicher, dass nur gültige Keys in den Defaults landen.
    Akzeptiert den gespeicherten Wert (source[CONF_KEYS]) oder fällt auf FAST_KEYS_DEFAULT_STR zurück.
    """
    raw = (
        list(FAST_KEYS_DEFAULT_STR)
        if source is None
        else list(source.get(CONF_KEYS, FAST_KEYS_DEFAULT_STR))
    )
    valid = {opt["value"] for opt in _select_options()}
    return [str(k) for k in raw if str(k) in valid]


def _as_str_list(v: Any) -> List[str]:
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x or "").strip()]
    return []


def _as_opt_str(v: Any) -> str:
    s = str(v or "").strip()
    return s  # allow empty → "optional"


# Leer oder 4–5 Ziffern
PIN_VALIDATOR = vol.All(str, vol.Match(r"^(\d{4,5})?$"))

# ---------- Config Flow ----------


class DachsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow für Dachs Senertec Modbus."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        if user_input is not None:
            # Keine komplexen Objekte speichern – nur primitive Typen
            clean = dict(user_input)
            clean[CONF_HOST] = str(clean.get(CONF_HOST, "")).strip()
            clean[CONF_PORT] = cv.port(clean.get(CONF_PORT, DEFAULT_PORT))
            clean[CONF_UNIT_ID] = int(clean.get(CONF_UNIT_ID, DEFAULT_UNIT_ID))
            clean[CONF_INTERVAL] = int(clean.get(CONF_INTERVAL, UPDATE_INTERVAL))
            clean[CONF_GLT_PIN] = PIN_VALIDATOR(
                str(clean.get(CONF_GLT_PIN, DEFAULT_GLT_PIN)).strip()
            )
            clean[CONF_GLT_HEARTBEAT_INTERVAL] = int(
                clean.get(CONF_GLT_HEARTBEAT_INTERVAL, DEFAULT_GLT_HEARTBEAT_INTERVAL)
            )
            clean[CONF_KEYS] = _sanitize_default_keys(
                {CONF_KEYS: clean.get(CONF_KEYS, FAST_KEYS_DEFAULT_STR)}
            )

            # clean[CONF_INSIDE_TEMPS] = _as_str_list(clean.get(CONF_INSIDE_TEMPS))

            # clean[CONF_OUTSIDE_TEMP] = _as_opt_str(clean.get(CONF_OUTSIDE_TEMP))
            # clean[CONF_ACCUWEATHER] = _as_opt_str(clean.get(CONF_ACCUWEATHER))

            return self.async_create_entry(
                title=f"Dachs GLT @ {clean.get(CONF_HOST, '')}",
                data=clean,
            )

        # SelectSelector: durchsuchbares Dropdown, multiple=True
        keys_selector = sel.SelectSelector(
            sel.SelectSelectorConfig(
                options=_select_options(),
                multiple=True,
                custom_value=False,
                mode=sel.SelectSelectorMode.DROPDOWN,  # zeigt Chips für Auswahl
            )
        )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=int(DEFAULT_PORT)): vol.All(
                    int, vol.Range(min=1, max=65535)
                ),
                vol.Required(
                    CONF_UNIT_ID, default=int(DEFAULT_UNIT_ID)
                ): unit_id_selector,
                vol.Required(CONF_INTERVAL, default=int(UPDATE_INTERVAL)): vol.All(
                    int, vol.Range(min=1, max=3600)
                ),
                vol.Optional(CONF_GLT_PIN, default=str(DEFAULT_GLT_PIN)): cv.string,
                vol.Required(
                    CONF_GLT_HEARTBEAT_INTERVAL,
                    default=int(DEFAULT_GLT_HEARTBEAT_INTERVAL),
                ): vol.All(int, vol.Range(min=5, max=3600)),
                vol.Required(
                    CONF_KEYS,
                    default=_sanitize_default_keys({CONF_KEYS: FAST_KEYS_DEFAULT_STR}),
                ): keys_selector,
                # vol.Optional(
                #     CONF_INSIDE_TEMPS
                # ): inside_temps_selector,  # mehrere, Pflicht
                # vol.Optional(
                #     CONF_OUTSIDE_TEMP
                # ): outside_temp_selector,  # optional, einer
                # vol.Optional(CONF_ACCUWEATHER): accuweather_selector,  # optional, einer
            }
        )

        return self.async_show_form(step_id="user", data_schema=data_schema)

    @staticmethod
    def async_get_options_flow(entry: config_entries.ConfigEntry):
        return DachsOptionsFlow(entry)


# ---------- Options Flow ----------


class DachsOptionsFlow(config_entries.OptionsFlow):
    """Options flow, um Intervalle/Keys/Heartbeat später zu ändern."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        current: Dict[str, Any] = {**self._entry.data, **self._entry.options}

        if user_input is not None:
            clean = dict(user_input)
            clean[CONF_HOST] = str(clean.get(CONF_HOST, "")).strip()
            clean[CONF_PORT] = cv.port(clean.get(CONF_PORT, DEFAULT_PORT))
            clean[CONF_INTERVAL] = int(
                clean.get(CONF_INTERVAL, current.get(CONF_INTERVAL, UPDATE_INTERVAL))
            )
            clean[CONF_UNIT_ID] = int(
                clean.get(CONF_UNIT_ID, current.get(CONF_UNIT_ID, DEFAULT_UNIT_ID))
            )
            clean[CONF_GLT_PIN] = str(
                clean.get(CONF_GLT_PIN, current.get(CONF_GLT_PIN, DEFAULT_GLT_PIN))
            ).strip()
            clean[CONF_GLT_HEARTBEAT_INTERVAL] = int(
                clean.get(
                    CONF_GLT_HEARTBEAT_INTERVAL,
                    current.get(
                        CONF_GLT_HEARTBEAT_INTERVAL, DEFAULT_GLT_HEARTBEAT_INTERVAL
                    ),
                )
            )
            clean[CONF_KEYS] = _sanitize_default_keys(
                {
                    CONF_KEYS: clean.get(
                        CONF_KEYS, current.get(CONF_KEYS, FAST_KEYS_DEFAULT_STR)
                    )
                }
            )

            # clean[CONF_INSIDE_TEMPS] = _as_str_list(clean.get(CONF_INSIDE_TEMPS))

            # clean[CONF_OUTSIDE_TEMP] = _as_opt_str(clean.get(CONF_OUTSIDE_TEMP))
            # clean[CONF_ACCUWEATHER] = _as_opt_str(clean.get(CONF_ACCUWEATHER))

            return self.async_create_entry(title="", data=clean)

        keys_selector = sel.SelectSelector(
            sel.SelectSelectorConfig(
                options=_select_options(),
                multiple=True,
                custom_value=False,
                mode=sel.SelectSelectorMode.DROPDOWN,
            )
        )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=int(DEFAULT_PORT)): vol.All(
                    int, vol.Range(min=1, max=65535)
                ),
                vol.Required(
                    CONF_INTERVAL,
                    default=int(current.get(CONF_INTERVAL, UPDATE_INTERVAL)),
                ): vol.All(int, vol.Range(min=1, max=3600)),
                vol.Required(
                    CONF_UNIT_ID,
                    default=int(current.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)),
                ): unit_id_selector,
                vol.Optional(
                    CONF_GLT_PIN,
                    default=str(current.get(CONF_GLT_PIN, DEFAULT_GLT_PIN)),
                ): cv.string,
                vol.Required(
                    CONF_GLT_HEARTBEAT_INTERVAL,
                    default=int(
                        current.get(
                            CONF_GLT_HEARTBEAT_INTERVAL, DEFAULT_GLT_HEARTBEAT_INTERVAL
                        )
                    ),
                ): vol.All(int, vol.Range(min=5, max=3600)),
                vol.Required(
                    CONF_KEYS,
                    default=_sanitize_default_keys(current),
                ): keys_selector,
                # vol.Optional(
                #     CONF_INSIDE_TEMPS
                # ): inside_temps_selector,  # mehrere, Pflicht
                # vol.Optional(
                #     CONF_OUTSIDE_TEMP
                # ): outside_temp_selector,  # optional, einer
                # vol.Optional(CONF_ACCUWEATHER): accuweather_selector,  # optional, einer
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)
