import datetime as dt
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

import aiohttp
import pytest

from southern_company_api import (
    GEORGIA_RESIDENTIAL_R31,
    Account,
    BillSummary,
    Company,
    parse_georgia_power_bill_text,
)
from southern_company_api.billing import BillingPeriod
from southern_company_api.exceptions import UsageDataFailure
from southern_company_api.readings import reading_status
from tests import MockResponse

UTC = dt.timezone.utc
NY = ZoneInfo("America/New_York")
IDS = {
    "serviceAgreementId": "sample-agreement",
    "servicePointId": "sample-point",
    "premiseId": "sample-premise",
    "operatingCompany": "GPC",
}


def graph(labels, *, usage=None, cost=None, delayed=None):
    def points(values):
        return {"data": [{"name": k, "y": v} for k, v in values.items()]}

    return {
        "xAxis": {"labels": labels},
        "series": {
            "usage": points(usage if usage is not None else dict.fromkeys(labels, 1)),
            "cost": points(cost if cost is not None else dict.fromkeys(labels, 0.1)),
            "usageDelayed": points(delayed or {}),
            "costDelayed": points(delayed or {}),
        },
    }


def test_real_zero_is_complete_but_estimates_do_not_advance_status():
    labels = ["2026-10-21T22:00:00", "2026-10-21T23:00:00", "2026-10-22T00:00:00"]
    data = graph(
        labels,
        usage={labels[0]: 0},
        cost={labels[0]: 0},
        delayed={labels[1]: 4, labels[2]: 0},
    )
    status = reading_status(
        data, "hourly", NY, dt.datetime(2026, 10, 22, 12, tzinfo=UTC)
    )
    assert status.latest_complete_reading.isoformat() == "2026-10-21T22:00:00-04:00"
    assert status.latest_complete_day is None


def test_usage_and_cost_watermarks_are_independent():
    labels = ["2026-10-21T22:00:00", "2026-10-21T23:00:00"]
    status = reading_status(
        graph(labels, cost={labels[0]: 0.1}),
        "hourly",
        NY,
        dt.datetime(2026, 10, 22, 12, tzinfo=UTC),
    )
    assert status.latest_usage.hour == 23
    assert status.latest_cost.hour == status.latest_complete_reading.hour == 22


@pytest.mark.parametrize(
    "day,hours,complete",
    [
        ("2026-03-08", [0, 1, *range(3, 24)], True),
        ("2025-11-02", list(range(24)), False),
    ],
)
def test_dst_days_require_real_interval_coverage(day, hours, complete):
    labels = [f"{day}T{h:02}:00:00" for h in hours]
    now = dt.datetime.fromisoformat(day).replace(tzinfo=NY) + dt.timedelta(days=2)
    status = reading_status(graph(labels), "hourly", NY, now)
    assert (status.latest_complete_day == dt.date.fromisoformat(day)) is complete
    assert bool(status.ambiguous_labels) is (not complete)


def test_explicit_offsets_resolve_both_autumn_hours():
    labels = [f"2025-11-02T{h:02}:00:00-05:00" for h in range(2, 24)]
    labels[:0] = [
        "2025-11-02T00:00:00-04:00",
        "2025-11-02T01:00:00-04:00",
        "2025-11-02T01:00:00-05:00",
    ]
    status = reading_status(
        graph(labels), "hourly", NY, dt.datetime(2025, 11, 4, tzinfo=UTC)
    )
    assert not status.ambiguous_labels
    assert status.latest_complete_day == dt.date(2025, 11, 2)


def test_current_daily_zero_is_not_a_complete_day():
    labels = ["2026-10-21T00:00:00", "2026-10-22T00:00:00"]
    status = reading_status(
        graph(labels), "daily", NY, dt.datetime(2026, 10, 22, 16, tzinfo=UTC)
    )
    assert status.latest_complete_reading.date() == dt.date(2026, 10, 21)
    assert status.latest_complete_day == dt.date(2026, 10, 21)


def test_nonexistent_hour_is_rejected():
    with pytest.raises(UsageDataFailure, match="nonexistent"):
        reading_status(graph(["2026-03-08T02:00:00"]), "hourly", NY)


def test_period_boundaries_are_preserved_and_malformed_periods_fail():
    period = BillingPeriod.from_portal(
        {
            "key": "Oct 01 - Oct 30, 2026",
            "value": "10/01/2026 00:00:00;10/30/2026 00:00:00",
        }
    )
    assert period.start == dt.datetime(2026, 10, 1)
    assert period.end == dt.datetime(2026, 10, 30)
    for value in ["", "not dates", "10/30/2026 00:00:00;10/01/2026 00:00:00"]:
        with pytest.raises(UsageDataFailure):
            BillingPeriod.from_portal({"value": value})


def test_bill_summary_retains_zero_and_unknown_amounts():
    result = BillSummary.from_portal(
        {
            "totalAmountBilled": 0,
            "totalDue": 12.34,
            "totalNonServiceAmount": None,
            "lastBillDate": "2026-10-01",
            "billId": "private-reference",
        }
    )
    assert result.total_billed == Decimal("0")
    assert result.total_due == Decimal("12.34")
    assert result.non_service_amount is None
    assert "private-reference" not in repr(result)


