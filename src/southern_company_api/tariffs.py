"""Versioned tariff references; these are not an all-in bill calculator."""

import dataclasses
import datetime as dt
from decimal import Decimal
from typing import Optional, Tuple


@dataclasses.dataclass(frozen=True)
class EnergyTier:
    up_to_kwh: Optional[int]
    dollars_per_kwh: Decimal


@dataclasses.dataclass(frozen=True)
class TariffReference:
    schedule: str
    source_url: str
    effective_billing_month: dt.date
    verified_on: dt.date
    basic_service_dollars_per_day: Decimal
    summer_billing_months: Tuple[int, ...]
    summer_tiers: Tuple[EnergyTier, ...]
    winter_tiers: Tuple[EnergyTier, ...]
    time_of_use: bool
    # Riders, taxes, subscriptions, discounts and proration require separate
    # sources. Do not equate these base rates with usage graph cost/kWh.


GEORGIA_RESIDENTIAL_R31 = TariffReference(
    schedule="R-31",
    source_url="https://www.georgiapower.com/content/dam/georgia-power/pdfs/tariffs/r.pdf",
    effective_billing_month=dt.date(2026, 6, 1),
    verified_on=dt.date(2026, 10, 22),
    basic_service_dollars_per_day=Decimal("0.4603"),
    summer_billing_months=(6, 7, 8, 9),
    summer_tiers=(
        EnergyTier(650, Decimal("0.087738")),
        EnergyTier(1000, Decimal("0.145738")),
        EnergyTier(None, Decimal("0.150828")),
    ),
    winter_tiers=(EnergyTier(None, Decimal("0.082116")),),
    time_of_use=False,
)
