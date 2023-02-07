import re
import typing
from typing import List

import aiohttp as aiohttp

from southern_company_api.account import Account

from .company import COMPANY_MAP, Company
from .exceptions import (
    AccountFailure,
    CantReachSouthernCompany,
    InvalidLogin,
    NoJwtTokenFound,
    NoScTokenFound,
)


async def get_request_verification_token() -> str:
    """
    Get the request verification token, which allows us to get a login session
    :return: the verification token
    """
    try:
        async with aiohttp.ClientSession() as session:
            http_response = await session.get(
                "https://webauth.southernco.com/account/login"
            )
            login_page = await http_response.text()
            matches = re.findall(r'data-aft="(\S+)"', login_page)
    except Exception as error:
        raise CantReachSouthernCompany() from error
    return matches[0]


class SouthernCompanyAPI:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.jwt: typing.Optional[str] = None
        self.sc: typing.Optional[str] = None
        self.request_token: typing.Optional[str] = None
        self.accounts: typing.Optional[List[Account]] = None

    async def connect(self) -> None:
        """
        Connects to Southern company and gets all accounts
        """
        self.request_token = await get_request_verification_token()
        self.sc = await self._get_sc_web_token()
        self.jwt = await self.get_jwt()
        self.accounts = await self.get_accounts()

    async def authenticate(self) -> bool:
        """Determines if you can authenticate with Southern Company with given login"""
        self.request_token = await get_request_verification_token()
        self.sc = await self._get_sc_web_token()
        return True

    async def _get_sc_web_token(self) -> str:
        """Gets a sc_web_token which we get from a successful log in"""
        if self.request_token is None:
            await get_request_verification_token()
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "RequestVerificationToken": self.request_token,
        }

        data = {
            "username": self.username,
            "password": self.password,
            "targetPage": 1,
            "params": {"ReturnUrl": "null"},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://webauth.southernco.com/api/login", json=data, headers=headers
            ) as response:
                connection = await response.json()
        if connection["statusCode"] == 500:
            raise InvalidLogin()
        sc_regex = re.compile(r"NAME='ScWebToken' value='(\S+.\S+.\S+)'", re.IGNORECASE)
        sc_data = sc_regex.search(connection["data"]["html"])
        if sc_data and sc_data.group(1):
            if "'>" in sc_data.group(1):
                return sc_data.group(1).split("'>")[0]
            else:
                return sc_data.group(1)
        else:
            raise NoScTokenFound("Login request did not return a sc token")

    async def _get_southern_jwt_cookie(self) -> str:
        if self.sc is None:
            await self._get_sc_web_token()
        data = {"ScWebToken": self.sc}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://customerservice2.southerncompany.com/Account/LoginComplete?"
                "ReturnUrl=null",
                data=data,
            ) as resp:
                # Checking for unsuccessful login
                if resp.status != 200:
                    raise NoScTokenFound(
                        f"Failed to get secondary ScWebToken: {resp.status} "
                        f"{resp.headers} {data}"
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
        async with aiohttp.ClientSession() as session:
            async with session.get(
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
                    raise NoJwtTokenFound(
                        "Failed to get JWT: No cookies were sent back."
                    )

        # Returning JWT
        self.jwt = token
        return token

    async def get_accounts(self) -> List[Account]:
        if self.jwt is None:
            await self.get_jwt()
        headers = {"Authorization": f"bearer {self.jwt}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://customerservice2api.southerncompany.com/api/account/"
                "getAllAccounts",
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    raise AccountFailure("failed to get accounts")
                account_json = await resp.json()
                accounts = []
                for account in account_json["Data"]:
                    accounts.append(
                        Account(
                            name=account["Description"],
                            primary=account["PrimaryAccount"] == "Y",
                            number=account["AccountNumber"],
                            company=COMPANY_MAP.get(account["Company"], Company.GPC),
                        )
                    )
        return accounts
