# Southern Company API

<p align="center">
  <a href="https://github.com/Lash-L/southern_company_api/actions/workflows/ci.yml?query=branch%3Amain">
    <img src="https://img.shields.io/github/actions/workflow/status/Lash-L/southern_company_api/ci.yml?branch=main&label=CI&logo=github&style=flat-square" alt="CI Status" >
  </a>
  <a href="https://codecov.io/gh/Lash-L/southern_company_api">
    <img src="https://img.shields.io/codecov/c/github/Lash-L/southern_company_api.svg?logo=codecov&logoColor=fff&style=flat-square" alt="Test coverage percentage">
  </a>
</p>
<p align="center">
  <a href="https://python-poetry.org/">
    <img src="https://img.shields.io/badge/packaging-poetry-299bd7?style=flat-square&logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAA4AAAASCAYAAABrXO8xAAAACXBIWXMAAAsTAAALEwEAmpwYAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAJJSURBVHgBfZLPa1NBEMe/s7tNXoxW1KJQKaUHkXhQvHgW6UHQQ09CBS/6V3hKc/AP8CqCrUcpmop3Cx48eDB4yEECjVQrlZb80CRN8t6OM/teagVxYZi38+Yz853dJbzoMV3MM8cJUcLMSUKIE8AzQ2PieZzFxEJOHMOgMQQ+dUgSAckNXhapU/NMhDSWLs1B24A8sO1xrN4NECkcAC9ASkiIJc6k5TRiUDPhnyMMdhKc+Zx19l6SgyeW76BEONY9exVQMzKExGKwwPsCzza7KGSSWRWEQhyEaDXp6ZHEr416ygbiKYOd7TEWvvcQIeusHYMJGhTwF9y7sGnSwaWyFAiyoxzqW0PM/RjghPxF2pWReAowTEXnDh0xgcLs8l2YQmOrj3N7ByiqEoH0cARs4u78WgAVkoEDIDoOi3AkcLOHU60RIg5wC4ZuTC7FaHKQm8Hq1fQuSOBvX/sodmNJSB5geaF5CPIkUeecdMxieoRO5jz9bheL6/tXjrwCyX/UYBUcjCaWHljx1xiX6z9xEjkYAzbGVnB8pvLmyXm9ep+W8CmsSHQQY77Zx1zboxAV0w7ybMhQmfqdmmw3nEp1I0Z+FGO6M8LZdoyZnuzzBdjISicKRnpxzI9fPb+0oYXsNdyi+d3h9bm9MWYHFtPeIZfLwzmFDKy1ai3p+PDls1Llz4yyFpferxjnyjJDSEy9CaCx5m2cJPerq6Xm34eTrZt3PqxYO1XOwDYZrFlH1fWnpU38Y9HRze3lj0vOujZcXKuuXm3jP+s3KbZVra7y2EAAAAAASUVORK5CYII=" alt="Poetry">
  </a>
  <a href="https://github.com/ambv/black">
    <img src="https://img.shields.io/badge/code%20style-black-000000.svg?style=flat-square" alt="black">
  </a>
  <a href="https://github.com/pre-commit/pre-commit">
    <img src="https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white&style=flat-square" alt="pre-commit">
  </a>
</p>
<p align="center">
  <a href="https://pypi.org/project/southern-company-api/">
    <img src="https://img.shields.io/pypi/v/southern-company-api.svg?logo=python&logoColor=fff&style=flat-square" alt="PyPI Version">
  </a>
  <img src="https://img.shields.io/pypi/pyversions/southern-company-api.svg?style=flat-square&logo=python&amp;logoColor=fff" alt="Supported Python versions">
  <img src="https://img.shields.io/pypi/l/southern-company-api.svg?style=flat-square" alt="License">
</p>

Control Southern company websites with this api

## Supported utilities

| Utility                                         | Class                | Auth method    |
| ----------------------------------------------- | -------------------- | -------------- |
| Georgia Power, Alabama Power, Mississippi Power | `SouthernCompanyAPI` | JWT            |
| Nicor Gas (LDC=7)                               | `NicorGasAPI`        | Cookie session |

## Usage

### Southern Company electric utilities (Georgia Power, Alabama Power, Mississippi Power)

```python
import asyncio
import aiohttp
from southern_company_api import SouthernCompanyAPI

async def main():
    async with aiohttp.ClientSession() as session:
        api = SouthernCompanyAPI("username", "password", session)
        await api.connect()
        for account in await api.accounts:
            usage = await account.get_daily_data(start, end, await api.jwt)
            print(usage)

asyncio.run(main())
```

### Nicor Gas

```python
import asyncio
import aiohttp
from southern_company_api import NicorGasAPI

async def main():
    async with aiohttp.ClientSession() as session:
        api = NicorGasAPI("username", "password", session)
        await api.connect()
        history = await api.get_usage_history()

        for period in history.billing_periods:
            print(period.date, period.therms, "therms")

        for day in history.daily_usage:
            print(day.date.date(), day.therms, "therms", day.cost, "cost")

        print("Projected bill:", history.projected_bill.low_amount,
              "–", history.projected_bill.high_amount)

asyncio.run(main())
```

#### Nicor Gas data types

| Type                 | Fields                                                                                                         |
| -------------------- | -------------------------------------------------------------------------------------------------------------- |
| `NicorBillingPeriod` | `date`, `meter_reading`, `reading_details`, `ccfs`, `therms`, `days_used`                                      |
| `NicorDailyUsage`    | `date`, `therms`, `cost`, `avg_temp`, `day_of_week`, `is_weekend`, `read_type`, `meter_read`, `billing_period` |
| `NicorProjectedBill` | `usage`, `low_amount`, `high_amount`                                                                           |
| `NicorMeterInfo`     | `meter_number`, `meter_status`, `next_read_date`                                                               |

