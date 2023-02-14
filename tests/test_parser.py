# type: ignore
# For get_accounts jwt mock. looking for better solution.
import typing
from unittest.mock import patch

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


def test_can_create():
    SouthernCompanyAPI("user", "pass")


@pytest.mark.asyncio
async def test_get_request_verification_token():
    token = await get_request_verification_token()
    assert len(token) > 1


@pytest.mark.asyncio
async def test_get_request_verification_token_fail():
    with pytest.raises(CantReachSouthernCompany):
        with patch(
            "src.southern_company_api.parser.aiohttp.ClientSession",
            side_effect=Exception(),
        ):
            await get_request_verification_token()


@pytest.mark.asyncio
async def test_cant_find_request_token():
    with patch(
        "src.southern_company_api.parser.aiohttp.ClientResponse.text", return_value=""
    ):
        with pytest.raises(NoRequestTokenFound):
            await get_request_verification_token()


@pytest.mark.asyncio
async def test_can_authenticate():
    with patch(
        "src.southern_company_api.parser.get_request_verification_token"
    ) as mock_get_request_verification_token, patch(
        "src.southern_company_api.parser.SouthernCompanyAPI._get_sc_web_token"
    ) as mock__get_sc_web_token:
        mock_get_request_verification_token.return_value = "fake_token"
        mock__get_sc_web_token.return_value = "fake_sc"
        api = SouthernCompanyAPI("", "")
        result = await api.authenticate()
        assert result is True
        mock_get_request_verification_token.assert_called_once()
        mock__get_sc_web_token.assert_called_once()


@pytest.mark.asyncio
async def test_ga_power_get_sc_web_token():
    with patch("southern_company_api.parser.aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse("", 200, "", ga_power_sample_sc_response)
        sca = SouthernCompanyAPI("", "")
        sca._request_token = "sample"
        response_token = await sca._get_sc_web_token()
        assert response_token == "sample_sc_token"


@pytest.mark.asyncio
async def test_get_sc_web_token_wrong_login():
    sca = SouthernCompanyAPI("user", "pass")
    with pytest.raises(InvalidLogin):
        await sca._get_sc_web_token()


@pytest.mark.asyncio
async def test_ga_power_get_jwt_cookie():
    with patch(
        "src.southern_company_api.parser.aiohttp.ClientSession.post"
    ) as mock_post:
        mock_post.return_value = MockResponse(
            "", 200, ga_power_southern_jwt_cookie_header, ""
        )
        sca = SouthernCompanyAPI("", "")
        sca._sc = ""
        token = await sca._get_southern_jwt_cookie()
        assert token == "sample_cookie"


@pytest.mark.asyncio
async def test_ga_power_get_jwt():
    with patch(
        "src.southern_company_api.parser.aiohttp.ClientSession.get"
    ) as mock_get, patch(
        "src.southern_company_api.parser.SouthernCompanyAPI._get_southern_jwt_cookie"
    ) as mock_get_cookie:
        mock_get.return_value = MockResponse("", 200, ga_power_jwt_header, "")
        mock_get_cookie.return_value.__aenter__.return_value = ""
        sca = SouthernCompanyAPI("", "")
        token = await sca.get_jwt()
        assert token == "sample_jwt"


@pytest.mark.asyncio
async def test_ga_power_get_accounts():
    with patch("src.southern_company_api.parser.aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.json.return_value = (
            ga_power_sample_account_response
        )
        mock_get.return_value.__aenter__.return_value.status = 200

        @property
        async def mock_jwt(_foo_self: SouthernCompanyAPI) -> str:
            return ""

        with patch.object(SouthernCompanyAPI, "jwt", new=mock_jwt):
            sca = SouthernCompanyAPI("", "")
            response_token: typing.List[Account] = await sca.get_accounts()
            assert response_token[0].name == "Home Energy"
            assert sca._accounts == response_token
