"""
Python app to check UPS status and relay to InfluxDB for Sinclair Group use.

Poll a NUT UPS via pynutclient and upload status snapshots to InfluxDB.

Notes on a few common NUT UPS variables used here
-------------------------------------------------
ups.status
    A space-separated list of status tokens reported by NUT.

    Common examples:
    - "OL"
        On line. Utility AC power is present and the UPS is not currently
        running from battery.
    - "OB"
        On battery. Utility AC power is absent or out of tolerance, and the
        UPS output is currently being powered by the battery/inverter.
    - "LB"
        Low battery. Remaining battery energy is low enough that shutdown
        logic may need to be considered soon.
    - "CHRG"
        Charging. The battery is currently charging.
    - "DISCHRG"
        Discharging. The battery is currently discharging.
    - "RB"
        Replace battery. The UPS is reporting that the battery should be
        replaced or at least checked.
    - "OVER"
        Overload. The UPS output load is above the supported range.

    Multiple tokens can appear at once. For example:
    - "OL CHRG"
        Utility power is present and the battery is charging.
    - "OB DISCHRG"
        The UPS is running from battery and the battery is being discharged.
    - "OB DISCHRG LB"
        The UPS is on battery and the battery is getting low.

battery.charge
    Battery state of charge in percent. Typical example: 100.0

battery.runtime
    Estimated remaining runtime in seconds at the current load.
    Typical example: 1520.0

input.voltage
    Input AC voltage seen by the UPS. Typical example: 120.0

output.voltage
    Output AC voltage delivered by the UPS. Typical example: 120.0

ups.load
    UPS load as a percent of rated capacity. Typical example: 18.0

ups.realpower
    Real output power in watts, if the UPS reports it. Typical example: 95.0
"""

from __future__ import annotations

from supervisor.supervisor_helper import *

import time
import tomllib
from typing import Any

import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS
from PyNUTClient.PyNUT import PyNUTClient

print()
print("----- NUT UPS readings relay to InfluxDB -----")
print()

# >>>>> app configuration >>>>>

# >>> load & parse config files >>>
# auth
with open("auth.toml", "rb") as f:
    AUTH: dict[str, Any] = tomllib.load(f)
NUT_HOST: str = AUTH["host"]
NUT_PORT: int = int(AUTH.get("port", 3493))
NUT_USERNAME: str | None = AUTH.get("username", None)
NUT_PASSWORD: str | None = AUTH.get("password", None)

# settings
with open("settings.toml", "rb") as f:
    SETTINGS: dict[str, Any] = tomllib.load(f)
NUT_UPS_NAME: str = SETTINGS["ups_name"]
INTERVAL_s: float = float(SETTINGS["interval_s"])
# <<< load & parse config files <<<

# print configuration
print(f"NUT target: {NUT_HOST}:{NUT_PORT}, ups_name: {NUT_UPS_NAME}.")
print(f"Polling interval = {INTERVAL_s} s.")
print()
# <<<<< app configuration <<<<<

# >>> load IMAQ auth/config >>>
with open("imaq_config/auth.toml", "rb") as f:
    IMAQ_AUTH: dict[str, Any] = tomllib.load(f)
# <<< load IMAQ auth/config <<<

# >>> InfluxDB configuration >>>
INFLUXDB_CLIENT = influxdb_client.InfluxDBClient(**IMAQ_AUTH["influxdb"])
INFLUXDB_WRITE_API = INFLUXDB_CLIENT.write_api(write_options=SYNCHRONOUS)
INFLUXDB_QUERY_API = INFLUXDB_CLIENT.query_api()
INFLUXDB_ORG: str = IMAQ_AUTH["influxdb"]["org"]
INFLUXDB_BUCKET: str = IMAQ_AUTH["influxdb"]["bucket"]
print(
    f"InfluxDB client initialized for org='{INFLUXDB_ORG}', "
    f"bucket='{INFLUXDB_BUCKET}'."
)
print()
# <<< InfluxDB configuration <<<


def parse_float(value: Any) -> float | None:
    """
    Convert a NUT value to float when possible.

    Parameters
    ----------
    value
        A value returned by pynutclient. It may be None, bytes, str, int-like,
        or float-like.

    Returns
    -------
    float | None
        Parsed float value, or None if the value is absent or not numeric.
    """
    if value is None:
        return None

    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")

    value = str(value).strip()

    if value == "":
        return None

    try:
        return float(value)
    except ValueError:
        return None


def parse_str(value: Any) -> str:
    """
    Convert a NUT value to a normal Python string.

    pynutclient may return bytes for many text fields, so decode those here.
    Missing values are converted to an empty string.

    All returned strings are stripped to avoid subtle issues such as
    trailing spaces in tags, status strings, serial numbers, or model names.
    """
    if value is None:
        return ""

    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")

    return str(value).strip()


def parse_status_tokens(ups_status: Any) -> set[str]:
    """
    Split the NUT ups.status string into individual status tokens.

    Examples
    --------
    "OL CHRG" -> {"OL", "CHRG"}
    "OB DISCHRG LB" -> {"OB", "DISCHRG", "LB"}

    Common token meanings
    ---------------------
    OL
        On line. Utility power is present.
    OB
        On battery. Utility power is absent or unacceptable.
    LB
        Low battery.
    CHRG
        Battery is charging.
    DISCHRG
        Battery is discharging.
    RB
        Replace battery.
    OVER
        Overload condition.
    """
    ups_status = parse_str(ups_status)
    return {token.strip() for token in ups_status.split() if token.strip()}


def normalize_nut_dict(d: dict[Any, Any]) -> dict[str, str]:
    """
    Convert a NUT dictionary with possible bytes keys and values
    into a normal string-to-string dictionary.
    """
    return {parse_str(key): parse_str(value) for key, value in d.items()}