All `date` fields are timezone-aware UTC `datetime` objects. The `parse_aspnet_date` helper
converts the ASP.NET `/Date(ms)/` format used in the portal.

## Installation

Install this via pip (or your favourite package manager):

`pip install southern-company-api`

## Contributors ✨

Thanks goes to these wonderful people ([emoji key](https://allcontributors.org/docs/en/emoji-key)):

<!-- prettier-ignore-start -->
<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Lash-L"><img src="https://avatars.githubusercontent.com/u/20257911?v=4?s=80" width="80px;" alt="Luke"/><br /><sub><b>Luke</b></sub></a><br /><a href="https://github.com/Lash-L/southern_company_api/commits?author=Lash-L" title="Code">💻</a> <a href="#ideas-Lash-L" title="Ideas, Planning, & Feedback">🤔</a> <a href="https://github.com/Lash-L/southern_company_api/commits?author=Lash-L" title="Documentation">📖</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->
<!-- prettier-ignore-end -->

This project follows the [all-contributors](https://github.com/all-contributors/all-contributors) specification. Contributions of any kind welcome!

## Credits

This package was created with
[Copier](https://copier.readthedocs.io/) and the
[browniebroke/pypackage-template](https://github.com/browniebroke/pypackage-template)
project template.

### Electric billing, rate plans and reading freshness

`Account` now exposes three additional read-only sources:

```python
rate_plan = await account.get_rate_plan(jwt)
# Exact account API code (for example G-R), not an inferred cost/kWh price.
periods = await account.get_billing_periods(start, end, jwt)
bill = await account.get_bill_summary(jwt)
statement_pdf = await account.get_bill_pdf(bill, jwt)

await account.get_hourly_data(start, end, jwt)
status = account.hourly_status
print(status.latest_complete_reading, status.latest_complete_day)
```

- `BillPeriods` includes the current **scheduled** usage period. The issued bill
  summary has its own `period_start`, `period_end`, `bill_date`, `due_date` and
  `next_bill_date`. Preserve these boundaries as returned; the current usage
  period is not necessarily the latest issued bill. Null values remain unknown.
- Monetary bill amounts use `Decimal`. The PDF is personal account data and
  should not be logged. `parse_georgia_power_bill_text(layout_text)` extracts the
  verified English Georgia Power statement's Current Electric Service table,
  including signed credits, Community Solar kWh credits/net usage, and previously
  unknown row descriptions. Supply text
  from a layout-preserving extractor such as `pdftotext -layout`. Use its output
  as a complete itemization only when `reconciled` is true. This format-specific
  parser does not split bundled Current Service into invented base/fuel charges,
  and is not a general parser for other providers or statement layouts.
- `get_rate_plan` reads `EligibilityDetails` and retains the account's
  `rate_schedule_code` and `bill_factor_code`. A retrieved non-null bill factor is
  used by later graph requests under the same JWT. `hourly_time_of_use` preserves
  the graph's optional TOU bands; absence means unknown, not free electricity or
  proof of no TOU pricing.
- `GEORGIA_RESIDENTIAL_R31` is an explicit, versioned reference to Georgia Power's
  published Residential Service tariff, effective with the June 2026 billing
  month and verified October 22, 2026. It includes exact decimal base tiers,
  summer **billing months**, basic service charge, and absence of hourly TOU
  pricing. It is not automatically selected for an account, an all-in bill
  calculator, or a promise of current prices after its verification date. Verify
  the account-code mapping and applicable tariff revision before using it. Fuel,
  environmental and DSM riders, taxes, franchise fees, subscriptions, credits,
  multiple-unit rules and proration need their own applicable sources. [Official
  tariff](https://www.georgiapower.com/content/dam/georgia-power/pdfs/tariffs/r.pdf).

Georgia Power's timezone-less labels were checked against live March 8, 2026
usage: the endpoint skips 02:00 and returns 23 hours. Georgia Power hourly and
account daily timestamps therefore use `America/New_York`, rather than fixed
EST. An explicit `usage_timezone="..."` constructor argument is available for
other verified service locations. Other companies keep the previous parsing
until their convention is verified; their status remains `None` without an
explicit timezone. `DailyEnergyUsageList` used directly retains its prior naive
labels; the account methods attach the service timezone.

The live November 2, 2025 graph has only one 01:00 label. Its offset cannot be
recovered from that response. Such rows carry `timestamp_ambiguous=True` (the
legacy `time` field uses fold 0), and cannot establish a complete day or advance
freshness. Consumers requiring exact instants must skip them. Explicit offset
labels can represent both autumn folds unambiguously. No missing hour is
synthesized and no repeated-hour energy is split by assumption.

`hourly_status` and `daily_status` describe the most recent successful graph
response window, with separate usage/cost watermarks. A complete reading has
both actual usage and cost and is in a closed interval, using the existing
hour-start label convention. It does not prove an uninterrupted history.
`latest_complete_day` checks full local-day coverage (23/24/25 hours as
appropriate). Delayed/estimated series, including nonzero estimates, do not
advance these watermarks; genuine actual zeros do. The current daily bucket
cannot establish a completed day. Existing hourly list values retain their
behavior and expose `usage_estimated` / `cost_estimated` flags.

**Home Assistant upgrade note:** timestamp changes require a coordinated review
of external-statistics import and existing history. Do not mix shifted new rows
with previously imported fixed-EST or naive-UTC daily rows. This API change does
not migrate the recorder or add HA sensors automatically.
