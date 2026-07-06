from __future__ import annotations

import datetime
import json
import re
from typing import Any

import aiohttp

from .exceptions import (
    CantReachSouthernCompany,
    InvalidLogin,
    NoRequestTokenFound,
    UsageDataFailure,
)
from .nicor_account import (
    NicorBillingPeriod,
    NicorDailyUsage,
    NicorMeterInfo,
    NicorProjectedBill,
    NicorUsageHistory,
    parse_aspnet_date,
)

_WEEKEND_DAYS = frozenset({"Saturday", "Sunday"})


class NicorGasAPI:
    """API client for Nicor Gas (LDC=7) via the Southern Company customer portal."""

    _BASE_URL = "https://customerportal.southerncompany.com"
    _LDC = "7"

    def __init__(
        self, username: str, password: str, session: aiohttp.ClientSession
    ) -> None:
        self.username = username
        self.password = password
        self.session = session
        self._account_id: str | None = None

    async def connect(self) -> None:
        """Authenticate and establish an authenticated portal session."""
        token = await self._get_request_verification_token()
        await self._login(token)
        await self._complete_session()

    async def _get_request_verification_token(self) -> str:
        async with self.session.get(
            f"{self._BASE_URL}/User/Login",
            params={"LDC": self._LDC},
        ) as resp:
            if resp.status != 200:
                raise CantReachSouthernCompany(
                    f"Failed to load Nicor login page: {resp.status}"
                )
            html = await resp.text()

        # Handle either attribute order of the hidden <input>
        match = re.search(
            r'<input\b[^>]*\bname="__RequestVerificationToken"[^>]*\bvalue="([^"]+)"'
            r'|<input\b[^>]*\bvalue="([^"]+)"[^>]*\bname="__RequestVerificationToken"',
            html,
            re.IGNORECASE,
        )
        if not match:
            raise NoRequestTokenFound(
                "Could not find __RequestVerificationToken in Nicor login page"
            )
        return match.group(1) or match.group(2)

    async def _login(self, token: str) -> None:
        form_data = {
            "__RequestVerificationToken": token,
            "UserName": self.username,
            "Password": self.password,
            "RememberMe": "false",
            # The submit button name/value must be included for the server to
            # accept the form submission.
            "loginbtn": "Login",
        }
        login_headers = {
            "Referer": f"{self._BASE_URL}/User/Login?LDC={self._LDC}",
        }
        async with self.session.post(
            f"{self._BASE_URL}/User/Login",
            data=form_data,
            headers=login_headers,
            allow_redirects=False,
        ) as resp:
            if resp.status != 302:
                raise InvalidLogin(
                    f"Nicor login failed: expected 302 redirect, got {resp.status}"
                )

    async def _complete_session(self) -> None:
        async with self.session.get(f"{self._BASE_URL}/Account/AccountSummary") as resp:
            if resp.status != 200:
                raise CantReachSouthernCompany(
                    f"Failed to complete Nicor session: {resp.status}"
                )

    async def get_usage_history(self) -> NicorUsageHistory:
        """Fetch and parse the full usage history from the portal."""
        async with self.session.get(
            f"{self._BASE_URL}/MeterDataManagement/UsageHistory"
        ) as resp:
            if resp.status != 200:
                raise UsageDataFailure(
                    f"Failed to load Nicor usage history: {resp.status}"
                )
            html = await resp.text()

        account_match = re.search(
            r'<input\b[^>]*\bid="AccountID"[^>]*\bvalue="([^"]+)"'
            r'|<input\b[^>]*\bvalue="([^"]+)"[^>]*\bid="AccountID"',
            html,
            re.IGNORECASE,
        )
        if account_match:
            self._account_id = account_match.group(1) or account_match.group(2)

        vmodel_match = re.search(r"var vmodel = '(.+?)';", html, re.DOTALL)
        if not vmodel_match:
            raise UsageDataFailure("Could not find vmodel in Nicor usage history page")

        vmodel: dict[str, Any] = json.loads(vmodel_match.group(1))
        return _parse_usage_history(vmodel)


def _parse_portal_date(date_str: str) -> datetime.datetime:
    """Parse MM/DD/YYYY date strings from the Nicor portal."""
    return datetime.datetime.strptime(date_str, "%m/%d/%Y").replace(
        tzinfo=datetime.timezone.utc
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float, stripping currency symbols; return default on failure."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return default


def _optional_float(value: Any) -> float | None:
    """Convert value to float, stripping currency symbols; return None if absent or invalid."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_usage_history(vmodel: dict[str, Any]) -> NicorUsageHistory:
    billing_periods = [
        NicorBillingPeriod(
            date=_parse_portal_date(p["Date"]),
            meter_reading=_safe_float(p.get("MeterReading")),
            reading_details=str(p.get("ReadingDetails", "")),
            ccfs=_safe_float(p.get("CCfs")),
            therms=_safe_float(p.get("Therms")),
            days_used=int(p.get("DaysUsed", 0)),
        )
        for p in vmodel.get("UsageHistoryCollection", [])
    ]

    ami = vmodel.get("AMIUsageMData") or {}
    daily_usage: list[NicorDailyUsage] = []
    for period in ami.get("DailyUsage", []):
        billing_period = str(period.get("BillingPeriodDatesListKey", ""))
        dates = period.get("LabelsHDate", [])
        therms_list = period.get("DailyThermsList", [])
        costs_list = period.get("DailyCostsList", [])
        temps_list = period.get("DailyAvgTempData", [])
        weekday_list = period.get("WeekDayorWeekEnd", [])
        read_type_list = period.get("ReadType", [])
        meter_reads_list = period.get("MeterReads", [])

        for i, date_str in enumerate(dates):
            day_of_week = str(weekday_list[i]) if i < len(weekday_list) else ""
            daily_usage.append(
                NicorDailyUsage(
                    date=parse_aspnet_date(date_str),
                    therms=_safe_float(therms_list[i]) if i < len(therms_list) else 0.0,
                    cost=_safe_float(costs_list[i]) if i < len(costs_list) else 0.0,
                    avg_temp=(
                        _optional_float(temps_list[i]) if i < len(temps_list) else None
                    ),
                    day_of_week=day_of_week,
                    is_weekend=day_of_week in _WEEKEND_DAYS,
                    read_type=str(read_type_list[i]) if i < len(read_type_list) else "",
                    meter_read=(
                        _optional_float(meter_reads_list[i])
                        if i < len(meter_reads_list)
                        else None
                    ),
                    billing_period=billing_period,
                )
            )

    meter_info: NicorMeterInfo | None = None
    meter_collection = vmodel.get("MeterInformationCollection", [])
    if meter_collection:
        m = meter_collection[0]
        meter_info = NicorMeterInfo(
            meter_number=str(m["MeterNumber"]),
            meter_status=str(m["MeterStatus"]),
            next_read_date=_parse_portal_date(m["NextMeterRead"]),
        )

    projected_bill = NicorProjectedBill(
        usage=_optional_float(ami.get("projectedBillUsage")),
        low_amount=_optional_float(ami.get("lowRangeBillAmt")),
        high_amount=_optional_float(ami.get("highRangeBillAmt")),
    )

    return NicorUsageHistory(
        billing_periods=billing_periods,
        daily_usage=daily_usage,
        projected_bill=projected_bill,
        meter_info=meter_info,
    )
