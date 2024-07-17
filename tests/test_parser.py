# type: ignore
# For get_accounts jwt mock. looking for better solution.
import datetime
import typing
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from southern_company_api import Account
from src.southern_company_api.exceptions import (
    CantReachSouthernCompany,
    InvalidLogin,
    NoRequestTokenFound,
)
from src.southern_company_api.parser import (
    SouthernCompanyAPI,
    get_request_verification_token,
)
from tests import (
    MockResponse,
    ga_power_jwt_header,
    ga_power_sample_account_response,
    ga_power_sample_sc_response,
    ga_power_southern_jwt_cookie_header,
)


@pytest.mark.asyncio
async def test_can_create():
    async with aiohttp.ClientSession() as session:
        SouthernCompanyAPI("user", "pass", session)


@pytest.mark.asyncio
async def test_get_request_verification_token():
    async with aiohttp.ClientSession() as session:
        token = await get_request_verification_token(session)
        assert len(token) > 1


# @pytest.mark.asyncio
# async def test_get_request_verification_token_fail():
#     with pytest.raises(CantReachSouthernCompany):
#         with patch("aiohttp.ClientSession"):
#             await get_request_verification_token()
#
#
@pytest.mark.asyncio
async def test_get_request_verification_token_fail():
    with pytest.raises(CantReachSouthernCompany):
        await get_request_verification_token(AsyncMock(side_effect=Exception()))


@pytest.mark.asyncio
async def test_cant_find_request_token():
    with patch(
        "src.southern_company_api.parser.aiohttp.ClientResponse.text", return_value=""
    ):
        with pytest.raises(NoRequestTokenFound):
            async with aiohttp.ClientSession() as session:
                await get_request_verification_token(session)


@pytest.mark.asyncio
async def test_can_authenticate():
    with patch(
        "src.southern_company_api.parser.get_request_verification_token"
    ) as mock_get_request_verification_token, patch(
        "src.southern_company_api.parser.SouthernCompanyAPI._get_sc_web_token"
    ) as mock__get_sc_web_token:
        mock_get_request_verification_token.return_value = "fake_token"
        mock__get_sc_web_token.return_value = "fake_sc"
        async with aiohttp.ClientSession() as session:
            api = SouthernCompanyAPI("", "", session)
            result = await api.authenticate()
            assert result is True
            mock_get_request_verification_token.assert_called_once()
            mock__get_sc_web_token.assert_called_once()


@pytest.mark.asyncio
async def test_ga_power_get_sc_web_token():
    with patch(
        "southern_company_api.parser.aiohttp.ClientSession.post"
    ) as mock_post, patch("src.southern_company_api.parser.jwt.decode"):
        mock_post.return_value = MockResponse("", 200, "", ga_power_sample_sc_response)
        async with aiohttp.ClientSession() as session:
            sca = SouthernCompanyAPI("", "", session)
            sca._request_token = "sample"
            response_token = await sca._get_sc_web_token()
            assert response_token == "sample_sc_token"


@pytest.mark.asyncio
async def test_get_sc_web_token_wrong_login():
    async with aiohttp.ClientSession() as session:
        sca = SouthernCompanyAPI("user", "pass", session)
        with patch(
            "src.southern_company_api.parser.aiohttp.ClientSession.post"
        ) as mock_post:
            mock_post.return_value = MockResponse("", 200, "", {"statusCode": 500})
            with pytest.raises(InvalidLogin):
                await sca._get_sc_web_token()


@pytest.mark.asyncio
async def test_ga_power_get_jwt_cookie():
    with patch(
        "src.southern_company_api.parser.aiohttp.ClientSession.post"
    ) as mock_post, patch(
        "src.southern_company_api.parser.SouthernCompanyAPI.authenticate"
    ):
        mock_post.return_value = MockResponse(
            "", 302, ga_power_southern_jwt_cookie_header, ""
        )
        async with aiohttp.ClientSession() as session:
            sca = SouthernCompanyAPI("", "", session)
            sca._sc = ""
            sca._sc_expiry = datetime.datetime.now() + datetime.timedelta(hours=3)
            token = await sca._get_southern_jwt_cookie()
            assert token == "sample_cookie"


@pytest.mark.asyncio
async def test_ga_power_get_jwt():
    with patch(
        "src.southern_company_api.parser.aiohttp.ClientSession.get"
    ) as mock_get, patch(
        "src.southern_company_api.parser.SouthernCompanyAPI._get_southern_jwt_cookie"
    ) as mock_get_cookie, patch(
        "src.southern_company_api.parser.jwt.decode"
    ):
        mock_get.return_value = MockResponse("", 200, ga_power_jwt_header, "")
        mock_get_cookie.return_value.__aenter__.return_value = ""
        async with aiohttp.ClientSession() as session:
            sca = SouthernCompanyAPI("", "", session)
            token = await sca.get_jwt()
            assert token == "sample_jwt"


@pytest.mark.asyncio
async def test_ga_power_get_accounts():
    with patch(
        "src.southern_company_api.parser.aiohttp.ClientSession.get"
    ) as mock_get, patch(
        "src.southern_company_api.parser.Account.get_service_point_number"
    ):
        mock_get.return_value.__aenter__.return_value.json.return_value = (
            ga_power_sample_account_response
        )
        mock_get.return_value.__aenter__.return_value.status = 200

        @property
        async def mock_jwt(_foo_self: SouthernCompanyAPI) -> str:
            return ""

        with patch.object(SouthernCompanyAPI, "jwt", new=mock_jwt):
            async with aiohttp.ClientSession() as session:
                sca = SouthernCompanyAPI("", "", session)
                response_token: typing.List[Account] = await sca.get_accounts()
                assert response_token[0].name == "Home Energy"
                assert sca._accounts == response_token


@pytest.mark.asyncio
async def test_get_accounts_expired_jwt():
    with patch(
        "src.southern_company_api.parser.aiohttp.ClientSession.get"
    ) as mock_get, patch(
        "src.southern_company_api.parser.SouthernCompanyAPI.get_jwt"
    ) as mock_get_jwt, patch(
        "src.southern_company_api.parser.Account.get_service_point_number"
    ):
        mock_get.return_value.__aenter__.return_value.json.return_value = (
            ga_power_sample_account_response
        )
        mock_get.return_value.__aenter__.return_value.status = 200

        async with aiohttp.ClientSession() as session:
            sca = SouthernCompanyAPI("", "", session)
            sca._jwt = ""
            sca._jwt_expiry = datetime.datetime.now() - datetime.timedelta(hours=5)
            response_token: typing.List[Account] = await sca.get_accounts()
            assert response_token[0].name == "Home Energy"
            assert sca._accounts == response_token
            assert mock_get_jwt.call_count == 1
