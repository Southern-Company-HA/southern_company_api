"""Issued bills and usage periods are separate sources, with separate dates."""

import dataclasses
import datetime as dt
import re
from decimal import Decimal
from typing import Any, Mapping, Optional, Tuple

from ._helpers import first
from .exceptions import UsageDataFailure


def date_value(value: Any) -> Optional[dt.date]:
    if value in (None, ""):
        return None
    return dt.date.fromisoformat(str(value)[:10])


def money(value: Any) -> Optional[Decimal]:
    return None if value is None else Decimal(str(value))


@dataclasses.dataclass(frozen=True)
class BillingPeriod:
    # Preserve portal boundaries. Do not subtract a day from the end date.
    start: dt.datetime
    end: dt.datetime

    @classmethod
    def from_portal(cls, item: Mapping[str, Any]) -> "BillingPeriod":
        try:
            start, end = str(first(item, "value")).split(";")
            result = cls(
                dt.datetime.strptime(start, "%m/%d/%Y %H:%M:%S"),
                dt.datetime.strptime(end, "%m/%d/%Y %H:%M:%S"),
            )
            if result.end <= result.start:
                raise ValueError("Invalid boundary order")
            return result
        except (TypeError, ValueError) as err:
            raise UsageDataFailure("Invalid BillPeriods date range") from err


@dataclasses.dataclass(frozen=True)
class BillSummary:
    period_start: Optional[dt.date]
    period_end: Optional[dt.date]
    bill_date: Optional[dt.date]
    next_bill_date: Optional[dt.date]
    due_date: Optional[dt.date]
    total_billed: Optional[Decimal]
    total_due: Optional[Decimal]
    service_amount: Optional[Decimal]
    non_service_amount: Optional[Decimal]
    total_usage: Optional[float]
    # Sensitive, opaque reference used only to retrieve the statement.
    bill_id: Optional[str] = dataclasses.field(repr=False)

    @classmethod
    def from_portal(cls, payload: Mapping[str, Any]) -> "BillSummary":
        try:
            return cls(
                period_start=date_value(first(payload, "periodStart")),
                period_end=date_value(first(payload, "periodEnd")),
                bill_date=date_value(first(payload, "lastBillDate")),
                next_bill_date=date_value(first(payload, "nextBillDate")),
                due_date=date_value(first(payload, "payDueDate")),
                total_billed=money(first(payload, "totalAmountBilled")),
                total_due=money(first(payload, "totalDue")),
                service_amount=money(first(payload, "totalServiceAmount")),
                non_service_amount=money(first(payload, "totalNonServiceAmount")),
                total_usage=first(payload, "lastBillTotalUsage"),
                bill_id=first(payload, "billId"),
            )
        except (TypeError, ValueError, ArithmeticError) as err:
            raise UsageDataFailure("Invalid bill summary") from err


@dataclasses.dataclass(frozen=True)
class RatePlan:
    # Account-specific API code, not a price inferred from dollars/kWh.
    rate_schedule_code: Optional[str]
    bill_factor_code: Optional[str]
    eligible_for_usage: Optional[bool]
    eligible_for_estimated_bill: Optional[bool]

    @classmethod
    def from_portal(cls, payload: Mapping[str, Any]) -> "RatePlan":
        characteristics = first(payload, "eligibilityCharacteristics", default={})
        return cls(
            first(characteristics, "rateScheduleCode"),
            first(characteristics, "billFactorCode"),
            first(payload, "isEligibleForMyPowerUsage"),
            first(payload, "isEligibleForEstimatedBill"),
        )


@dataclasses.dataclass(frozen=True)
class BillLineItem:
    description: str
    amount: Decimal


@dataclasses.dataclass(frozen=True)
class BillBreakdown:
    items: Tuple[BillLineItem, ...]
    total: Decimal
    # False means an unrecognised layout or missing row: do not publish as a
    # complete itemization. Credits keep their original negative sign.
    reconciled: bool
    source: str = "Georgia Power statement text"
    # Subscription energy credit, not a measurement of grid export.
    community_solar_kwh: Optional[Decimal] = None
    net_usage_kwh: Optional[Decimal] = None


def parse_georgia_power_bill_text(text: str) -> BillBreakdown:
    """Parse the verified English statement's Current Electric Service table.

    Supply layout-preserving PDF text (e.g. pdftotext -layout), not HTML or an
    arbitrary bill. PDF extraction is deliberately left to the caller, so this
    API client does not require a PDF engine. Unknown labels are preserved;
    base/fuel/other charges bundled into Current Service are not invented.
    """
    total_match = re.search(
        r"Total Current Electric Service\s*\$\s*([\d,]+\.\d{2})", text
    )
    start_match = re.search(r"^Current Service\s{2,}", text, re.MULTILINE)
    if total_match is None or start_match is None:
        raise UsageDataFailure("Unsupported Georgia Power bill layout")
    if start_match.start() >= total_match.start():
        raise UsageDataFailure("Invalid Georgia Power bill table")
    items = []
    table_start = start_match.start()
    table_end = total_match.start()
    for line in text[table_start:table_end].splitlines():
        match = re.match(
            r"^(\S.*?)\s{2,}\$?\s*(\(?-?[\d,]+\.\d{2}\)?)(?:\s+(CR))?"
            r"(?:\s{2,}.*)?$",
            line.rstrip(),
        )
        if match:
            label, amount, credit = match.groups()
            negative = amount.startswith("(") or credit is not None
            value = Decimal(amount.strip("()").replace(",", ""))
            items.append(
                BillLineItem(label.strip(), -abs(value) if negative else value)
            )
    total = Decimal(total_match.group(1).replace(",", ""))

    def energy_value(pattern: str) -> Optional[Decimal]:
        match = re.search(pattern + r"\s+([\d,]+\.\d+)", text)
        return Decimal(match.group(1).replace(",", "")) if match else None

    return BillBreakdown(
        tuple(items),
        total,
        bool(items) and sum(i.amount for i in items) == total,
        community_solar_kwh=energy_value(r"Community Solar\s*-\s*Community Solar kWh"),
        net_usage_kwh=energy_value(r"Community Solar\s*-\s*Net kWh"),
    )
