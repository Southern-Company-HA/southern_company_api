"""Shared constants for the southern_company_api package.

Centralizes browser headers, API URLs, and other constants used across
parser.py and account.py to keep them DRY.
"""

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_ACCEPT_HTML = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8"
)

_ACCEPT_JSON = "application/json, text/plain, */*"
_ACCEPT_LANGUAGE = "en-US,en;q=0.9"

# --- URLs ------------------------------------------------------------------

WEBAUTH_BASE = "https://webauth.southernco.com"
LOGIN_PAGE_URL = f"{WEBAUTH_BASE}/account/login"
LOGIN_API_URL = f"{WEBAUTH_BASE}/api/login"

CS_BASE = "https://customerservice2.southerncompany.com"
LOGIN_COMPLETE_URL = f"{CS_BASE}/Account/LoginComplete?ReturnUrl=/Billing/Home"
JWT_TOKEN_URL = f"{CS_BASE}/Account/LoginValidated/JwtToken"
CS_BILLING_HOME = f"{CS_BASE}/Billing/Home"

# NOTE (Sept 2026 backend migration): the old customerservice2api.southerncompany.com
# origin used before the migration no longer serves the account/data API at all --
# every path on it now falls through to a static "site is currently down"
# maintenance page (HTTP 200, text/html) instead of JSON. The account list and
# account-summary endpoints moved to occaccountapi.southerncompany.com, and the
# usage-graph (hourly/daily/monthly) endpoint moved to
# occmypowerusageapi.southerncompany.com. Both confirmed working live, Sept 2026,
# via a fresh HAR capture of the post-migration site.
ACCOUNT_API_BASE = "https://occaccountapi.southerncompany.com/api/v1"
GET_ALL_ACCOUNTS_URL = f"{ACCOUNT_API_BASE}/Cap/"

USAGE_API_BASE = "https://occmypowerusageapi.southerncompany.com/api/v1/MyPowerUsage"

EMAIL_VALIDATION_URL = f"{CS_BASE}/MyProfile/LoginInfo"

# --- Header dicts ----------------------------------------------------------

LOGIN_PAGE_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": _ACCEPT_HTML,
    "Accept-Language": _ACCEPT_LANGUAGE,
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

LOGIN_API_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": _ACCEPT_JSON,
    "Accept-Language": _ACCEPT_LANGUAGE,
    "Content-Type": "application/json; charset=utf-8",
    "Origin": WEBAUTH_BASE,
    "Referer": LOGIN_PAGE_URL,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}

DOWNSTREAM_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": _ACCEPT_HTML,
    "Accept-Language": _ACCEPT_LANGUAGE,
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}

API_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": _ACCEPT_JSON,
    "Accept-Language": _ACCEPT_LANGUAGE,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Origin": CS_BASE,
    "Referer": CS_BILLING_HOME,
}

# Headers for occaccountapi.southerncompany.com. Confirmed live (Sept 2026):
# Authorization bearer + userid + devicetype get a 200 from Cap/ and
# Accounts/{id}/Summary; Authorization is added per-call by the caller.
ACCOUNT_API_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": _ACCEPT_JSON,
    "Accept-Language": _ACCEPT_LANGUAGE,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Origin": CS_BASE,
    "Referer": CS_BILLING_HOME,
    "devicetype": "Desktop",
}
