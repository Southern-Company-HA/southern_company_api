import json

from southern_company_api.account import DailyEnergyUsageList


def test_daily_usage_data(datadir):
    data = json.loads((datadir / "get_data.json").read_text())
    daily_usage_data = DailyEnergyUsageList(data).usage()
    assert len(daily_usage_data) == 30
