from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)


from dataclasses import dataclass


@dataclass(frozen=True)
class DachsDesc(SensorEntityDescription):
    key: str


DESCRIPTIONS: dict[str, DachsDesc] = {
    "plant_status_enum": DachsDesc(
        key="plant_status_enum",
        name="BHKW Status",
        icon="mdi:engine",
        device_class=SensorDeviceClass.ENUM,
    ),
    "last_shutdown_reason_enum": DachsDesc(
        key="last_shutdown_reason_enum",
        name="Letzter Abschaltgrund",
        icon="mdi:engine",
        device_class=SensorDeviceClass.ENUM,
    ),
    "request_type_enum": DachsDesc(
        key="request_type_enum",
        name="Letzte Anfrage",
        icon="mdi:engine",
        device_class=SensorDeviceClass.ENUM,
    ),
    "electrical_power_kW": DachsDesc(
        key="electrical_power_kW",
        name="Elektrische Leistung",
        native_unit_of_measurement="kW",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "energy_el_total_kWh": DachsDesc(
        key="energy_el_total_kWh",
        name="Elektrische Energie gesamt",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "energy_th_total_kWh": DachsDesc(
        key="energy_th_total_kWh",
        name="Thermische Energie gesamt",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "temp_out_C": DachsDesc(
        key="temp_out_C",
        name="BHKW Vorlauf",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "temp_in_C": DachsDesc(
        key="temp_in_C",
        name="BHKW Rücklauf",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "outdoor_temp_C": DachsDesc(
        key="outdoor_temp_C",
        name="Außentemperatur",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "buffer_T1_C": DachsDesc(
        key="buffer_T1_C",
        name="Pufferspeichertemperatur 1",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "buffer_T2_C": DachsDesc(
        key="buffer_T2_C",
        name="Pufferspeichertemperatur 2",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "buffer_T3_C": DachsDesc(
        key="buffer_T3_C",
        name="Pufferspeichertemperatur 3",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "buffer_T4_C": DachsDesc(
        key="buffer_T4_C",
        name="Pufferspeichertemperatur 4",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "op_hours_total_h": DachsDesc(
        key="op_hours_total_h",
        name="Laufzeit",
        native_unit_of_measurement="h",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
}
