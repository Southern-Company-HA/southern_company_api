from unittest.mock import patch

import pytest

from src.southern_company_api.parser import (
    SouthernCompanyAPI,
    get_request_verification_token,
)
from tests import ga_power_sample_sc_response


def test_can_create():
    SouthernCompanyAPI("user", "pass")


@pytest.mark.asyncio
async def test_get_request_verification_token():
    token = await get_request_verification_token()
    assert len(token) > 1


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
# async def test_ga_power_get_accounts():
#     pass
