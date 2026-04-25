import dataclasses
import datetime
import re
from typing import List, Optional


def parse_aspnet_date(date_str: str) -> datetime.datetime:
    """Parse an ASP.NET /Date(milliseconds)/ string to a UTC datetime."""
    match = re.search(r"/Date\((-?\d+)\)/", date_str)
    if not match:
        raise ValueError(f"Invalid ASP.NET date format: {date_str!r}")
    ms = int(match.group(1))
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc)


@dataclasses.dataclass
class NicorBillingPeriod:
    date: datetime.datetime
    meter_reading: float
    reading_details: str
    ccfs: float
    therms: float
    days_used: int


@dataclasses.dataclass
class NicorDailyUsage:
    date: datetime.datetime
    therms: float
    cost: float
    avg_temp: Optional[float]
    day_of_week: str
    is_weekend: bool
    read_type: str
    meter_read: Optional[float]
    billing_period: str


@dataclasses.dataclass
class NicorMeterInfo:
    meter_number: str
    meter_status: str
    next_read_date: datetime.datetime


@dataclasses.dataclass
class NicorProjectedBill:
    usage: Optional[float]
    low_amount: Optional[float]
    high_amount: Optional[float]


@dataclasses.dataclass
class NicorUsageHistory:
    billing_periods: List[NicorBillingPeriod]
    daily_usage: List[NicorDailyUsage]
    projected_bill: NicorProjectedBill
    meter_info: Optional[NicorMeterInfo]
