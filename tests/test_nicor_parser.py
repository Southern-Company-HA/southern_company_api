import datetime
import json
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from southern_company_api.exceptions import (
    CantReachSouthernCompany,
    InvalidLogin,
    NoRequestTokenFound,
    UsageDataFailure,
)
from southern_company_api.nicor_account import NicorUsageHistory, parse_aspnet_date
from southern_company_api.nicor_parser import NicorGasAPI, _parse_usage_history
from tests import MockResponse

_LOGIN_PAGE_HTML = """
<html><body>
<form method="post" action="/User/Login">
  <input name="__RequestVerificationToken" type="hidden" value="test_token_abc" />
  <input name="UserName" type="text" />
  <input name="Password" type="password" />
  <input type="submit" name="loginbtn" value="Login" />
</form>
</body></html>
"""

_LOGIN_PAGE_HTML_VALUE_FIRST = """
<html><body>
<input value="test_token_xyz" name="__RequestVerificationToken" type="hidden" />
</body></html>
"""


def _make_usage_history_html(vmodel_json: str) -> str:
    return (
        '<html><body>'
        '<input type="hidden" id="AccountID" value="99999" />'
        '<script>var vmodel = \'' + vmodel_json + '\';</script>'
        '</body></html>'
    )


# --- parse_aspnet_date ---

def test_parse_aspnet_date_epoch():
    dt = parse_aspnet_date("/Date(0)/")
    assert dt == datetime.datetime(1970, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)


def test_parse_aspnet_date_known():
    dt = parse_aspnet_date("/Date(1699315200000)/")
    assert dt == datetime.datetime(2023, 11, 7, 0, 0, 0, tzinfo=datetime.timezone.utc)


def test_parse_aspnet_date_invalid():
    with pytest.raises(ValueError):
        parse_aspnet_date("not-a-date")


# --- _parse_usage_history ---

def test_parse_usage_history_billing_periods(datadir):
    vmodel = json.loads((datadir / "vmodel.json").read_text())
    history = _parse_usage_history(vmodel)

    assert isinstance(history, NicorUsageHistory)
    assert len(history.billing_periods) == 2

    first = history.billing_periods[0]
    assert first.therms == pytest.approx(11.025)
    assert first.ccfs == pytest.approx(10.5)
    assert first.days_used == 30
    assert first.meter_reading == pytest.approx(12345.0)
    assert first.reading_details == "Actual"
    assert first.date == datetime.datetime(2023, 11, 7, 0, 0, 0)


def test_parse_usage_history_daily_usage(datadir):
    vmodel = json.loads((datadir / "vmodel.json").read_text())
    history = _parse_usage_history(vmodel)

    assert len(history.daily_usage) == 3

    day0 = history.daily_usage[0]
    assert day0.therms == pytest.approx(0.8)
    assert day0.cost == pytest.approx(1.50)
    assert day0.avg_temp == pytest.approx(45.0)
    assert day0.day_of_week == "Monday"
    assert day0.is_weekend is False
    assert day0.read_type == "ACTUAL"
    assert day0.meter_read == pytest.approx(12300.0)
    assert day0.billing_period == "10/7/23-11/7/23"
    assert day0.date == datetime.datetime(2023, 11, 6, 0, 0, 0, tzinfo=datetime.timezone.utc)

    day1 = history.daily_usage[1]
    assert day1.day_of_week == "Tuesday"
    assert day1.is_weekend is False

    day2 = history.daily_usage[2]
    assert day2.day_of_week == "Saturday"
    assert day2.is_weekend is True
    assert day2.avg_temp is None
    assert day2.meter_read is None
    assert day2.read_type == "ESTIMATED"


def test_parse_usage_history_projected_bill(datadir):
    vmodel = json.loads((datadir / "vmodel.json").read_text())
    history = _parse_usage_history(vmodel)

    assert history.projected_bill.usage == pytest.approx(45.0)
    assert history.projected_bill.low_amount == pytest.approx(60.0)
    assert history.projected_bill.high_amount == pytest.approx(80.0)


def test_parse_usage_history_projected_bill_none():
    history = _parse_usage_history({"AMIUsageMData": {}})
    assert history.projected_bill.usage is None
    assert history.projected_bill.low_amount is None
    assert history.projected_bill.high_amount is None


def test_parse_usage_history_meter_info(datadir):
    vmodel = json.loads((datadir / "vmodel.json").read_text())
    history = _parse_usage_history(vmodel)

    assert history.meter_info is not None
    assert history.meter_info.meter_number == "98765432"
    assert history.meter_info.meter_status == "On"
    assert history.meter_info.next_read_date == datetime.datetime(2023, 12, 7, 0, 0, 0)


def test_parse_usage_history_empty():
    history = _parse_usage_history({})
    assert history.billing_periods == []
    assert history.daily_usage == []
    assert history.meter_info is None
    assert history.projected_bill.usage is None


# --- NicorGasAPI ---

@pytest.mark.asyncio
async def test_nicor_can_create():
    async with aiohttp.ClientSession() as session:
        NicorGasAPI("user", "pass", session)


