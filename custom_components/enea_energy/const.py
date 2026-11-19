"""Constants for the Enea Energy integration."""

from __future__ import annotations

DOMAIN = "enea_energy"

# Legacy (pre–Moja Enea OIDC); kept for migration / entry titles only.
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Since ~2026-10 eBOK signs in via moja.enea.pl (reCAPTCHA + optional SMS 2FA).
# The integration takes over browser session cookies — it never submits the password.
CONF_EBOK_COOKIE = "ebok_cookie"  # EBOK_SESSION for ebok.enea.pl
CONF_SSO_COOKIE = "sso_cookie"  # PHPSESSID (and friends) for moja.enea.pl

CONF_START_DATE = "start_date"
CONF_POINT_OF_DELIVERY_ID = "point_of_delivery_id"
# UUID from URL after selecting a client: .../dashboard/select-current-client/<here>
CONF_CURRENT_CLIENT_ID = "current_client_id"
# Share of exported energy counted as recoverable (prosumer, default 80%).
CONF_EXPORT_RECOVERY_PERCENT = "export_recovery_percent"

DEFAULT_EXPORT_RECOVERY_PERCENT = 80
EXPORT_RECOVERY_PERCENT_OPTIONS = (70, 80)

# Daily check for new published days (Home Assistant local time).
DAILY_CHECK_HOUR = 20
DAILY_CHECK_MINUTE = 0

# Touch eBOK so the handed-over session does not idle out between daily syncs.
KEEPALIVE_MINUTES = 10

# eBOK usually publishes full days with a delay; skip today and treat fresh [] as no data.
SYNC_LAG_DAYS = 1
RECENT_DATA_LAG_DAYS = 3

STORAGE_KEY = "enea_energy_store"
STORAGE_VERSION = 1

ENEA_BASE_URL = "https://ebok.enea.pl"
ENEA_SSO_URL = "https://moja.enea.pl"
EBOK_COOKIE_NAME = "EBOK_SESSION"
SSO_COOKIE_NAME = "PHPSESSID"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# --- eBOK meter API (unchanged) ---
ENEA_LOGIN_PAGE_URL = "https://ebok.enea.pl/logowanie"
ENEA_METER_SUMMARY_URL = "https://ebok.enea.pl/meter/summaryBalancingChart"
ENEA_METER_SUMMARY_REFERER = "https://ebok.enea.pl/meter/summaryBalancingChart"
ENEA_DASHBOARD_MANY_CLIENTS_URL = "https://ebok.enea.pl/dashboard/many-clients"
ENEA_SELECT_CURRENT_CLIENT_BASE = "https://ebok.enea.pl/dashboard/select-current-client/"

# eBOK requires Cookiebot consent before some portal pages submit.
ENEA_COOKIEBOT_CONSENT_VALUE = (
    "{stamp:'-1',necessary:true,preferences:true,"
    "statistics:true,marketing:true,method:'implied',ver:1,utc:1700000000000}"
)
