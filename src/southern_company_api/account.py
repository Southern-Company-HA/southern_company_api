import dataclasses
import datetime
import json
import logging
import math
from typing import Any, Dict, List, Mapping, Optional
from zoneinfo import ZoneInfo

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
from .billing import BillingPeriod, BillSummary, RatePlan
from .company import Company
from .constants import (
    ACCOUNT_SUMMARY_URL,
    API_HEADERS,
    BILL_IMAGE_URL,
    BILL_PERIODS_URL,
    BILL_SUMMARY_URL,
    USAGE_ELIGIBILITY_URL,
    USAGE_GRAPH_DATA_URL,
)
from .exceptions import CantReachSouthernCompany, UsageDataFailure
from .readings import (
    ReadingStatus,
    actual_points,
    label_is_ambiguous,
    local_timestamp,
    reading_status,
)

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
    # The portal can collapse the repeated autumn hour into one label.
    timestamp_ambiguous: bool = False
    usage_estimated: bool = False
    cost_estimated: bool = False


@dataclasses.dataclass
class MonthlyUsage:
    dollars_to_date: float
    total_kwh_used: float
    average_daily_usage: float
    average_daily_cost: float
    # Projections are only published once SoCo has an estimated bill for the
    # period (hasEstimatedBill), so they can be absent; None, not 0.
    projected_usage_low: Optional[float]
    projected_usage_high: Optional[float]
    projected_bill_amount_low: Optional[float]
    projected_bill_amount_high: Optional[float]


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
        *,
        usage_timezone: Optional[str] = None,
    ):
        self.name = name
        self.primary = primary
        self.number = number
        self.company = company
        self.hourly_data: Dict[str, HourlyEnergyUsage] = {}
        self.daily_data: Dict[str, DailyEnergyUsage] = {}
        self.session = session
        # Georgia Power civil-time labels verified against live DST windows.
        # Other operating companies retain legacy parsing until verified or
        # explicitly configured by the caller; do not assume HA's timezone.
        timezone_name = usage_timezone or (
            "America/New_York" if company == Company.GPC else None
        )
        self.usage_timezone = ZoneInfo(timezone_name) if timezone_name else None
        self.hourly_status: Optional[ReadingStatus] = None
        self.daily_status: Optional[ReadingStatus] = None
        self.hourly_time_of_use: Optional[List[Mapping[str, Any]]] = None
        self.rate_plan: Optional[RatePlan] = None
        self.rate_plan_jwt: Optional[str] = None
        self.service_point_number: Optional[str] = None
        # Opaque, session-scoped ids the usage endpoints are keyed on. Filled by
        # get_service_point_number(); see _usage_params for how they are used.
        self.usage_ids: Dict[str, Any] = {}
        # The JWT usage_ids were resolved under. The caller renews its JWT on
        # expiry but keeps this Account, so ids are only reused with the token
        # that fetched them.
        self.usage_ids_jwt: Optional[str] = None

    def _headers(self, jwt: str) -> Dict[str, str]:
        headers = dict(API_HEADERS)
        headers["Authorization"] = f"Bearer {jwt}"
        return headers

    async def get_service_point_number(self, jwt: str) -> str:
        """Resolve this account's service point via the account summary.

        The summary is also the only source of the opaque ``CfDJ8...`` ids
        (service agreement, service point, premise) and the person id that every
        usage request needs, so they are cached on the account here together
        with the JWT they were resolved under. They are session-scoped, so
        they are refreshed whenever this is called rather than persisted.
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
            self.usage_ids_jwt = None
            self.service_point_number = ""
            return ""

        # Top-level points can belong to a different agreement. Match by meter
        # badge, since the API independently encrypts IDs in the sibling arrays.
        service_point = deep_find(agreement, "servicePointId")
        if not service_point:
            points = [
                point
                for point in first(summary, "servicePoints", default=[]) or []
                if isinstance(point, Mapping) and first(point, "servicePointId")
            ]
            badge = deep_find(agreement, "badgeNumber")
            agreements = [
                entry
                for entry in first(summary, "serviceAgreements", default=[]) or []
                if isinstance(entry, Mapping)
            ]
            if badge:
                candidates = [
                    point for point in points if first(point, "badgeNumber") == badge
                ]
            else:
                # Without a link, only one agreement AND one point is safe.
                candidates = points if len(agreements) == 1 else []
            if len(candidates) == 1:
                service_point = first(candidates[0], "servicePointId")
            elif points:
                self.usage_ids = {}
                self.usage_ids_jwt = None
                self.service_point_number = ""
                raise UsageDataFailure(
                    "Could not unambiguously resolve service point for account "
                    f"ending {str(self.number)[-4:]}"
                )

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
            self.usage_ids_jwt = None
            self.service_point_number = ""
            return ""

        self.usage_ids = ids
        self.usage_ids_jwt = jwt
        self.service_point_number = str(ids["servicePointId"])
        return self.service_point_number

    async def _usage_ids(self, jwt: str, refresh: bool = False) -> Dict[str, Any]:
        if (
            refresh
            or jwt != self.usage_ids_jwt
            or not self.usage_ids.get("serviceAgreementId")
        ):
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
            "billFactorCode": (
                self.rate_plan.bill_factor_code
                if self.rate_plan is not None
                and self.rate_plan_jwt == self.usage_ids_jwt
                and self.rate_plan.bill_factor_code is not None
                else "null"
            ),
        }

    async def _usage_graph_data(
        self,
        jwt: str,
        granularity: str,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> Mapping[str, Any]:
        """GET one UsageGraphData payload and return its unwrapped body.

        A rejected request re-resolves the ids and retries once. Ids survive
        a JWT renewal in practice, but SoCo answers an id it cannot decrypt
        (e.g. after a server-side key rotation) with a 500 rather than a 401,
        so both are treated as possibly stale ids.
        """
        what = f"{granularity.lower()} data"
        response: Any = None
        for attempt in range(2):
            ids = await self._usage_ids(jwt, refresh=attempt > 0)
            params = self._usage_params(ids, start_date, end_date)
            params.update(extra_params or {})
            async with self.session.get(
                USAGE_GRAPH_DATA_URL.format(
                    agreement=ids["serviceAgreementId"], granularity=granularity
                ),
                headers=self._headers(jwt),
                params=params,
            ) as resp:
                if resp.status in (401, 403, 500) and attempt == 0:
                    _LOGGER.debug(
                        "Got %s for %s; re-resolving usage ids", resp.status, what
                    )
                    continue
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
            break
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
        if self.usage_timezone is not None:
            for day in days:
                day.date = local_timestamp(day.date.isoformat(), self.usage_timezone)
            self.daily_status = reading_status(
                payload.get("data") or {}, "daily", self.usage_timezone
            )
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
        self.hourly_time_of_use = first(graph, "timeOfUse")
        if self.usage_timezone is not None:
            self.hourly_status = reading_status(graph, "hourly", self.usage_timezone)
        cost = series_points(graph, "cost")
        usage = series_points(graph, "usage")
        temp = series_points(graph, "temp")

        actual_usage = actual_points(graph, "usage")
        actual_cost = actual_points(graph, "cost")
        return_dates = []
        for date in graph_labels(graph):
            parsed_date = local_timestamp(
                date,
                self.usage_timezone
                or datetime.timezone(datetime.timedelta(hours=-5), "EST"),
            )
            self.hourly_data[date] = HourlyEnergyUsage(
                time=parsed_date,
                usage=usage.get(date),
                cost=cost.get(date),
                temp=temp.get(date),
                timestamp_ambiguous=label_is_ambiguous(date, parsed_date),
                usage_estimated=date in usage and date not in actual_usage,
                cost_estimated=date in cost and date not in actual_cost,
            )
            return_dates.append(self.hourly_data[date])
        if not return_dates:
            raise UsageDataFailure("Received no data back for usage.")
        return return_dates

    async def get_month_data(self, jwt: str) -> MonthlyUsage:
        """Gets monthly data such as usage so far.

        dollarsToDate and totalkWhUsed are the current bill period to date
        whatever window is requested; the window -- first of the calendar
        month up to today -- only scopes the daily averages and projections.
        """
        today = datetime.datetime.now()
        start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.date() == today.date():
            # The end date is exclusive and a window that starts and ends on
            # the same date is rejected with a 400, which is every 1st of the
            # month; take yesterday instead.
            start -= datetime.timedelta(days=1)
        payload = await self._usage_graph_data(
            jwt,
            "Daily",
            start,
            today,
            {"intervalBehavior": "Automatic"},
        )
        if first(payload, "hasData") is False:
            # A window with no reads yet comes back with every total present
            # and 0 (seen live), which is not a month of zero usage either.
            raise UsageDataFailure(
                f"No month data yet for account ending {str(self.number)[-4:]}"
            )
        totals = {
            key: first(payload, key)
            for key in (
                "dollarsToDate",
                "totalkWhUsed",
                "averageDailyUsage",
                "averageDailyCost",
            )
        }
        missing = [key for key, value in totals.items() if value is None]
        if missing:
            # An envelope without the totals is not a month of zero usage.
            raise UsageDataFailure(
                f"Month data for account ending {str(self.number)[-4:]} "
                f"is missing {', '.join(missing)}"
            )
        return MonthlyUsage(
            dollars_to_date=totals["dollarsToDate"],
            total_kwh_used=totals["totalkWhUsed"],
            average_daily_usage=totals["averageDailyUsage"],
            average_daily_cost=totals["averageDailyCost"],
            projected_usage_low=first(payload, "projectedUsageLow"),
            projected_usage_high=first(payload, "projectedUsageHigh"),
            projected_bill_amount_low=first(payload, "projectedBillAmountLow"),
            projected_bill_amount_high=first(payload, "projectedBillAmountHigh"),
        )

    async def _billing_json(
        self, url: str, jwt: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Read a billing envelope; never include private response bodies in errors."""
        async with self.session.get(
            url, headers=self._headers(jwt), params=params
        ) as resp:
            if resp.status != 200:
                raise UsageDataFailure(f"Failed to get billing metadata: {resp.status}")
            try:
                body = await resp.json()
                if first(body, "status") is False:
                    raise UsageDataFailure("Billing API rejected metadata request")
                return unwrap(body, "billing metadata")
            except (ContentTypeError, json.JSONDecodeError, KeyError) as err:
                raise UsageDataFailure("Invalid billing metadata response") from err

    async def get_billing_periods(
        self, start_date: datetime.datetime, end_date: datetime.datetime, jwt: str
    ) -> List[BillingPeriod]:
        """Portal usage periods, including the scheduled current period.

        Boundaries are date-like local wall times; the last end is scheduled,
        not proof of a completed bill. These differ from issued bill dates.
        """
        ids = await self._usage_ids(jwt)
        params = {
            "ServiceAgreementId": ids["serviceAgreementId"],
            "ServicePointId": ids["servicePointId"],
            "PremiseId": ids.get("premiseId") or "",
            "OperatingCompany": ids["operatingCompany"],
            "StartDate": start_date.strftime("%m/%d/%Y"),
            "EndDate": end_date.strftime("%m/%d/%Y"),
        }
        payload = await self._billing_json(BILL_PERIODS_URL, jwt, params)
        if not isinstance(payload, list) or any(
            not isinstance(item, Mapping) for item in payload
        ):
            raise UsageDataFailure("Unexpected BillPeriods payload")
        return [BillingPeriod.from_portal(item) for item in payload]

    async def get_bill_summary(self, jwt: str) -> BillSummary:
        """Latest issued bill, not the usage graph's to-date estimate."""
        payload = await self._billing_json(
            BILL_SUMMARY_URL.format(account=self.number), jwt
        )
        if not isinstance(payload, Mapping):
            raise UsageDataFailure("Unexpected bill summary payload")
        return BillSummary.from_portal(payload)

    async def get_rate_plan(self, jwt: str) -> RatePlan:
        """Read the account's actual schedule code and optional bill factor.

        The eligibility API does not return tier prices or tax rules. Keep
        published tariff references separate from this account-specific fact.
        """
        ids = await self._usage_ids(jwt)
        payload = await self._billing_json(
            USAGE_ELIGIBILITY_URL.format(
                agreement=ids["serviceAgreementId"],
                company=ids["operatingCompany"],
            ),
            jwt,
        )
        if not isinstance(payload, Mapping):
            raise UsageDataFailure("Unexpected usage eligibility payload")
        plan = RatePlan.from_portal(payload)
        self.rate_plan = plan
        self.rate_plan_jwt = jwt
        return plan

    async def get_bill_pdf(self, summary: BillSummary, jwt: str) -> bytes:
        """Download the selected issued statement for itemized fees/credits.

        This is personal account data. Do not log or publish the document.
        No PDF extraction dependency is imposed on API consumers.
        """
        if not summary.bill_id or summary.bill_date is None:
            raise UsageDataFailure("Bill summary has no statement reference")
        params = {
            "accountId": self.number,
            "billId": summary.bill_id,
            "billDate": summary.bill_date.isoformat(),
        }
        async with self.session.get(
            BILL_IMAGE_URL, headers=self._headers(jwt), params=params
        ) as resp:
            if resp.status != 200:
                raise UsageDataFailure(f"Failed to get bill PDF: {resp.status}")
            document = await resp.read()
            if not document.startswith(b"%PDF-"):
                raise UsageDataFailure("Bill image response is not a PDF")
            return document
