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
from tests import ga_power_sample_account_response, ga_power_sample_sc_response


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
    with patch(
        "southern_company_api.parser.aiohttp.ClientResponse.json",
        return_value=ga_power_sample_sc_response,
    ):
        sca = SouthernCompanyAPI("", "")
        sca.request_token = "sample"
        response_token = await sca._get_sc_web_token()
        assert response_token == "sample_sc_token"


@pytest.mark.asyncio
async def test_get_sc_web_token_wrong_login():
    sca = SouthernCompanyAPI("user", "pass")
    with pytest.raises(InvalidLogin):
        await sca._get_sc_web_token()


# @pytest.mark.asyncio
# async def test_ga_power_get_secondary_sc_token():
#     with patch("southern_company_api.parser.aiohttp.ClientResponse") as mocked_client:
#         mocked_client.headers = ga_power_sample_second_swt_token
#         mocked_client.status = 200
#         sca = SouthernCompanyAPI("", "")
#         sca.sc = ""
#         token = await sca._get_secondary_sc_token()
#         assert token == "sample_sc_token"
#
#
# async def test_ga_power_get_secondary_jwt():
#     pass
#
#


@pytest.mark.asyncio
async def test_ga_power_get_accounts():
    with patch("src.southern_company_api.parser.aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.json.return_value = (
            ga_power_sample_account_response
        )
        mock_get.return_value.__aenter__.return_value.status = 200
        sca = SouthernCompanyAPI("", "")
        sca.jwt = "sample"
        response_token: typing.List[Account] = await sca.get_accounts()
        print(response_token)
        assert response_token[0].name == "Home Energy"