print("Connecting to NUT server...", end=" ")
NUT_CLIENT = PyNUTClient(
    host=NUT_HOST,
    port=NUT_PORT,
    login=NUT_USERNAME,
    password=NUT_PASSWORD,
)
print("Done.")

print("Checking available UPS list...", end=" ")
UPS_LIST: dict[str, str] = normalize_nut_dict(NUT_CLIENT.GetUPSList())
print("Done.")
print(f"Available UPSes: {UPS_LIST}")

if NUT_UPS_NAME not in UPS_LIST:
    raise RuntimeError(
        f"UPS name '{NUT_UPS_NAME}' not found in NUT server UPS list: {UPS_LIST}"
    )

print(f"Target UPS '{NUT_UPS_NAME}' confirmed.")
print()

il: int = 0
print("Entering main polling loop...")
print()

while True:
    msg_il = f"Iteration {il}: "

    try:
        # Query all UPS variables from the configured UPS.
        UPS_VARS: dict[str, str] = normalize_nut_dict(
            NUT_CLIENT.GetUPSVars(NUT_UPS_NAME)
        )

    except Exception as ex:
        log_error(msg_il)
        log_error(f"NUT query failed: {type(ex).__name__}: {ex}")
        log_warn("Reconnecting to NUT server and retrying once...")

        NUT_CLIENT = PyNUTClient(
            host=NUT_HOST,
            port=NUT_PORT,
            login=NUT_USERNAME,
            password=NUT_PASSWORD,
        )

        UPS_LIST = normalize_nut_dict(NUT_CLIENT.GetUPSList())

        if NUT_UPS_NAME not in UPS_LIST:
            raise RuntimeError(
                f"UPS name '{NUT_UPS_NAME}' disappeared after reconnect. "
                f"Available UPSes: {UPS_LIST}"
            )

        UPS_VARS = normalize_nut_dict(NUT_CLIENT.GetUPSVars(NUT_UPS_NAME))

    # >>> parse common NUT fields >>>
    device_mfr: str = parse_str(UPS_VARS.get("device.mfr"))
    device_model: str = parse_str(UPS_VARS.get("device.model"))
    device_serial: str = parse_str(UPS_VARS.get("device.serial"))
    device_description: str = parse_str(UPS_LIST.get(NUT_UPS_NAME))

    ups_status: str = parse_str(UPS_VARS.get("ups.status"))
    status_tokens: set[str] = parse_status_tokens(ups_status)

    battery_charge_pct: float | None = parse_float(UPS_VARS.get("battery.charge"))
    battery_runtime_s: float | None = parse_float(UPS_VARS.get("battery.runtime"))
    battery_voltage_v: float | None = parse_float(UPS_VARS.get("battery.voltage"))

    input_voltage_v: float | None = parse_float(UPS_VARS.get("input.voltage"))
    input_frequency_hz: float | None = parse_float(UPS_VARS.get("input.frequency"))

    output_voltage_v: float | None = parse_float(UPS_VARS.get("output.voltage"))
    output_frequency_hz: float | None = parse_float(UPS_VARS.get("output.frequency"))

    load_pct: float | None = parse_float(UPS_VARS.get("ups.load"))
    real_power_w: float | None = parse_float(UPS_VARS.get("ups.realpower"))

    ambient_temperature_degC: float | None = parse_float(
        UPS_VARS.get("ambient.temperature")
    )
    # <<< parse common NUT fields <<<

    influxdb_record: dict[str, Any] = {
        "measurement": "NUT_UPS",
        "tags": {
            "ups_name": NUT_UPS_NAME,
            "nut_host": NUT_HOST,
            "DeviceManufacturer": device_mfr,
            "DeviceModel": device_model,
            "DeviceSerial": device_serial,
            "DeviceDescription": device_description,
        },
        "fields": {
            "UPSStatus": ups_status,
            "OnLine": "OL" in status_tokens,
            "OnBattery": "OB" in status_tokens,
            "LowBattery": "LB" in status_tokens,
            "Charging": "CHRG" in status_tokens,
            "Discharging": "DISCHRG" in status_tokens,
            "ReplaceBattery": "RB" in status_tokens,
            "Overloaded": "OVER" in status_tokens,
            "BatteryCharge[%]": battery_charge_pct,
            "BatteryRuntime[s]": battery_runtime_s,
            "BatteryVoltage[V]": battery_voltage_v,
            "InputVoltage[V]": input_voltage_v,
            "InputFrequency[Hz]": input_frequency_hz,
            "OutputVoltage[V]": output_voltage_v,
            "OutputFrequency[Hz]": output_frequency_hz,
            "Load[%]": load_pct,
            "RealPower[W]": real_power_w,
            "Temperature[degC]": ambient_temperature_degC,
        },
    }

    # Remove unavailable numeric fields before upload.
    influxdb_record["fields"] = {
        key: value
        for key, value in influxdb_record["fields"].items()
        if value is not None
    }

    influxdb_records: list[dict[str, Any]] = [influxdb_record]

    INFLUXDB_WRITE_API.write(
        bucket=INFLUXDB_BUCKET,
        org=INFLUXDB_ORG,
        record=influxdb_records,
    )

    log(
        msg_il
        + f"UPSStatus='{ups_status}', "
        + f"BatteryCharge[%]={battery_charge_pct}, "
        + f"BatteryRuntime[s]={battery_runtime_s}, "
        + f"InputVoltage[V]={input_voltage_v}, "
        + f"Load[%]={load_pct}"
    )

    time.sleep(INTERVAL_s)
    il += 1