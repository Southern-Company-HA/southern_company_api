import dataclasses
import datetime
import json
import logging
import math
from typing import Any, Dict, List, Mapping, Optional

import aiohttp
from aiohttp import ContentTypeError

from ._helpers import (
    company_from,
    deep_find,
    first,
    graph_labels,
    series_points,
    unwrap,
)
from .company import Company
from .constants import (
    ACCOUNT_SUMMARY_URL,
    API_HEADERS,
    USAGE_GRAPH_DATA_URL,
)
from .exceptions import CantReachSouthernCompany, UsageDataFailure

_LOGGER = logging.getLogger(__name__)


def _is_electric(agreement: Mapping[str, Any]) -> bool:
    """Whether a service agreement is the electric one.

    Accounts can carry several agreements -- outdoor lighting, solar, a second
    premise -- and only the electric one has usage data behind it.
    """
    type_code = str(first(agreement, "serviceTypeCode", default="")).strip().lower()
    type_name = str(
        first(
            agreement, "serviceAgreementType", "serviceSubTypeDescription", default=""
        )
    ).lower()
    return type_code == "e" or "electric" in type_name


def _select_service_agreement(
    summary: Mapping[str, Any],
) -> Optional[Mapping[str, Any]]:
    """Pick the agreement whose ids the usage endpoints should be keyed on.

    Prefers active electric agreements, then any active one, then anything at
    all, and warns when the choice is ambiguous so a wrong pick is visible in
    the log rather than silently producing another account's numbers.
    """
    agreements = first(summary, "serviceAgreements") or []
    if not isinstance(agreements, list):
        return None
    usable = [entry for entry in agreements if isinstance(entry, Mapping)]
    active = [entry for entry in usable if first(entry, "isActive") is not False]
    candidates = [entry for entry in active if _is_electric(entry)] or active or usable
    if not candidates:
        return None
    if len(candidates) > 1:
        _LOGGER.warning(
            "Found %d candidate service agreements; using the first (%s). "
            "Open an issue with your account layout if usage data looks wrong",
            len(candidates),
            first(candidates[0], "serviceSubTypeDescription", "serviceAgreementType"),
        )
    return candidates[0]


@dataclasses.dataclass
class DailyEnergyUsage:
    date: datetime.datetime
    # A series can be absent for a given day (missing read, no temperature
    # data), which the previous implementation also surfaced as None -- the
    # annotations just did not say so. Matches HourlyEnergyUsage.
    usage: Optional[float]
    cost: Optional[float]
    low_temp: Optional[float]
    high_temp: Optional[float]


@dataclasses.dataclass
class HourlyEnergyUsage:
    time: datetime.datetime
    usage: Optional[float]
    cost: Optional[float]
    temp: Optional[float]


@dataclasses.dataclass
class MonthlyUsage:
    dollars_to_date: float
    total_kwh_used: float
    average_daily_usage: float
    average_daily_cost: float
    projected_usage_low: float
    projected_usage_high: float
    projected_bill_amount_low: float
    projected_bill_amount_high: float


class DailyEnergyUsageList:
    def __init__(self, data: Mapping[str, Any]):
        self.data = data

    def usage(self) -> List[DailyEnergyUsage]:
        cost = series_points(self.data, "cost")
        usage = series_points(self.data, "usage")
        high_temps = series_points(self.data, "hightemp")
        low_temps = series_points(self.data, "lowtemp")

        days = [
            DailyEnergyUsage(
                # TODO: Determine timezone
                date=datetime.datetime.strptime(date, "%Y-%m-%dT%H:%M:%S"),
                usage=usage.get(date),
                cost=cost.get(date),
                low_temp=low_temps.get(date),
                high_temp=high_temps.get(date),
            )
            for date in graph_labels(self.data)
        ]
        return days


