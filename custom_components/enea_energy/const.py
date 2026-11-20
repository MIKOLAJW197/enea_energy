"""Constants for the Enea Energy integration."""

from __future__ import annotations

DOMAIN = "enea_energy"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_START_DATE = "start_date"
CONF_METER_ID = "meter_id"
CONF_METER_CODE = "meter_code"
# Share of exported energy counted as recoverable (prosumer, default 80%).
CONF_EXPORT_RECOVERY_PERCENT = "export_recovery_percent"

DEFAULT_EXPORT_RECOVERY_PERCENT = 80
EXPORT_RECOVERY_PERCENT_OPTIONS = (70, 80)

# Coordinator poll interval (hours).
UPDATE_INTERVAL_HOURS = 3

PORTAL_URL = "https://portalodbiorcy.operator.enea.pl"
PORTAL_API_BASE = f"{PORTAL_URL}/portalOdbiorcy/api"
URL_LOGIN = f"{PORTAL_API_BASE}/auth/login"
URL_PPES = f"{PORTAL_API_BASE}/user/ppes"
URL_PPE_DASHBOARD = f"{PORTAL_API_BASE}/consumptionDashboard/ppe/{{meter_id}}"
URL_CONSUMPTION_RANGE = (
    f"{PORTAL_API_BASE}"
    "/consumption/{meter_id}/{start_date}/{end_date}/{measurement_type}/{resolution}"
)
URL_CONSUMPTION_RANGE_DATA_SOURCE = URL_CONSUMPTION_RANGE + "/{data_source}"

REQUEST_TIMEOUT_SECONDS = 120

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# measurement_type for /consumption/… (Portal Odbiorcy numbering)
MEASUREMENT_ENERGY_CONSUMED = 1
MEASUREMENT_ENERGY_RETURNED = 5

# resolution: 1 = 15 min, 2 = 60 min
RESOLUTION_HOURLY = 2

# Prosumer data source: 1 = before balancing, 2 = after balancing
DATA_SOURCE_AFTER_BALANCING = 2

# billingWeekData: measurementId 1 = active energy consumed (same as portal UI).
DASHBOARD_MEASUREMENT_CONSUMPTION = 1
# Long segments interleaved with daily ones mark invoice period boundaries.
BILLING_PERIOD_MIN_SEGMENT_DAYS = 2
