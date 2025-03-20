import datetime
import json
from unittest.mock import patch

import aiohttp
import pytest

from southern_company_api import Account, Company, exceptions
from tests import MockResponse


@pytest.mark.asyncio
async def test_can_create():
    async with aiohttp.ClientSession() as session:
        Account("sample", True, "1", Company.APC, session)


@pytest.mark.asyncio
async def test_apc_get_hourly_data(datadir):
    test_get_hourly_usage = json.loads((datadir / "get_hourly_usage.json").read_text())
    async with aiohttp.ClientSession() as session:
        acc = Account("sample", True, "1", Company.APC, session)
        with patch(
            "src.southern_company_api.account.aiohttp.ClientSession.get"
        ) as mock_get, patch(
            "southern_company_api.account.Account.get_service_point_number"
        ) as mock_get_service_point:
            with pytest.raises(exceptions.UsageDataFailure):
                mock_get.return_value = MockResponse("", 200, "", test_get_hourly_usage)
                mock_get_service_point.return_value.__aenter__.return_value = ""
                await acc.get_hourly_data(
                    datetime.datetime.now() - datetime.timedelta(days=3),
                    datetime.datetime.now() - datetime.timedelta(days=2, hours=22),
                    "dummy_jwt",
                )


@pytest.mark.asyncio
async def test_apc_get_monthly_data(datadir):
    test_get_month_data = json.loads((datadir / "get_monthly_usage.json").read_text())
    async with aiohttp.ClientSession() as session:
        acc = Account("sample", True, "1", Company.APC, session)
        with patch(
            "src.southern_company_api.account.aiohttp.ClientSession.get"
        ) as mock_get, patch(
            "southern_company_api.account.Account.get_service_point_number"
        ) as mock_get_service_point:
            mock_get.return_value = MockResponse("", 200, "", test_get_month_data)
            mock_get_service_point.return_value.__aenter__.return_value = ""
            month = await acc.get_month_data("dummy_jwt")
        assert month.total_kwh_used == pytest.approx(1588.0)
        assert month.dollars_to_date == pytest.approx(250.78)
        assert month.average_daily_cost == pytest.approx(8.65)
        assert month.average_daily_usage == pytest.approx(54.76)
        assert month.projected_usage_high == pytest.approx(0.0)
        assert month.projected_usage_low == pytest.approx(1588.0)
        assert month.projected_bill_amount_high == pytest.approx(0.0)
        assert month.projected_bill_amount_low == pytest.approx(250.78)
