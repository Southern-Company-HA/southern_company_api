import dataclasses
import datetime
import json
import math
import typing
from typing import List

import aiohttp
from aiohttp import ContentTypeError

from .company import Company
from .exceptions import CantReachSouthernCompany, UsageDataFailure


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
    usage: typing.Optional[float]
    cost: typing.Optional[float]
    temp: typing.Optional[float]


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
        self.hourly_data: typing.Dict[str, HourlyEnergyUsage] = {}
        self.daily_data: typing.Dict[str, DailyEnergyUsage] = {}
        self.session = session
        self.service_point_number = None

    async def get_service_point_number(self, jwt: str) -> str:
        headers = {
            "Authorization": f"bearer {jwt}",
            "content-type": "application/json, text/plain, */*",
        }
        # TODO: Is the /GPC for all customers or just GA power?
        try:
            async with self.session.get(
                f"https://customerservice2api.southerncompany.com/api/MyPowerUsage/"
                f"getMPUBasicAccountInformation/{self.number}/GPC",
                headers=headers,
            ) as resp:
                try:
                    service_info = await resp.json()
                except (ContentTypeError, json.JSONDecodeError) as err:
                    try:
                        error_text = await resp.text()
                    except aiohttp.ClientError:
                        error_text = err.msg
                    raise CantReachSouthernCompany(
                        f"Incorrect mimetype while trying to get service point number. error:{error_text} Response "
                        f"headers:{resp.headers} Your headers:{headers}"
                    ) from err

                # TODO: Test with multiple accounts
                self.service_point_number = service_info["Data"][
                    "meterAndServicePoints"
                ][0]["servicePointNumber"]
                return service_info["Data"]["meterAndServicePoints"][0][
                    "servicePointNumber"
                ]
        except aiohttp.ClientConnectorError as err:
            raise CantReachSouthernCompany("Failed to connect to api") from err

    async def get_daily_data(
        self, start_date: datetime.datetime, end_date: datetime.datetime, jwt: str
    ) -> List[DailyEnergyUsage]:
        """Available 24 hours after"""
        """This is not really tested yet."""
        headers = {"Authorization": f"bearer {jwt}"}
        params = {
            "accountNumber": self.number,
            "startDate": start_date.strftime("%m/%d/%Y 12:00:00 AM"),
            "endDate": end_date.strftime("%m/%d/%Y 11:59:59 PM"),
            "OPCO": self.company.name,
            "ServicePointNumber": self.service_point_number,
            "intervalBehavior": "Automatic",
        }
        async with self.session.get(
            f"https://customerservice2api.southerncompany.com/api/MyPowerUsage/"
            f"MPUData/{self.number}/Daily",
            headers=headers,
            params=params,
        ) as resp:
            if resp.status != 200:
                raise UsageDataFailure(
                    f"Failed to get daily data: {resp.status} {headers}"
                )
            else:
                try:
                    response = await resp.json()
                except (ContentTypeError, json.JSONDecodeError) as err:
                    try:
                        error_text = await resp.text()
                    except aiohttp.ClientError:
                        error_text = err.msg
                    raise CantReachSouthernCompany(
                        f"Incorrect mimetype while trying to get daily data. {error_text}"
                    ) from err
                data = json.loads(response["Data"]["Data"])
                day_maps = {}
                dates = [date for date in data["xAxis"]["labels"]]
                high_temps = [temp["y"] for temp in data["series"]["highTemp"]["data"]]
                low_temps = [temp["y"] for temp in data["series"]["lowTemp"]["data"]]
                for i, date in enumerate(dates):
                    day_maps[date] = DailyEnergyUsage(
                        # TODO: Determine timezone
                        date=datetime.datetime.strptime(date, "%Y-%m-%dT%H:%M:%S"),
                        usage=-1,
                        cost=1,
                        low_temp=low_temps[i],
                        high_temp=high_temps[i],
                    )
                # TODO: Zip weekday and weekend to make it simpler.
                for weekend_cost in data["series"]["weekdayCost"]["data"]:
                    day_maps[weekend_cost["name"]].cost = weekend_cost["y"]
                for weekend_usage in data["series"]["weekdayUsage"]["data"]:
                    day_maps[weekend_usage["name"]].usage = weekend_usage["y"]
                for weekday_cost in data["series"]["weekdayCost"]["data"]:
                    day_maps[weekday_cost["name"]].cost = weekday_cost["y"]
                for weekday_usage in data["series"]["weekdayUsage"]["data"]:
                    day_maps[weekday_usage["name"]].usage = weekday_usage["y"]
                return list(day_maps.values())

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
        headers = {"Authorization": f"bearer {jwt}"}
        params = {
            "accountNumber": self.number,
            "startDate": start_date.strftime("%m/%d/%Y %H:%M:%S %p"),
            "endDate": end_date.strftime("%m/%d/%Y %H:%M:%S %p"),
            "OPCO": self.company.name,
            "ServicePointNumber": self.service_point_number,
            "intervalBehavior": "Automatic",
        }
        async with self.session.get(
            f"https://customerservice2api.southerncompany.com/api/MyPowerUsage/"
            f"MPUData/{self.number}/Hourly",
            headers=headers,
            params=params,
        ) as resp:
            if resp.status != 200:
                raise UsageDataFailure(
                    f"Failed to get hourly data: {resp.status} {headers}"
                )
            else:
                try:
                    data = await resp.json()
                except (ContentTypeError, json.JSONDecodeError) as err:
                    try:
                        error_text = await resp.text()
                    except aiohttp.ClientError:
                        error_text = err.msg
                    raise CantReachSouthernCompany(
                        f"Incorrect mimetype while trying to get hourly data. {error_text}"
                    ) from err
                if data["Data"]["Data"] is None:
                    raise UsageDataFailure("Received no data back for usage.")
                data = json.loads(data["Data"]["Data"])
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
        """Gets monthly data such as usage so far"""
        headers = {"Authorization": f"bearer {jwt}"}
        today = datetime.datetime.now()
        first_of_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        params = {
            "accountNumber": self.number,
            "startDate": first_of_month.strftime("%m/%d/%Y 12:00:00 AM"),
            "endDate": today.strftime("%m/%d/%Y 11:59:59 PM"),
            "OPCO": self.company.name,
            "ServicePointNumber": self.service_point_number,
            "intervalBehavior": "Automatic",
        }
        async with self.session.get(
            f"https://customerservice2api.southerncompany.com/api/MyPowerUsage/"
            f"MPUData/{self.number}/Daily",
            headers=headers,
            params=params,
        ) as resp:
            if resp.status != 200:
                raise UsageDataFailure(
                    f"Failed to get month data: {resp.status} {headers}"
                )
            else:
                try:
                    connection = await resp.json()
                except (ContentTypeError, json.JSONDecodeError) as err:
                    try:
                        error_text = await resp.text()
                    except aiohttp.ClientError:
                        error_text = err.msg
                    raise CantReachSouthernCompany(
                        f"Incorrect mimetype while trying to get month data. {error_text}"
                    ) from err
                data = connection["Data"]
                return MonthlyUsage(
                    dollars_to_date=data["DollarsToDate"],
                    total_kwh_used=data["TotalkWhUsed"],
                    average_daily_usage=data["AverageDailyUsage"],
                    average_daily_cost=data["AverageDailyCost"],
                    projected_usage_low=data["ProjectedUsageLow"],
                    projected_usage_high=data["ProjectedUsageHigh"],
                    projected_bill_amount_low=data["ProjectedBillAmountLow"],
                    projected_bill_amount_high=data["ProjectedBillAmountHigh"],
                )
