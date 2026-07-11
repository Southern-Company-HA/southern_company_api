import datetime
import json
import logging
import re
import typing
from typing import Any, List, Optional
from urllib.parse import unquote

import aiohttp as aiohttp
import jwt
from aiohttp import ClientSession, ContentTypeError

from southern_company_api.account import Account

from .company import COMPANY_MAP, Company
from .exceptions import (
    CantReachSouthernCompany,
    EmailValidationRequired,
    InvalidLogin,
    NoJwtTokenFound,
    NoRequestTokenFound,
    NoScTokenFound,
)

_LOGGER = logging.getLogger(__name__)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_LOGIN_PAGE_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

_LOGIN_API_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json; charset=utf-8",
    "Origin": "https://webauth.southernco.com",
    "Referer": "https://webauth.southernco.com/account/login",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}

_DOWNSTREAM_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}

_JWT_RE = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_SC_ATTR_RE = re.compile(
    r"""name\s*=\s*['"]ScWebToken['"][^>]*?value\s*=\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)

EMAIL_VALIDATION_URL = (
    "https://customerservice2.southerncompany.com/MyProfile/LoginInfo"
)


def _extract_sc_token(connection: dict[str, Any]) -> Optional[str]:
    """Try every known location for the ScWebToken in the login response.

    The API can return the token in multiple forms:
    - ``data.html``: an auto-submitting form with a JWT-format ScWebToken
      (this is the one LoginComplete accepts).
    - ``data.token``: an opaque encrypted token (LoginComplete rejects
      this with 500).
    - ``data.returnUrlWithToken``: a URL containing the token as a query
      parameter.

    Prefer the JWT from ``data.html`` first, then fall back to the others.
    """
    data = connection.get("data") or {}

    html = data.get("html") or ""
    if isinstance(html, str) and html:
        attr_match = _SC_ATTR_RE.search(html)
        if attr_match:
            candidate = unquote(attr_match.group(1))
            if _JWT_RE.fullmatch(candidate):
                return candidate
        jwt_match = _JWT_RE.search(html)
        if jwt_match:
            return jwt_match.group(0)

    return_url = data.get("returnUrlWithToken")
    if isinstance(return_url, str) and return_url:
        url_match = re.search(
            r"ScWebToken=([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)",
            return_url,
        )
        if url_match:
            return url_match.group(1)
        jwt_match = _JWT_RE.search(return_url)
        if jwt_match:
            return jwt_match.group(0)

    token = data.get("token")
    if isinstance(token, str) and token.strip():
        decoded = unquote(token)
        if _JWT_RE.fullmatch(decoded) or len(decoded) > 100:
            return decoded

    return None


async def get_request_verification_token(session: ClientSession) -> str:
    """Get the request verification token from the login page with browser headers."""
    try:
        async with session.get(
            "https://webauth.southernco.com/account/login",
            headers=_LOGIN_PAGE_HEADERS,
        ) as http_response:
            if http_response.status != 200:
                raise CantReachSouthernCompany(
                    f"Login page returned {http_response.status}"
                )
            login_page = await http_response.text()
            matches = re.findall(r'data-aft="(\S+)"', login_page)
    except (CantReachSouthernCompany, NoRequestTokenFound):
        raise
    except Exception as error:
        raise CantReachSouthernCompany() from error
    if len(matches) < 1:
        raise NoRequestTokenFound()
    return matches[0]


class SouthernCompanyAPI:
    def __init__(self, username: str, password: str, session: ClientSession):
        self.session = session
        self.username = username
        self.password = password
        self._jwt: typing.Optional[str] = None
        self._jwt_expiry: datetime.datetime = datetime.datetime.now()
        self._sc: typing.Optional[str] = None
        self._sc_expiry = datetime.datetime.now()
        self._request_token: typing.Optional[str] = None
        self._accounts: List[Account] = []

    @property
    async def sc(self) -> str:
        if self._sc is None or datetime.datetime.now() >= self._sc_expiry:
            return await self._get_sc_web_token()
        return self._sc

    @property
    async def accounts(self) -> List[Account]:
        if len(self._accounts) == 0:
            return await self.get_accounts()
        return self._accounts

    @property
    async def jwt(self) -> str:
        if self._jwt is None or datetime.datetime.now() >= self._jwt_expiry:
            self._jwt = await self.get_jwt()
        return self._jwt

    @property
    async def request_token(self) -> str:
        if self._request_token is None:
            self._request_token = await get_request_verification_token(self.session)
        return self._request_token

    async def connect(self) -> None:
        """
        Connects to Southern company and gets all accounts
        """
        self._request_token = await get_request_verification_token(self.session)
        self._sc = await self._get_sc_web_token()
        self._jwt = await self.get_jwt()
        self._accounts = await self.get_accounts()

    async def authenticate(self) -> bool:
        """Determines if you can authenticate with Southern Company with given login"""
        self._request_token = await get_request_verification_token(self.session)
        self._sc = await self._get_sc_web_token()
        return True

    async def _get_sc_web_token(self) -> str:
        """Gets a sc_web_token which we get from a successful log in."""
        if self._request_token is None:
            self._request_token = await get_request_verification_token(self.session)

        headers = dict(_LOGIN_API_HEADERS)
        headers["RequestVerificationToken"] = self._request_token

        data = {
            "username": self.username,
            "password": self.password,
            "rememberUsername": False,
            "staySignedIn": False,
            "targetPage": 1,
            "params": {"ReturnUrl": "null"},
            "ScWebToken": "",
        }

        async with self.session.post(
            "https://webauth.southernco.com/api/login", json=data, headers=headers
        ) as response:
            if response.status != 200:
                raise CantReachSouthernCompany(
                    f"Login API returned status {response.status}"
                )
            try:
                connection = await response.json()
            except (ContentTypeError, json.JSONDecodeError) as err:
                try:
                    body = await response.text()
                except Exception:
                    body = ""
                preview = body[:200] if body else "(empty)"
                raise CantReachSouthernCompany(
                    f"Login API returned non-JSON response (Content-Type: "
                    f"{response.headers.get('Content-Type', 'unknown')}). "
                    f"Likely blocked by Southern Company bot detection (Imperva). "
                    f"Try accessing southernco.com from a browser on the same "
                    f"network. Response preview: {preview}"
                ) from err

        if not connection.get("isSuccess", False):
            status_code = connection.get("statusCode")
            result = (connection.get("data") or {}).get("result")
            error_msg = (connection.get("data") or {}).get("errorMessage") or ""
            _LOGGER.warning(
                "Southern Company login failed: statusCode=%s result=%s "
                "errorMessage=%s isSuccess=%s",
                status_code,
                result,
                error_msg,
                connection.get("isSuccess"),
            )

            if status_code == 500 or result == 2:
                raise InvalidLogin(
                    f"Invalid username/password (result={result}): {error_msg}"
                )
            if result == 3:
                raise InvalidLogin(
                    f"Password expired, must be changed on southernco.com: {error_msg}"
                )

            self._sc = None
            keys = sorted((connection.get("data") or {}).keys())
            raise NoScTokenFound(
                f"Login was not successful (statusCode={status_code}, "
                f"result={result}, data keys: {keys}): {error_msg}"
            )

        token = _extract_sc_token(connection)
        if token is None:
            self._sc = None
            keys = sorted((connection.get("data") or {}).keys())
            raise NoScTokenFound(
                f"Login request did not return a sc token (data keys: {keys})"
            )
        self._sc = token

        redirect = (connection.get("data") or {}).get("redirect") or ""
        if redirect and "validateemail" in redirect.lower():
            raise EmailValidationRequired(
                f"Email validation required. Visit {EMAIL_VALIDATION_URL}, "
                "validate your email address, then reconfigure this integration.",
                validation_url=EMAIL_VALIDATION_URL,
            )

        try:
            sc_decoded = jwt.decode(self._sc, options={"verify_signature": False})
            self._sc_expiry = datetime.datetime.fromtimestamp(sc_decoded["exp"])
        except (jwt.DecodeError, KeyError):
            self._sc_expiry = datetime.datetime.now() + datetime.timedelta(hours=1)
            _LOGGER.debug("ScWebToken is not a JWT; using 1-hour default expiry")
        return self._sc

    async def _get_southern_jwt_cookie(self) -> str:
        # update to use property
        if await self.sc is None:
            raise CantReachSouthernCompany("Sc token cannot be refreshed")
        data = {"ScWebToken": self._sc}
        headers = dict(_DOWNSTREAM_HEADERS)
        headers["Origin"] = "https://webauth.southernco.com"
        headers["Referer"] = "https://webauth.southernco.com/"
        async with self.session.post(
            "https://customerservice2.southerncompany.com/Account/LoginComplete?"
            "ReturnUrl=/Billing/Home",
            data=data,
            headers=headers,
            allow_redirects=False,
        ) as resp:
            # Checking for unsuccessful login
            if resp.status != 302:
                await self.authenticate()
                raise NoScTokenFound(
                    f"Failed to get secondary ScWebToken: {resp.status} "
                    f"{resp.headers} {data} sc_expiry: {self._sc_expiry}"
                )
            # Regex to parse JWT out of headers
            # NOTE: This used to be ScWebToken before 02/07/2023
            swtregex = re.compile(r"SouthernJwtCookie=(\S*);", re.IGNORECASE)
            # Parsing response header to get token
            swtcookies = resp.headers.get("set-cookie")
            if swtcookies:
                swtmatches = swtregex.search(swtcookies)

                # Checking for matches
                if swtmatches and swtmatches.group(1):
                    swtoken = swtmatches.group(1)
                else:
                    raise NoScTokenFound(
                        "Failed to get secondary ScWebToken: Could not find any "
                        "token matches in headers"
                    )
            else:
                raise NoScTokenFound(
                    "Failed to get secondary ScWebToken: No cookies were sent back."
                )
        return swtoken

    async def get_jwt(self) -> str:
        # Trading ScWebToken for Jwt
        swtoken = await self._get_southern_jwt_cookie()
        # Now fetch JWT after secondary ScWebToken
        # NOTE: This used to be ScWebToken before 02/07/2023
        headers = dict(_DOWNSTREAM_HEADERS)
        headers["Cookie"] = f"SouthernJwtCookie={swtoken}"
        headers["Referer"] = "https://customerservice2.southerncompany.com/Billing/Home"
        async with self.session.get(
            "https://customerservice2.southerncompany.com/Account/LoginValidated/"
            "JwtToken",
            headers=headers,
        ) as resp:
            if resp.status != 200:
                raise NoJwtTokenFound(
                    f"Failed to get JWT: {resp.status} {await resp.text()} "
                    f"{headers}"
                )
            # Regex to parse JWT out of headers
            regex = re.compile(r"ScJwtToken=(\S*);", re.IGNORECASE)

            # Parsing response header to get token
            cookies = resp.headers.get("set-cookie")
            if cookies:
                matches = regex.search(cookies)

                # Checking for matches
                if matches and matches.group(1):
                    token = matches.group(1)
                else:
                    raise NoJwtTokenFound(
                        "Failed to get JWT: Could not find any token matches in "
                        "headers"
                    )
            else:
                raise NoJwtTokenFound("Failed to get JWT: No cookies were sent back.")

        # Returning JWT
        self._jwt = token
        jwt_decoded = jwt.decode(self._jwt, options={"verify_signature": False})
        self._jwt_expiry = datetime.datetime.fromtimestamp(jwt_decoded["exp"])
        return token

    async def get_accounts(self) -> List[Account]:
        if await self.jwt is None:
            raise CantReachSouthernCompany(
                f"Can't get jwt. Expired and not refreshed jwt: {self._jwt}"
            )
        headers = dict(_DOWNSTREAM_HEADERS)
        headers["Authorization"] = f"bearer {self._jwt}"
        headers["Accept"] = "application/json, text/plain, */*"
        headers["Sec-Fetch-Dest"] = "empty"
        headers["Sec-Fetch-Mode"] = "cors"
        headers["Sec-Fetch-Site"] = "same-site"
        headers["Origin"] = "https://customerservice2.southerncompany.com"
        headers["Referer"] = "https://customerservice2.southerncompany.com/Billing/Home"
        async with self.session.get(
            "https://customerservice2api.southerncompany.com/api/account/"
            "getAllAccounts",
            headers=headers,
        ) as resp:
            if resp.status != 200:
                raise CantReachSouthernCompany(
                    f"Failed to get accounts: status {resp.status}"
                )
            try:
                account_json = await resp.json()
            except (ContentTypeError, json.JSONDecodeError) as err:
                try:
                    error_text = await resp.text()
                except aiohttp.ClientError:
                    error_text = str(err)
                raise CantReachSouthernCompany(
                    f"Incorrect mimetype while trying to get accounts. {error_text}"
                ) from err
            accounts = []
            try:
                account_list = account_json["Data"]
                for account in account_list:
                    accounts.append(
                        Account(
                            name=account["Description"],
                            primary=account["PrimaryAccount"] == "Y",
                            number=account["AccountNumber"],
                            company=COMPANY_MAP.get(account["Company"], Company.GPC),
                            session=self.session,
                        )
                    )
            except (KeyError, TypeError) as err:
                raise CantReachSouthernCompany(
                    f"Unexpected account data format: {err}"
                ) from err
        for account in accounts:
            await account.get_service_point_number(self._jwt)
        self._accounts = accounts
        return accounts
