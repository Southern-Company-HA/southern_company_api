import datetime
from unittest.mock import patch

import aiohttp
import pytest

from southern_company_api import Account, Company
from tests import MockResponse, test_get_hourly_usage, test_get_month_data


@pytest.mark.asyncio
async def test_can_create():
    async with aiohttp.ClientSession() as session:
        Account("sample", True, "1", Company.GPC, session)


@pytest.mark.asyncio
async def test_get_hourly_data():
    async with aiohttp.ClientSession() as session:
        acc = Account("sample", True, "1", Company.GPC, session)
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


@pytest.mark.asyncio
async def test_ga_power_get_monthly_data():
    async with aiohttp.ClientSession() as session:
        acc = Account("sample", True, "1", Company.GPC, session)
        with patch(
            "src.southern_company_api.account.aiohttp.ClientSession.get"
        ) as mock_get, patch(
            "southern_company_api.account.Account.get_service_point_number"
        ) as mock_get_service_point:
            mock_get.return_value = MockResponse("", 200, "", test_get_month_data)
            mock_get_service_point.return_value.__aenter__.return_value = ""
            month = await acc.get_month_data("dummy_jwt")
        assert month.total_kwh_used == 97.0
        assert month.dollars_to_date == 13.974766406622413
        assert month.average_daily_cost == 2.79
        assert month.average_daily_usage == 19.17
        assert month.projected_usage_high == 629.0
        assert month.projected_usage_low == 419.0
        assert month.projected_bill_amount_high == 91.0
        assert month.projected_bill_amount_low == 60.0
