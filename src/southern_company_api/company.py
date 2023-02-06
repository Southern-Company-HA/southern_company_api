from enum import Enum


class Company(Enum):
    SCS = "Southern Company"
    APC = "Alabama Power"
    GPC = "Georgia Power"
    MPC = "Mississippi Power"


COMPANY_MAP = {0: Company.SCS, 1: Company.APC, 2: Company.GPC, 4: Company.MPC}