@pytest.mark.asyncio
async def test_nicor_get_request_verification_token():
    async with aiohttp.ClientSession() as session:
        api = NicorGasAPI("user", "pass", session)
        with patch(
            "southern_company_api.nicor_parser.aiohttp.ClientSession.get"
        ) as mock_get:
            mock_get.return_value = MockResponse(_LOGIN_PAGE_HTML, 200, {}, {})
            token = await api._get_request_verification_token()
            assert token == "test_token_abc"


@pytest.mark.asyncio
async def test_nicor_get_request_verification_token_value_first():
    async with aiohttp.ClientSession() as session:
        api = NicorGasAPI("user", "pass", session)
        with patch(
            "southern_company_api.nicor_parser.aiohttp.ClientSession.get"
        ) as mock_get:
            mock_get.return_value = MockResponse(
                _LOGIN_PAGE_HTML_VALUE_FIRST, 200, {}, {}
            )
            token = await api._get_request_verification_token()
            assert token == "test_token_xyz"


@pytest.mark.asyncio
async def test_nicor_get_request_verification_token_not_found():
    async with aiohttp.ClientSession() as session:
        api = NicorGasAPI("user", "pass", session)
        with patch(
            "southern_company_api.nicor_parser.aiohttp.ClientSession.get"
        ) as mock_get:
            mock_get.return_value = MockResponse("<html><body></body></html>", 200, {}, {})
            with pytest.raises(NoRequestTokenFound):
                await api._get_request_verification_token()


@pytest.mark.asyncio
async def test_nicor_login_success():
    async with aiohttp.ClientSession() as session:
        api = NicorGasAPI("user", "pass", session)
        with patch(
            "southern_company_api.nicor_parser.aiohttp.ClientSession.post"
        ) as mock_post:
            mock_post.return_value = MockResponse("", 302, {}, {})
            await api._login("token")


@pytest.mark.asyncio
async def test_nicor_login_failure():
    async with aiohttp.ClientSession() as session:
        api = NicorGasAPI("user", "pass", session)
        with patch(
            "southern_company_api.nicor_parser.aiohttp.ClientSession.post"
        ) as mock_post:
            mock_post.return_value = MockResponse("", 200, {}, {})
            with pytest.raises(InvalidLogin):
                await api._login("token")


@pytest.mark.asyncio
async def test_nicor_complete_session_success():
    async with aiohttp.ClientSession() as session:
        api = NicorGasAPI("user", "pass", session)
        with patch(
            "southern_company_api.nicor_parser.aiohttp.ClientSession.get"
        ) as mock_get:
            mock_get.return_value = MockResponse("", 200, {}, {})
            await api._complete_session()


@pytest.mark.asyncio
async def test_nicor_complete_session_failure():
    async with aiohttp.ClientSession() as session:
        api = NicorGasAPI("user", "pass", session)
        with patch(
            "southern_company_api.nicor_parser.aiohttp.ClientSession.get"
        ) as mock_get:
            mock_get.return_value = MockResponse("", 302, {}, {})
            with pytest.raises(CantReachSouthernCompany):
                await api._complete_session()


@pytest.mark.asyncio
async def test_nicor_connect():
    async with aiohttp.ClientSession() as session:
        api = NicorGasAPI("user", "pass", session)
        api._get_request_verification_token = AsyncMock(return_value="tok")
        api._login = AsyncMock()
        api._complete_session = AsyncMock()
        await api.connect()
        api._get_request_verification_token.assert_called_once()
        api._login.assert_called_once_with("tok")
        api._complete_session.assert_called_once()


@pytest.mark.asyncio
async def test_nicor_get_usage_history(datadir):
    vmodel = json.loads((datadir / "vmodel.json").read_text())
    html = _make_usage_history_html(json.dumps(vmodel))
    async with aiohttp.ClientSession() as session:
        api = NicorGasAPI("user", "pass", session)
        with patch(
            "southern_company_api.nicor_parser.aiohttp.ClientSession.get"
        ) as mock_get:
            mock_get.return_value = MockResponse(html, 200, {}, {})
            history = await api.get_usage_history()
            assert api._account_id == "99999"
            assert len(history.billing_periods) == 2
            assert len(history.daily_usage) == 3


@pytest.mark.asyncio
async def test_nicor_get_usage_history_no_vmodel():
    async with aiohttp.ClientSession() as session:
        api = NicorGasAPI("user", "pass", session)
        with patch(
            "southern_company_api.nicor_parser.aiohttp.ClientSession.get"
        ) as mock_get:
            mock_get.return_value = MockResponse("<html><body></body></html>", 200, {}, {})
            with pytest.raises(UsageDataFailure):
                await api.get_usage_history()


@pytest.mark.asyncio
async def test_nicor_get_usage_history_bad_status():
    async with aiohttp.ClientSession() as session:
        api = NicorGasAPI("user", "pass", session)
        with patch(
            "southern_company_api.nicor_parser.aiohttp.ClientSession.get"
        ) as mock_get:
            mock_get.return_value = MockResponse("", 403, {}, {})
            with pytest.raises(UsageDataFailure):
                await api.get_usage_history()