class Account:
    def __init__(
        self,
        name: str,
        primary: bool,
        number: str,
        company: Company,
        session: aiohttp.ClientSession,
    ):
        self.name = name
        self.primary = primary
        self.number = number
        self.company = company
        self.hourly_data: Dict[str, HourlyEnergyUsage] = {}
        self.daily_data: Dict[str, DailyEnergyUsage] = {}
        self.session = session
        self.service_point_number: Optional[str] = None
        # Opaque, session-scoped ids the usage endpoints are keyed on. Filled by
        # get_service_point_number(); see _usage_params for how they are used.
        self.usage_ids: Dict[str, Any] = {}

    def _headers(self, jwt: str) -> Dict[str, str]:
        headers = dict(API_HEADERS)
        headers["Authorization"] = f"Bearer {jwt}"
        return headers

    async def get_service_point_number(self, jwt: str) -> str:
        """Resolve this account's service point via the account summary.

        The summary is also the only source of the opaque ``CfDJ8...`` ids
        (service agreement, service point, premise) and the person id that every
        usage request needs, so they are cached on the account here. They are
        session-scoped, so they are refreshed whenever this is called rather
        than persisted.
        """
        try:
            async with self.session.get(
                ACCOUNT_SUMMARY_URL.format(account=self.number),
                headers=self._headers(jwt),
            ) as resp:
                if resp.status != 200:
                    raise CantReachSouthernCompany(
                        f"Failed to get account summary: status {resp.status}"
                    )
                try:
                    response = await resp.json()
                except (ContentTypeError, json.JSONDecodeError) as err:
                    raise CantReachSouthernCompany(
                        f"Incorrect mimetype while trying to get account summary. "
                        f"status:{resp.status} "
                        f"content_type:{resp.headers.get('Content-Type')}"
                    ) from err
        except aiohttp.ClientConnectorError as err:
            raise CantReachSouthernCompany("Failed to connect to api") from err

        try:
            summary = unwrap(response, "account summary")
        except KeyError as err:
            raise CantReachSouthernCompany(str(err)) from err

        # Resolve every id from ONE agreement. Searching the whole document per
        # id can pair a service agreement with another agreement's premise.
        agreement = _select_service_agreement(summary)
        if agreement is None:
            _LOGGER.warning(
                "No service agreement for account ending %s; "
                "monthly/hourly stats unavailable",
                str(self.number)[-4:],
            )
            self.usage_ids = {}
            self.service_point_number = ""
            return ""

        # The service point usually lives in a top-level servicePoints[] array
        # rather than inside the agreement, so fall back to it explicitly.
        service_point = deep_find(agreement, "servicePointId")
        if not service_point:
            service_point = deep_find(first(summary, "servicePoints"), "servicePointId")

        ids = {
            "serviceAgreementId": first(agreement, "serviceAgreementId"),
            "servicePointId": service_point,
            "premiseId": first(agreement, "premiseId"),
            "personId": first(summary, "mainPersonId", "personId"),
            "operatingCompany": company_from(
                first(summary, "divisionCode", "operatingCompany"), self.company
            ).name,
        }

        if not ids["serviceAgreementId"] or not ids["servicePointId"]:
            _LOGGER.warning(
                "Could not resolve usage ids for account ending %s; "
                "monthly/hourly stats unavailable. Resolved: %s",
                str(self.number)[-4:],
                {key: bool(value) for key, value in ids.items()},
            )
            self.usage_ids = {}
            self.service_point_number = ""
            return ""

        self.usage_ids = ids
        self.service_point_number = str(ids["servicePointId"])
        return self.service_point_number

    async def _usage_ids(self, jwt: str) -> Dict[str, Any]:
        if not self.usage_ids.get("serviceAgreementId"):
            await self.get_service_point_number(jwt)
        if not self.usage_ids.get("serviceAgreementId"):
            raise UsageDataFailure(
                f"No service agreement for account ending {str(self.number)[-4:]}"
            )
        return self.usage_ids

    def _usage_params(
        self,
        ids: Dict[str, Any],
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> Dict[str, Any]:
        return {
            "accountId": self.number,
            "personId": ids.get("personId") or "",
            "operatingCompany": ids.get("operatingCompany") or self.company.name,
            "startDate": start_date.strftime("%m/%d/%Y"),
            "endDate": end_date.strftime("%m/%d/%Y"),
            "servicePointId": ids.get("servicePointId") or "",
            "premiseId": ids.get("premiseId") or "",
            "billFactorCode": "null",
        }

    async def _usage_graph_data(
        self,
        jwt: str,
        granularity: str,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> Mapping[str, Any]:
        """GET one UsageGraphData payload and return its unwrapped body."""
        ids = await self._usage_ids(jwt)
        params = self._usage_params(ids, start_date, end_date)
        params.update(extra_params or {})
        what = f"{granularity.lower()} data"
        async with self.session.get(
            USAGE_GRAPH_DATA_URL.format(
                agreement=ids["serviceAgreementId"], granularity=granularity
            ),
            headers=self._headers(jwt),
            params=params,
        ) as resp:
            if resp.status != 200:
                raise UsageDataFailure(f"Failed to get {what}: {resp.status}")
            try:
                response = await resp.json()
            except (ContentTypeError, json.JSONDecodeError) as err:
                try:
                    error_text = await resp.text()
                except aiohttp.ClientError:
                    error_text = str(err)
                raise CantReachSouthernCompany(
                    f"Incorrect mimetype while trying to get {what}. {error_text}"
                ) from err
        try:
            payload = unwrap(response, what)
        except KeyError as err:
            raise UsageDataFailure(str(err)) from err
        if not isinstance(payload, Mapping):
            raise UsageDataFailure(f"Unexpected {what} payload: {type(payload)}")
        return payload

    async def get_daily_data(
        self, start_date: datetime.datetime, end_date: datetime.datetime, jwt: str
    ) -> List[DailyEnergyUsage]:
        """Available 24 hours after"""
        payload = await self._usage_graph_data(
            jwt,
            "Daily",
            start_date,
            end_date,
            {"intervalBehavior": "Automatic"},
        )
        days = DailyEnergyUsageList(payload.get("data") or {}).usage()
        self.daily_data = {str(day.date): day for day in days}
        return days

    async def get_hourly_data(
        self, start_date: datetime.datetime, end_date: datetime.datetime, jwt: str
    ) -> List[HourlyEnergyUsage]:
        """Available 48 hours after"""
        if (end_date - start_date).days > 35:
            number_of_chunks = math.ceil((end_date - start_date).days / 34)
            cur_date = start_date
            return_data = []
            for i in range(number_of_chunks):
                # TODO: Find start date of service and user that to make sure we don't try to get data from before
                #  an account was made
                window_end = min(cur_date + datetime.timedelta(days=34), end_date)
                try:
                    return_data.extend(
                        await self.get_hourly_data(cur_date, window_end, jwt)
                    )
                except UsageDataFailure as err:
                    # One empty window is normal (before service started, or a
                    # gap in published reads); log it so a partial backfill is
                    # distinguishable from a complete one.
                    _LOGGER.debug(
                        "No hourly data for %s..%s: %s",
                        cur_date.date(),
                        window_end.date(),
                        err,
                    )
                cur_date = window_end
                if cur_date >= end_date:
                    break
            return return_data

        payload = await self._usage_graph_data(
            jwt,
            "Hourly",
            start_date,
            end_date,
            {"intervalBehavior": "Automatic"},
        )
        graph = payload.get("data") or {}
        cost = series_points(graph, "cost")
        usage = series_points(graph, "usage")
        temp = series_points(graph, "temp")

        return_dates = []
        for date in graph_labels(graph):
            # TODO: Determine timezone
            parsed_date = datetime.datetime.strptime(date, "%Y-%m-%dT%H:%M:%S")
            parsed_date = parsed_date.replace(
                tzinfo=datetime.timezone(datetime.timedelta(hours=-5), "EST")
            )
            self.hourly_data[date] = HourlyEnergyUsage(
                time=parsed_date,
                usage=usage.get(date),
                cost=cost.get(date),
                temp=temp.get(date),
            )
            return_dates.append(self.hourly_data[date])
        if not return_dates:
            raise UsageDataFailure("Received no data back for usage.")
        return return_dates

    async def get_month_data(self, jwt: str) -> MonthlyUsage:
        """Gets monthly data such as usage so far.

        Keeps the historic window -- first of the calendar month through today,
        not the current bill period -- so the numbers mean what they did before
        the API migration.
        """
        today = datetime.datetime.now()
        first_of_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        payload = await self._usage_graph_data(
            jwt,
            "Daily",
            first_of_month,
            today,
            {"intervalBehavior": "Automatic"},
        )
        return MonthlyUsage(
            dollars_to_date=first(payload, "dollarsToDate", default=0),
            total_kwh_used=first(payload, "totalkWhUsed", default=0),
            average_daily_usage=first(payload, "averageDailyUsage", default=0),
            average_daily_cost=first(payload, "averageDailyCost", default=0),
            projected_usage_low=first(payload, "projectedUsageLow", default=0),
            projected_usage_high=first(payload, "projectedUsageHigh", default=0),
            projected_bill_amount_low=first(
                payload, "projectedBillAmountLow", default=0
            ),
            projected_bill_amount_high=first(
                payload, "projectedBillAmountHigh", default=0
            ),
        )