def test_bill_table_reconciles_and_preserves_signed_credit():
    text = """Community Solar - Community Solar kWh 12.00
Community Solar - Net kWh 300.00
Current Service                        $ 100.00       Payment help
Community Solar Subscription 1 BLK * $24.00  24.00       Pay here
Environmental Compliance Cost             10.00
Municipal Franchise Fee                    4.00
Sales Tax                                  5.00
Adjustment Credit                          (3.00)
Total Current Electric Service $ 140.00
"""
    result = parse_georgia_power_bill_text(text)
    assert result.reconciled
    assert result.community_solar_kwh == Decimal("12.00")
    assert result.net_usage_kwh == Decimal("300.00")
    assert result.items[-1].amount == Decimal("-3.00")
    assert result.total == Decimal("140.00")
    incomplete = parse_georgia_power_bill_text(
        text.replace("Sales Tax                                  5.00\n", "")
    )
    assert not incomplete.reconciled
    with pytest.raises(UsageDataFailure):
        parse_georgia_power_bill_text("Unknown statement layout")


@pytest.mark.asyncio
async def test_verified_routes_and_rate_factor_are_used():
    async with aiohttp.ClientSession() as session:
        account = Account("sample", True, "sample-account", Company.GPC, session)
        account.usage_ids = IDS.copy()
        account.usage_ids_jwt = "jwt"
        data = {
            "status": True,
            "data": {
                "eligibilityCharacteristics": {
                    "rateScheduleCode": "G-R",
                    "billFactorCode": "factor",
                }
            },
        }
        with patch.object(
            session, "get", return_value=MockResponse("", 200, {}, data)
        ) as get:
            plan = await account.get_rate_plan("jwt")
            assert get.call_args.args[0].endswith(
                "EligibilityDetails/sample-agreement/GPC"
            )
        assert plan.rate_schedule_code == "G-R"
        start, end = dt.datetime(2026, 10, 1), dt.datetime(2026, 10, 22)
        assert account._usage_params(IDS, start, end)["billFactorCode"] == "factor"
        data = {
            "status": True,
            "data": [{"value": "10/01/2026 00:00:00;10/30/2026 00:00:00"}],
        }
        with patch.object(
            session, "get", return_value=MockResponse("", 200, {}, data)
        ) as get:
            periods = await account.get_billing_periods(start, end, "jwt")
            assert periods[0].end.day == 30
            assert (
                get.call_args.kwargs["params"]["ServiceAgreementId"]
                == "sample-agreement"
            )
        account.usage_ids_jwt = "other-jwt"
        assert account._usage_params(IDS, start, end)["billFactorCode"] == "null"


@pytest.mark.asyncio
async def test_billing_errors_do_not_expose_response_contents():
    async with aiohttp.ClientSession() as session:
        account = Account("sample", True, "sample-account", Company.GPC, session)
        for status, data in [
            (403, {}),
            (200, {"status": False, "data": {}}),
            (200, {"data": []}),
        ]:
            with patch.object(
                session,
                "get",
                return_value=MockResponse("private-body", status, {}, data),
            ):
                with pytest.raises(UsageDataFailure) as error:
                    await account.get_bill_summary("private-token")
                assert "private" not in str(error.value)


def test_tariff_uses_decimal_dollars_and_explicit_billing_months():
    tariff = GEORGIA_RESIDENTIAL_R31
    assert tariff.effective_billing_month == dt.date(2026, 6, 1)
    assert tariff.summer_billing_months == (6, 7, 8, 9)
    assert tariff.summer_tiers[0].dollars_per_kwh == Decimal("0.087738")
    assert tariff.summer_tiers[1].up_to_kwh == 1000
    assert tariff.time_of_use is False


@pytest.mark.asyncio
async def test_pdf_download_requires_a_valid_document_and_uses_selected_bill():
    class BinaryResponse(MockResponse):
        async def read(self):
            return self._text

    summary = BillSummary.from_portal(
        {"lastBillDate": "2026-10-01", "billId": "sample-bill"}
    )
    async with aiohttp.ClientSession() as session:
        account = Account("sample", True, "sample-account", Company.GPC, session)
        with patch.object(
            session,
            "get",
            return_value=BinaryResponse(b"%PDF-1.7\nsample", 200, {}, {}),
        ) as get:
            assert (await account.get_bill_pdf(summary, "jwt")).startswith(b"%PDF-")
            assert get.call_args.kwargs["params"] == {
                "accountId": "sample-account",
                "billId": "sample-bill",
                "billDate": "2026-10-01",
            }
        for status, body in [
            (200, b"<html>Login required</html>"),
            (403, b"private error"),
        ]:
            with patch.object(
                session, "get", return_value=BinaryResponse(body, status, {}, {})
            ):
                with pytest.raises(UsageDataFailure):
                    await account.get_bill_pdf(summary, "jwt")
        with pytest.raises(UsageDataFailure):
            await account.get_bill_pdf(BillSummary.from_portal({}), "jwt")


@pytest.mark.asyncio
async def test_hourly_parser_marks_estimates_and_ambiguous_hours():
    labels = ["2025-11-02T01:00:00", "2025-11-02T02:00:00"]
    data = graph(
        labels, usage={labels[0]: 1.2}, cost={labels[0]: 0.2}, delayed={labels[1]: 0.3}
    )
    async with aiohttp.ClientSession() as session:
        account = Account("sample", True, "sample-account", Company.GPC, session)
        with patch.object(account, "_usage_graph_data", return_value={"data": data}):
            rows = await account.get_hourly_data(
                dt.datetime(2025, 11, 2), dt.datetime(2025, 11, 3), "jwt"
            )
        assert rows[0].timestamp_ambiguous
        assert rows[1].usage_estimated and rows[1].cost_estimated
        assert account.hourly_status.latest_complete_reading is None
        assert rows[1].time.utcoffset() == dt.timedelta(hours=-5)
