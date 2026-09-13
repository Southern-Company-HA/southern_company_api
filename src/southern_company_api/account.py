import dataclasses
import datetime
import json
import logging
import math
from typing import Any, Dict, List, Mapping, Optional

import aiohttp
from aiohttp import ContentTypeError

from .company import Company
from .constants import ACCOUNT_API_BASE, ACCOUNT_API_HEADERS, USAGE_API_BASE
from .exceptions import CantReachSouthernCompany, UsageDataFailure

_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass
class DailyEnergyUsage:
    date: datetime.datetime
    usage: float
    cost: float
    low_temp: float
    high_temp: float


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
        series = self.data.get("series", {})
        dates = self.data.get("xAxis", {}).get("labels", [])

        high_temps = {i["name"]: i for i in series.get("highTemp", {}).get("data", [])}
        low_temps = {i["name"]: i for i in series.get("lowTemp", {}).get("data", [])}
        cost = {
            i["name"]: i
            for i in [
                *series.get("weekdayCost", {}).get("data", []),
                *series.get("weekendCost", {}).get("data", []),
            ]
        }
        usage = {
            i["name"]: i
            for i in [
                *series.get("weekendUsage", {}).get("data", []),
                *series.get("weekdayUsage", {}).get("data", []),
            ]
        }

        days = [
            DailyEnergyUsage(
                # TODO: Determine timezone
                date=datetime.datetime.strptime(date, "%Y-%m-%dT%H:%M:%S"),
                usage=usage.get(date, {}).get("y"),
                cost=cost.get(date, {}).get("y"),
                low_temp=low_temps.get(date, {}).get("y"),
                high_temp=high_temps.get(date, {}).get("y"),
            )
            for date in dates
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
        # Populated by get_service_point_number() from the Summary response;
        # required (alongside service_point_number) to call the usage-graph
        # endpoint used by get_daily_data/get_hourly_data/get_month_data.
        self.person_id: Optional[str] = None
        self.premise_id: Optional[str] = None

    async def get_service_point_number(self, jwt: str) -> str:
        # NOTE (Sept 2026 backend migration): the old
        # customerservice2api.southerncompany.com/api/MyPowerUsage/
        # getMPUBasicAccountInformation endpoint is dead post-migration
        # (every path on that origin now falls through to a static
        # maintenance page). Service point info now comes from
        # occaccountapi.southerncompany.com's account Summary endpoint,
        # confirmed live.
        headers = dict(ACCOUNT_API_HEADERS)
        headers["Authorization"] = f"bearer {jwt}"
        try:
            async with self.session.get(
                f"{ACCOUNT_API_BASE}/Accounts/{self.number}/Summary",
                headers=headers,
            ) as resp:
                try:
                    service_info = await resp.json()
                except (ContentTypeError, json.JSONDecodeError) as err:
                    raise CantReachSouthernCompany(
                        f"Incorrect mimetype while trying to get service point "
                        f"number. status:{resp.status} "
                        f"content_type:{resp.headers.get('Content-Type')}"
                    ) from err

                data = service_info.get("data") or {}
                self.person_id = data.get("mainPersonId") or ""
                self.service_point_number = ""
                self.premise_id = ""

                # NOTE: the top-level data.servicePoints[].servicePointId is a
                # separately-encrypted opaque token from the one nested inside
                # data.serviceAgreements[].servicePoints[] -- same badgeNumber,
                # different string -- so they can't be cross-matched by
                # equality. Use the electric service agreement's own
                # (servicePointId, premiseId) pair together, since only those
                # two values from the SAME agreement are guaranteed consistent
                # with each other for the usage-graph endpoint.
                electric_agreement = next(
                    (
                        agreement
                        for agreement in data.get("serviceAgreements") or []
                        if agreement.get("serviceTypeCode") == "E"
                        and agreement.get("servicePoints")
                    ),
                    None,
                )
                if electric_agreement:
                    self.service_point_number = (
                        electric_agreement["servicePoints"][0].get("servicePointId")
                        or ""
                    )
                    self.premise_id = electric_agreement.get("premiseId") or ""
                else:
                    points = data.get("servicePoints") or []
                    if points:
                        self.service_point_number = (
                            points[0].get("servicePointId") or ""
                        )

                if not self.service_point_number:
                    _LOGGER.warning(
                        "servicePoints empty for company %s; "
                        "monthly/hourly stats unavailable.",
                        self.company.name,
                    )

                return self.service_point_number or ""
        except aiohttp.ClientConnectorError as err:
            raise CantReachSouthernCompany("Failed to connect to api") from err

    async def _get_usage_graph_data(
        self,
        period: str,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
        jwt: str,
    ) -> Dict[str, Any]:
        """Fetch UsageGraphData for the given period ("Daily"/"Hourly"/"Monthly").

        NOTE (Sept 2026 backend migration): the old
        customerservice2api.southerncompany.com/api/MyPowerUsage/MPUData
        endpoint is dead post-migration (every path on that origin now falls
        through to a static maintenance page). Usage graph data now comes
        from occmypowerusageapi.southerncompany.com, confirmed live via a
        fresh HAR capture. The response shape under response["data"]["data"]
        (xAxis/series) matches what MPUData used to return byte-for-byte in
        structure, just no longer double-JSON-encoded as a string.
        """
        headers = dict(ACCOUNT_API_HEADERS)
        headers["Authorization"] = f"bearer {jwt}"
        params = {
            "accountId": self.number,
            "personId": self.person_id or "",
            "operatingCompany": self.company.name,
            "startDate": start_date.strftime("%m/%d/%Y"),
            "endDate": end_date.strftime("%m/%d/%Y"),
            "maxBills": "13",
            "servicePointId": self.service_point_number or "",
            "premiseId": self.premise_id or "",
            "billFactorCode": "null",
            "aggregateMonthlyDataForElectircServiceAgreements": "true",
        }
        url = f"{USAGE_API_BASE}/UsageGraphData/{self.service_point_number}/{period}"
        async with self.session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                raise UsageDataFailure(
                    f"Failed to get {period.lower()} data: {resp.status} {headers}"
                )
            try:
                response = await resp.json()
            except (ContentTypeError, json.JSONDecodeError) as err:
                try:
                    error_text = await resp.text()
                except aiohttp.ClientError:
                    error_text = str(err)
                raise CantReachSouthernCompany(
                    f"Incorrect mimetype while trying to get {period.lower()} "
                    f"data. {error_text}"
                ) from err
            return response.get("data") or {}

    async def get_daily_data(
        self, start_date: datetime.datetime, end_date: datetime.datetime, jwt: str
    ) -> List[DailyEnergyUsage]:
        """
        Available 24 hours after
        This is not really tested yet.
        """
        envelope = await self._get_usage_graph_data("Daily", start_date, end_date, jwt)
        graph_data = envelope.get("data") or {}
        if not graph_data:
            raise UsageDataFailure("Received no data back for usage.")
        daily_usage = DailyEnergyUsageList(graph_data)
        return daily_usage.usage()

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
                try:
                    return_data.extend(
                        await self.get_hourly_data(
                            cur_date, cur_date + datetime.timedelta(days=35), jwt
                        )
                    )
                except UsageDataFailure:
                    cur_date = min(cur_date + datetime.timedelta(days=35), end_date)
                    continue
                cur_date = cur_date + datetime.timedelta(days=35)
            return return_data
        # Needs to check if the data already exist in self.hourly_data to avoid making an unneeded call.
        envelope = await self._get_usage_graph_data("Hourly", start_date, end_date, jwt)
        data = envelope.get("data") or {}
        if not data.get("xAxis", {}).get("labels"):
            raise UsageDataFailure("Received no data back for usage.")
        return_dates = []
        for date in data["xAxis"]["labels"]:
            # TODO: Determine timezone
            parsed_date = datetime.datetime.strptime(date, "%Y-%m-%dT%H:%M:%S")
            parsed_date = parsed_date.replace(
                tzinfo=datetime.timezone(datetime.timedelta(hours=-5), "EST")
            )
            self.hourly_data[date] = HourlyEnergyUsage(
                time=parsed_date, usage=None, cost=None, temp=None
            )
            return_dates.append(self.hourly_data[date])
        # costs and temps can be different lengths?
        for cost in data["series"]["cost"]["data"]:
            self.hourly_data[cost["name"]].cost = cost["y"]
        for usage in data["series"]["usage"]["data"]:
            self.hourly_data[usage["name"]].usage = usage["y"]
        for temp in data["series"]["temp"]["data"]:
            self.hourly_data[temp["name"]].temp = temp["y"]
        return return_dates

    async def get_month_data(self, jwt: str) -> MonthlyUsage:
        """Gets monthly data such as usage so far

        NOTE (Sept 2026 backend migration): confirmed live that this call
        succeeds and returns well-formed JSON, but the dollarsToDate/
        totalkWhUsed/projected* fields all come back as 0 even when the
        account has real current-period usage (the UsageGraphData/Monthly
        graph itself, i.e. get_daily_data-shaped data under data.data, does
        have real values). This suggests current-bill-period stats have
        moved to a different endpoint post-migration -- occbillingapi.
        southerncompany.com/api/v1/Billing/billSummary/{accountId} looks
        like the likely replacement (seen in a live HAR capture) but its
        response body wasn't captured, so it needs verification before
        wiring in.
        """
        today = datetime.datetime.now()
        one_year_ago = today - datetime.timedelta(days=365)
        data = await self._get_usage_graph_data("Monthly", one_year_ago, today, jwt)
        try:
            return MonthlyUsage(
                dollars_to_date=data["dollarsToDate"],
                total_kwh_used=data["totalkWhUsed"],
                average_daily_usage=data["averageDailyUsage"],
                average_daily_cost=data["averageDailyCost"],
                projected_usage_low=data["projectedUsageLow"],
                projected_usage_high=data["projectedUsageHigh"],
                projected_bill_amount_low=data["projectedBillAmountLow"],
                projected_bill_amount_high=data["projectedBillAmountHigh"],
            )
        except KeyError as err:
            raise UsageDataFailure(f"Unexpected month data format: {err}") from err
