import datetime
import json
import re
import typing
from typing import List

import aiohttp as aiohttp
from aiohttp import ClientSession, ContentTypeError

from southern_company_api.account import Account

from .company import COMPANY_MAP, Company
from .exceptions import (
    AccountFailure,
    CantReachSouthernCompany,
    InvalidLogin,
    NoJwtTokenFound,
    NoRequestTokenFound,
    NoScTokenFound,
)


async def get_request_verification_token(session: ClientSession) -> str:
    """
    Get the request verification token, which allows us to get a login session
    :return: the verification token
    """
    try:
        http_response = await session.get(
            "https://webauth.southernco.com/account/login"
        )
        login_page = await http_response.text()
        matches = re.findall(r'data-aft="(\S+)"', login_page)
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
        self._request_token_expiry: datetime.datetime = datetime.datetime.now()
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
        if (
            self._request_token is None
            or datetime.datetime.now() >= self._request_token_expiry
        ):
            self._request_token = await get_request_verification_token(self.session)
            self._request_token_expiry = datetime.datetime.now() + datetime.timedelta(
                hours=3
            )
        return self._request_token

    async def connect(self) -> None:
        """
        Connects to Southern company and gets all accounts
        """
        self._request_token = await get_request_verification_token(self.session)
        self._request_token_expiry = datetime.datetime.now() + datetime.timedelta(
            hours=3
        )
        self._sc = await self._get_sc_web_token()
        self._jwt = await self.get_jwt()
        self._accounts = await self.get_accounts()

    async def authenticate(self) -> bool:
        """Determines if you can authenticate with Southern Company with given login"""
        self._request_token = await get_request_verification_token(self.session)
        self._request_token_expiry = datetime.datetime.now() + datetime.timedelta(
            hours=3
        )
        self._sc = await self._get_sc_web_token()
        return True

    async def _get_sc_web_token(self) -> str:
        """Gets a sc_web_token which we get from a successful log in"""
        if await self.request_token is None:
            raise CantReachSouthernCompany("Request Token could not be refreshed")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "RequestVerificationToken": self._request_token,
        }

        data = {
            "username": self.username,
            "password": self.password,
            "targetPage": 1,
            "params": {"ReturnUrl": "null"},
        }

        async with self.session.post(
            "https://webauth.southernco.com/api/login", json=data, headers=headers
        ) as response:
            if response.status != 200:
                raise CantReachSouthernCompany()
            try:
                connection = await response.json()
            except (ContentTypeError, json.JSONDecodeError) as err:
                raise InvalidLogin from err
            if connection["statusCode"] == 500:
                raise InvalidLogin()
        sc_regex = re.compile(r"NAME='ScWebToken' value='(\S+.\S+.\S+)'", re.IGNORECASE)
        sc_data = sc_regex.search(connection["data"]["html"])
        self._sc_expiry = datetime.datetime.now() + datetime.timedelta(hours=3)
        if sc_data and sc_data.group(1):
            if "'>" in sc_data.group(1):
                return sc_data.group(1).split("'>")[0]
            else:
                return sc_data.group(1)
        else:
            self._sc = None
            raise NoScTokenFound("Login request did not return a sc token")

    async def _get_southern_jwt_cookie(self) -> str:
        # update to use property
        await self.authenticate()
        if await self.sc is None:
            raise CantReachSouthernCompany("Sc token cannot be refreshed")
        data = {"ScWebToken": self._sc}
        async with self.session.post(
            "https://customerservice2.southerncompany.com/Account/LoginComplete?"
            "ReturnUrl=null",
            data=data,
        ) as resp:
            # Checking for unsuccessful login
            if resp.status != 200:
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
        headers = {"Cookie": f"SouthernJwtCookie={swtoken}"}
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
        # We can get the exact expiration date from the jwt token, but I don't think it is needed. It should always be
        # greater than 3 hours.
        self._jwt_expiry = datetime.datetime.now() + datetime.timedelta(hours=3)
        return token

    async def get_accounts(self) -> List[Account]:
        if await self.jwt is None:
            raise CantReachSouthernCompany("Can't get jwt. Expired and not refreshed")
        headers = {"Authorization": f"bearer {self._jwt}"}
        async with self.session.get(
            "https://customerservice2api.southerncompany.com/api/account/"
            "getAllAccounts",
            headers=headers,
        ) as resp:
            if resp.status != 200:
                raise AccountFailure("failed to get accounts")
            try:
                account_json = await resp.json()
            except (ContentTypeError, json.JSONDecodeError) as err:
                try:
                    error_text = await resp.text()
                except aiohttp.ClientError:
                    error_text = err.msg
                raise CantReachSouthernCompany(
                    f"Incorrect mimetype while trying to get accounts. {error_text}"
                ) from err
            accounts = []
            for account in account_json["Data"]:
                accounts.append(
                    Account(
                        name=account["Description"],
                        primary=account["PrimaryAccount"] == "Y",
                        number=account["AccountNumber"],
                        company=COMPANY_MAP.get(account["Company"], Company.GPC),
                        session=self.session,
                    )
                )
        for account in accounts:
            await account.get_service_point_number(self._jwt)
        self._accounts = accounts
        return accounts
