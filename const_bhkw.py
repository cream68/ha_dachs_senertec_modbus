from __future__ import annotations

from enum import Enum
from typing import Final, TypedDict, Literal

from homeassistant.helpers.entity import DeviceInfo

# ----- Domain / config keys -----
DOMAIN: Final = "bhkw"

CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_UNIT_ID: Final = "unit_id"
CONF_INTERVAL: Final = "update interval"
CONF_KEYS: Final = "fast_keys"

CONF_GLT_PIN: Final = "glt_pin"
DEFAULT_GLT_PIN: Final = ""  # empty means "not configured"
CONF_GLT_HEARTBEAT_INTERVAL: Final = "glt_heartbeat_interval"  # seconds
DEFAULT_GLT_HEARTBEAT_INTERVAL: Final = 300  # set to what your GLT expects

DEFAULT_PORT: Final = 502
DEFAULT_UNIT_ID: Final = 1
UPDATE_INTERVAL: Final = 60  # seconds

MANUFACTURER: Final = "Senertec"
INTEGRATION_NAME: Final = "Dachs Senertec Modbus Reader and Writer"

# ---------- Register definition ----------
RegType = Literal["U16", "S16", "U32", "S32", "U64"]
FmtType = Literal["FIX0", "FIX1", "FIX2", "FIX3", "FIX4", "TEMP", "DT", "ENUM", "RAW"]

# ----- Dachs enum maps -----
PLANT_STATUS_MAP = {
    0: "Aus",
    1: "Standby",
    2: "Läuft",
    3: "Wartezustand",
    4: "Fehler",
}

REQUEST_TYPE_MAP = {  # 8015 — Art der Anforderung
    0: "Keine",
    1: "Mindestlaufzeit",
    2: "Notbetrieb",
    3: "Stromanforderung",
    4: "Wärmeanforderung",
    5: "TWW Anforderung",
    6: "Kaminkehrermodus",
}

LAST_SHUTDOWN_REASON_MAP = {  # 8017 — Letzter Abschaltgrund
    0: "Nicht definiert",
    1: "Manuell",
    2: "Keine Anforderung",
    3: "Fehler",
    4: "Eintrittstemp. zu hoch",
    5: "24h Abschaltung",
    6: "Takten/Stillstand",
    7: "Freigabe Netz",
    8: "Freigabe Uhr",
    9: "Freigabe extern",
    10: "NA-Schutz Fehler",
    11: "Release Building Management System",
}

# Generic key→map routing so sensors can translate automatically
ENUM_MAPS: dict[str, dict[int, str]] = {
    "plant_status_enum": PLANT_STATUS_MAP,
    "request_type_enum": REQUEST_TYPE_MAP,
    "last_shutdown_reason_enum": LAST_SHUTDOWN_REASON_MAP,
}


