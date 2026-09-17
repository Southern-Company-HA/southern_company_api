import datetime
import json
from unittest.mock import patch

import aiohttp
import pytest

from southern_company_api import Account, Company
from tests import MockResponse


@pytest.mark.asyncio
async def test_can_create():
    async with aiohttp.ClientSession() as session:
        Account("sample", True, "1", Company.GPC, session)


SAMPLE_USAGE_IDS = {
    "serviceAgreementId": "CfDJ8-sample-agreement",
    "servicePointId": "CfDJ8-sample-point",
    "premiseId": "CfDJ8-sample-premise",
    "personId": "CfDJ8-sample-person",
    "operatingCompany": "GPC",
}


@pytest.mark.asyncio
async def test_get_service_point_number(datadir):
    account_summary = json.loads((datadir / "account_summary.json").read_text())
    async with aiohttp.ClientSession() as session:
        acc = Account("sample", True, "1", Company.GPC, session)
        with patch(
            "src.southern_company_api.account.aiohttp.ClientSession.get"
        ) as mock_get:
            mock_get.return_value = MockResponse("", 200, "", account_summary)
            service_point = await acc.get_service_point_number("dummy_jwt")
        # servicePointId lives in a sibling array, not inside the agreement
        assert service_point == "CfDJ8-sample-point"
        assert acc.usage_ids["serviceAgreementId"] == "CfDJ8-sample-agreement"
        assert acc.usage_ids["premiseId"] == "CfDJ8-sample-premise"
        assert acc.usage_ids["personId"] == "CfDJ8-sample-person"
        assert acc.usage_ids["operatingCompany"] == "GPC"


@pytest.mark.asyncio
async def test_get_service_point_number_picks_electric_agreement(datadir):
    """All ids must come from one agreement -- the electric one."""
    account_summary = json.loads((datadir / "account_summary_multi.json").read_text())
    async with aiohttp.ClientSession() as session:
        acc = Account("sample", True, "1", Company.GPC, session)
        with patch(
            "src.southern_company_api.account.aiohttp.ClientSession.get"
        ) as mock_get:
            mock_get.return_value = MockResponse("", 200, "", account_summary)
            service_point = await acc.get_service_point_number("dummy_jwt")
        # The lighting agreement is listed first and has its own premise and
        # service point; none of its ids may leak into the resolved set.
        assert acc.usage_ids["serviceAgreementId"] == "CfDJ8-electric-agreement"
        assert acc.usage_ids["premiseId"] == "CfDJ8-electric-premise"
        assert service_point == "CfDJ8-electric-point"


@pytest.mark.asyncio
async def test_get_hourly_data(datadir):
    test_get_hourly_usage = json.loads((datadir / "get_hourly_usage.json").read_text())
    async with aiohttp.ClientSession() as session:
        acc = Account("sample", True, "1", Company.GPC, session)
        acc.usage_ids = dict(SAMPLE_USAGE_IDS)
        with patch(
            "src.southern_company_api.account.aiohttp.ClientSession.get"
        ) as mock_get:
            mock_get.return_value = MockResponse("", 200, "", test_get_hourly_usage)
            await acc.get_hourly_data(
                datetime.datetime.now() - datetime.timedelta(days=3),
                datetime.datetime.now() - datetime.timedelta(days=2, hours=22),
                "dummy_jwt",
            )
            hours = acc.hourly_data
            assert len(hours) == 3
            # plain series wins over the delayed duplicate for the first hour
            assert hours["2023-02-04T22:50:11"].usage == 0.32
            # a delayed zero is "not reported yet", not a 0 kWh hour
            pending = hours["2023-02-05T00:50:11"]
            assert pending.usage is None and pending.cost is None
            assert pending.temp == 43.5


@pytest.mark.asyncio
async def test_ga_power_get_monthly_data(datadir):
    test_get_month_data = json.loads((datadir / "get_monthly_usage.json").read_text())
    async with aiohttp.ClientSession() as session:
        acc = Account("sample", True, "1", Company.GPC, session)
        acc.usage_ids = dict(SAMPLE_USAGE_IDS)
        with patch(
            "src.southern_company_api.account.aiohttp.ClientSession.get"
        ) as mock_get:
            mock_get.return_value = MockResponse("", 200, "", test_get_month_data)
            month = await acc.get_month_data("dummy_jwt")
        assert month.total_kwh_used == 97.0
        assert month.dollars_to_date == 13.974766406622413
        assert month.average_daily_cost == 2.79
        assert month.average_daily_usage == 19.17
        assert month.projected_usage_high == 629.0
        assert month.projected_usage_low == 419.0
        assert month.projected_bill_amount_high == 91.0
        assert month.projected_bill_amount_low == 60.0
