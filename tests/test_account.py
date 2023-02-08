import datetime
from unittest.mock import patch

import pytest

from southern_company_api import Account, Company
from tests import MockResponse, test_get_hourly_usage


def test_can_create():
    Account("sample", True, "1", Company.GPC)


@pytest.mark.asyncio
async def test_get_hourly_data():
    acc = Account("sample", True, "1", Company.GPC)
    with patch(
        "src.southern_company_api.account.aiohttp.ClientSession.get"
    ) as mock_get, patch(
        "southern_company_api.account.Account.get_service_point_number"
    ) as mock_get_service_point:
        mock_get.return_value = MockResponse("", 200, "", test_get_hourly_usage)
        mock_get_service_point.return_value.__aenter__.return_value = ""
        await acc.get_hourly_data(
            datetime.datetime.now() - datetime.timedelta(days=3),
            datetime.datetime.now() - datetime.timedelta(days=2, hours=22),
            "dummy_jwt",
        )
        assert len(list(acc.hourly_data.values())) == 2