def make_device_info(entry_id: str, host: str, port: int, unit_id: int) -> DeviceInfo:
    """Return consistent DeviceInfo for all Dachs platforms."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},  # use entry_id for global consistency
        manufacturer=MANUFACTURER,
        name=f"Dachs GLT @ {host}",
        model=f"Senertec Dachs (Modbus TCP {port}, Unit {unit_id})",
        configuration_url=f"http://{host}",  # optional: clickable in HA
    )


class RegisterDef(TypedDict):
    ref: int  # Modbus *input* register address (word index) exactly as in manual
    cnt: int  # number of 16-bit registers
    type: RegType  # unsigned/signed width (manual lists UNSIGNED/INTEGER types)
    fmt: FmtType  # display/scale hint (TEMP => 0.1°C, FIX1 => /10, etc.)
    access: Literal[
        "RO", "RO/WO"
    ]  # RO for reads (0x04), RO/WO when a writeback exists (0x06)


# =========================================================
# READ REGISTERS (FC = 0x04 Read Input Registers)
# =========================================================
READ_REGS: dict[str, RegisterDef] = {
    # ---- 6.2.1 Profil der KWK-Anlage (8000..8012) ----
    "glt_version": {
        "ref": 8000,
        "cnt": 1,
        "type": "U16",
        "fmt": "RAW",
        "access": "RO",
    },  # main.sub
    "device_type": {
        "ref": 8001,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
    # Serial number VisibleString[20] over 10 registers (8002..8011)
    "serial_1_2": {"ref": 8002, "cnt": 1, "type": "U16", "fmt": "RAW", "access": "RO"},
    "serial_3_4": {"ref": 8003, "cnt": 1, "type": "U16", "fmt": "RAW", "access": "RO"},
    "serial_5_6": {"ref": 8004, "cnt": 1, "type": "U16", "fmt": "RAW", "access": "RO"},
    "serial_7_8": {"ref": 8005, "cnt": 1, "type": "U16", "fmt": "RAW", "access": "RO"},
    "serial_9_10": {"ref": 8006, "cnt": 1, "type": "U16", "fmt": "RAW", "access": "RO"},
    "serial_11_12": {
        "ref": 8007,
        "cnt": 1,
        "type": "U16",
        "fmt": "RAW",
        "access": "RO",
    },
    "serial_13_14": {
        "ref": 8008,
        "cnt": 1,
        "type": "U16",
        "fmt": "RAW",
        "access": "RO",
    },
    "serial_15_16": {
        "ref": 8009,
        "cnt": 1,
        "type": "U16",
        "fmt": "RAW",
        "access": "RO",
    },
    "serial_17_18": {
        "ref": 8010,
        "cnt": 1,
        "type": "U16",
        "fmt": "RAW",
        "access": "RO",
    },
    "serial_19_20": {
        "ref": 8011,
        "cnt": 1,
        "type": "U16",
        "fmt": "RAW",
        "access": "RO",
    },
    "module_nominal_power_kW": {
        "ref": 8012,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX1",
        "access": "RO",
    },  # 0.1 kW
    # ---- 6.2.2 Status des KWK-Gerätes (8013..8020) ----
    "plant_status_enum": {
        "ref": 8013,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },  # 0..4
    "electrical_power_kW": {
        "ref": 8014,
        "cnt": 1,
        "type": "S16",
        "fmt": "FIX1",
        "access": "RO",
    },  # 0.1 kW
    "request_type_enum": {
        "ref": 8015,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
    "runtime_since_start_h": {
        "ref": 8016,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX1",
        "access": "RO",
    },  # 0.1 h
    "last_shutdown_reason_enum": {
        "ref": 8017,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
    "pump_status_enum": {
        "ref": 8018,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
    "temp_out_C": {
        "ref": 8019,
        "cnt": 1,
        "type": "U16",
        "fmt": "TEMP",
        "access": "RO",
    },  # 0.1 °C
    "temp_in_C": {
        "ref": 8020,
        "cnt": 1,
        "type": "U16",
        "fmt": "TEMP",
        "access": "RO",
    },  # 0.1 °C
    # ---- 6.2.3 Konfiguration des KWK-Gerätes (8021..8026) ----
    "lead_quantity_enum": {
        "ref": 8021,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },  # Wärme/Strom/…
    "min_runtime_min": {
        "ref": 8022,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO",
    },
    "max_inlet_temp_C": {
        "ref": 8023,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },  # 0.1 °C
    "modulation_onoff": {
        "ref": 8024,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
    "fixed_stage_level": {
        "ref": 8025,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO",
    },
    "module_type_enum": {
        "ref": 8026,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
    # ---- 6.2.4 Betriebsdaten (8027..8040) ----
    "op_hours_total_h": {
        "ref": 8027,
        "cnt": 2,
        "type": "U32",
        "fmt": "FIX0",
        "access": "RO",
    },
    "start_count": {
        "ref": 8029,
        "cnt": 2,
        "type": "U32",
        "fmt": "FIX0",
        "access": "RO",
    },
    "energy_el_total_kWh": {
        "ref": 8031,
        "cnt": 2,
        "type": "U32",
        "fmt": "FIX1",
        "access": "RO",
    },  # 0.1 kWh
    "energy_th_total_kWh": {
        "ref": 8033,
        "cnt": 2,
        "type": "U32",
        "fmt": "FIX1",
        "access": "RO",
    },  # 0.1 kWh
    "op_hours_stage1_h": {
        "ref": 8035,
        "cnt": 2,
        "type": "U32",
        "fmt": "FIX0",
        "access": "RO",
    },
    "op_hours_stage2_h": {
        "ref": 8037,
        "cnt": 2,
        "type": "U32",
        "fmt": "FIX0",
        "access": "RO",
    },
    "op_hours_stage3_h": {
        "ref": 8039,
        "cnt": 2,
        "type": "U32",
        "fmt": "FIX0",
        "access": "RO",
    },
    # ---- 6.2.5 Systemdaten (8041..8056) ----
    "outdoor_temp_C": {
        "ref": 8041,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "buffer_T1_C": {
        "ref": 8042,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "buffer_T2_C": {
        "ref": 8043,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "buffer_T3_C": {
        "ref": 8044,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "buffer_T4_C": {
        "ref": 8045,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "buffer_T5_unused": {
        "ref": 8046,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "buffer_T6_unused": {
        "ref": 8047,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "sensor1_unused": {
        "ref": 8048,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "sensor2_unused": {
        "ref": 8049,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "sensor3_unused": {
        "ref": 8050,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "sensor4_unused": {
        "ref": 8051,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "temp_sensor5_C": {
        "ref": 8052,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "temp_sensor6_C": {
        "ref": 8053,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "temp_sensor7_C": {
        "ref": 8054,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "temp_sensor8_C": {
        "ref": 8055,
        "cnt": 1,
        "type": "S16",
        "fmt": "TEMP",
        "access": "RO",
    },
    "discharge_power_pct": {
        "ref": 8056,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO",
    },
    # ---- 6.2.6 Konfiguration der KWK-Anlage (8057..8065) ----
    "buffer_type_enum": {
        "ref": 8057,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
    "buffer_volume_l": {
        "ref": 8058,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO",
    },
    "buffer_sensor_cfg_enum": {
        "ref": 8059,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
    "buffer_pos1_pct": {
        "ref": 8060,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO",
    },
    "buffer_pos2_pct": {
        "ref": 8061,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO",
    },
    "buffer_pos3_pct": {
        "ref": 8062,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO",
    },
    "buffer_pos4_pct": {
        "ref": 8063,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO",
    },
    "heat_provisioning_enum": {
        "ref": 8064,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
    "buffer_discharge_onoff": {
        "ref": 8065,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
    # ---- 6.2.7 Mehrmodulanlage (8066..8072) ----
    "mm_active_power_kW": {
        "ref": 8066,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX1",
        "access": "RO",
    },  # 0.1 kW
    "mm_modules_detected": {
        "ref": 8067,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO",
    },
    "mm_modules_available": {
        "ref": 8068,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO",
    },
    "mm_modules_requested": {
        "ref": 8069,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO",
    },
    "mm_modules_running": {
        "ref": 8070,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO",
    },
    "mm_modules_configured": {
        "ref": 8071,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO",
    },
    "mm_nominal_power_kW": {
        "ref": 8072,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX1",
        "access": "RO",
    },  # 0.1 kW
    # ---- 6.2.8 Zweiter Wärmeerzeuger (8073..8083) ----
    "we2_status_enum": {
        "ref": 8073,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
    "we2_set_status_enum": {
        "ref": 8074,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
    "we2_start_count": {
        "ref": 8075,
        "cnt": 2,
        "type": "U32",
        "fmt": "FIX0",
        "access": "RO",
    },
    "we2_op_hours_h": {
        "ref": 8077,
        "cnt": 2,
        "type": "U32",
        "fmt": "FIX0",
        "access": "RO",
    },
    "we2_available_bool": {
        "ref": 8079,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
    "we2_release_bool": {
        "ref": 8080,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
    "we2_nominal_power_kW": {
        "ref": 8081,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX1",
        "access": "RO",
    },  # 0.1 kW
    "we2_min_runtime_min": {
        "ref": 8082,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO",
    },
    "we2_connected_to_buffer": {
        "ref": 8083,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO",
    },
}

# =========================================================
# WRITE REGISTERS (FC = 0x06 Write Single Register)
# =========================================================
# Heartbeat rule: write at < 10 min intervals; 8301 changes accepted only every 5 min.
WRITE_REGS: dict[str, RegisterDef] = {
    # ---- 6.3 Sollwerte (8300..8302) ----
    "glt_pin": {
        "ref": 8300,
        "cnt": 1,
        "type": "U16",
        "fmt": "RAW",
        "access": "RO/WO",  # 4-digit PIN
    },
    "electrical_setpoint_W": {
        "ref": 8301,
        "cnt": 1,
        "type": "U16",
        "fmt": "FIX0",
        "access": "RO/WO",  # steps of 10 W (raw * 10 W)
    },
    "bhkw_locked_bool": {
        "ref": 8302,
        "cnt": 1,
        "type": "U16",
        "fmt": "ENUM",
        "access": "RO/WO",  # 0=Nein, 1=Ja
    },
}


# ---------- Keys for autocomplete ----------
class DachsKey(str, Enum):
    # reads
    glt_version = "glt_version"
    device_type = "device_type"
    serial_1_2 = "serial_1_2"
    serial_3_4 = "serial_3_4"
    serial_5_6 = "serial_5_6"
    serial_7_8 = "serial_7_8"
    serial_9_10 = "serial_9_10"
    serial_11_12 = "serial_11_12"
    serial_13_14 = "serial_13_14"
    serial_15_16 = "serial_15_16"
    serial_17_18 = "serial_17_18"
    serial_19_20 = "serial_19_20"
    module_nominal_power_kW = "module_nominal_power_kW"

    plant_status_enum = "plant_status_enum"
    electrical_power_kW = "electrical_power_kW"
    request_type_enum = "request_type_enum"
    runtime_since_start_h = "runtime_since_start_h"
    last_shutdown_reason = "last_shutdown_reason"
    pump_status_enum = "pump_status_enum"
    temp_out_C = "temp_out_C"
    temp_in_C = "temp_in_C"

    lead_quantity_enum = "lead_quantity_enum"
    min_runtime_min = "min_runtime_min"
    max_inlet_temp_C = "max_inlet_temp_C"
    modulation_onoff = "modulation_onoff"
    fixed_stage_level = "fixed_stage_level"
    module_type_enum = "module_type_enum"

    op_hours_total_h = "op_hours_total_h"
    start_count = "start_count"
    energy_el_total_kWh = "energy_el_total_kWh"
    energy_th_total_kWh = "energy_th_total_kWh"
    op_hours_stage1_h = "op_hours_stage1_h"
    op_hours_stage2_h = "op_hours_stage2_h"
    op_hours_stage3_h = "op_hours_stage3_h"

    outdoor_temp_C = "outdoor_temp_C"
    buffer_T1_C = "buffer_T1_C"
    buffer_T2_C = "buffer_T2_C"
    buffer_T3_C = "buffer_T3_C"
    buffer_T4_C = "buffer_T4_C"
    buffer_T5_unused = "buffer_T5_unused"
    buffer_T6_unused = "buffer_T6_unused"
    sensor1_unused = "sensor1_unused"
    sensor2_unused = "sensor2_unused"
    sensor3_unused = "sensor3_unused"
    sensor4_unused = "sensor4_unused"
    temp_sensor5_C = "temp_sensor5_C"
    temp_sensor6_C = "temp_sensor6_C"
    temp_sensor7_C = "temp_sensor7_C"
    temp_sensor8_C = "temp_sensor8_C"
    discharge_power_pct = "discharge_power_pct"

    buffer_type_enum = "buffer_type_enum"
    buffer_volume_l = "buffer_volume_l"
    buffer_sensor_cfg_enum = "buffer_sensor_cfg_enum"
    buffer_pos1_pct = "buffer_pos1_pct"
    buffer_pos2_pct = "buffer_pos2_pct"
    buffer_pos3_pct = "buffer_pos3_pct"
    buffer_pos4_pct = "buffer_pos4_pct"
    heat_provisioning_enum = "heat_provisioning_enum"
    buffer_discharge_onoff = "buffer_discharge_onoff"

    mm_active_power_kW = "mm_active_power_kW"
    mm_modules_detected = "mm_modules_detected"
    mm_modules_available = "mm_modules_available"
    mm_modules_requested = "mm_modules_requested"
    mm_modules_running = "mm_modules_running"
    mm_modules_configured = "mm_modules_configured"
    mm_nominal_power_kW = "mm_nominal_power_kW"

    we2_status_enum = "we2_status_enum"
    we2_set_status_enum = "we2_set_status_enum"
    we2_start_count = "we2_start_count"
    we2_op_hours_h = "we2_op_hours_h"
    we2_available_bool = "we2_available_bool"
    we2_release_bool = "we2_release_bool"
    we2_nominal_power_kW = "we2_nominal_power_kW"
    we2_min_runtime_min = "we2_min_runtime_min"
    we2_connected_to_buffer = "we2_connected_to_buffer"

    # writes
    glt_pin = "glt_pin"
    electrical_setpoint_W = "electrical_setpoint_W"
    bhkw_locked_bool = "bhkw_locked_bool"


# Helpful defaults for a “fast” telemetry set
DEFAULT_KEYS: list[DachsKey] = [
    DachsKey.plant_status_enum,
    DachsKey.op_hours_total_h,
    DachsKey.electrical_power_kW,
    DachsKey.energy_el_total_kWh,
    DachsKey.energy_th_total_kWh,
    DachsKey.outdoor_temp_C,
    DachsKey.temp_out_C,
    DachsKey.temp_in_C,
    DachsKey.buffer_T1_C,
    DachsKey.buffer_T2_C,
    DachsKey.buffer_T3_C,
    DachsKey.buffer_T4_C,
    DachsKey.last_shutdown_reason,
    DachsKey.request_type_enum,
]

CONF_GLT_HEARTBEAT_ENABLED: Final = "glt_heartbeat_enabled"
CONF_GLT_PIN: Final = "glt_pin"
CONF_GLT_HEARTBEAT_SEC: Final = "glt_heartbeat_sec"

# Defaults
DEFAULT_GLT_HEARTBEAT_ENABLED: Final = True  # default ON
DEFAULT_GLT_HEARTBEAT_SEC: Final = 300  # every 5 minutes (spec: < 10 min)

FAST_KEYS_DEFAULT_STR: list[str] = [k.value for k in DEFAULT_KEYS]
ALL_READ_KEYS_STR: list[str] = sorted(READ_REGS.keys())
ALL_WRITE_KEYS_STR: list[str] = sorted(WRITE_REGS.keys())
