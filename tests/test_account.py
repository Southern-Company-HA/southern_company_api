from southern_company_api import Account, Company


def test_can_create():
    Account("sample", True, "1", Company.GPC)
