"""Stałe integracji Enea Energy."""

DOMAIN = "enea_energy"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_START_DATE = "start_date"
CONF_POINT_OF_DELIVERY_ID = "point_of_delivery_id"
# UUID z URL po kliknięciu klienta: .../dashboard/select-current-client/<tu>
CONF_CURRENT_CLIENT_ID = "current_client_id"
# Jaka część energii oddanej do sieci liczy się jako „do odbioru” (prosument, domyślnie 80%).
CONF_EXPORT_RECOVERY_PERCENT = "export_recovery_percent"

DATA_LAG_DAYS = 3
DEFAULT_EXPORT_RECOVERY_PERCENT = 80

# Codzienne sprawdzenie nowych dni (czas lokalny HA).
DAILY_CHECK_HOUR = 20
DAILY_CHECK_MINUTE = 0

STORAGE_KEY = "enea_energy_store"
STORAGE_VERSION = 1

# --- eBOK logowanie: https://ebok.enea.pl/logowanie ---
ENEA_LOGIN_PAGE_URL = "https://ebok.enea.pl/logowanie"
ENEA_LOGIN_SUBMIT_URL = "https://ebok.enea.pl/logowanie"
# Bilans dobowy — odpowiedź JSON (nie CSV): POST jak w DevTools (duration=day&date=DD.MM.RRRR&pointOfDeliveryId=…)
ENEA_METER_SUMMARY_URL = "https://ebok.enea.pl/meter/summaryBalancingChart"
ENEA_METER_SUMMARY_REFERER = "https://ebok.enea.pl/meter/summaryBalancingChart"
ENEA_DASHBOARD_MANY_CLIENTS_URL = "https://ebok.enea.pl/dashboard/many-clients"
ENEA_SELECT_CURRENT_CLIENT_BASE = "https://ebok.enea.pl/dashboard/select-current-client/"

# Pola formularza HTML (name=): email + password + dynamiczny token z GET
ENEA_FORM_USER_FIELD = "email"
ENEA_FORM_PASSWORD_FIELD = "password"
ENEA_FORM_TOKEN_FIELD = "token"

# Opcjonalnie: stałe dodatkowe pola POST (poza tokenem z HTML)
ENEA_LOGIN_EXTRA_FIELDS: dict[str, str] | None = None
