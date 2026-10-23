from enum import Enum


class Company(Enum):
    SCS = "Southern Company"
    APC = "Alabama Power"
    GPC = "Georgia Power"
    MPC = "Mississippi Power"
    NICOR_GAS = "Nicor Gas"


COMPANY_MAP = {
    0: Company.SCS,
    1: Company.APC,
    2: Company.GPC,
    4: Company.MPC,
    7: Company.NICOR_GAS,
}

# The portal labels usage with local wall-clock times of the utility's area.
COMPANY_TIMEZONE = {
    Company.SCS: "America/New_York",
    Company.APC: "America/Chicago",
    Company.GPC: "America/New_York",
    Company.MPC: "America/Chicago",
    Company.NICOR_GAS: "America/Chicago",
}
