class SouthernCompanyException(Exception):
    pass


class InvalidLogin(SouthernCompanyException):
    pass


class CantReachSouthernCompany(SouthernCompanyException):
    pass


class NoRequestTokenFound(SouthernCompanyException):
    pass


class NoJwtTokenFound(SouthernCompanyException):
    pass


class NoScTokenFound(SouthernCompanyException):
    pass


class AccountFailure(SouthernCompanyException):
    pass


class UsageDataFailure(SouthernCompanyException):
    pass
