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


class EmailValidationRequired(InvalidLogin):
    """Raised when Southern Company requires email validation before login can complete."""

    def __init__(self, message: str = "", validation_url: str = ""):
        self.validation_url = validation_url
        super().__init__(message)


class AccountFailure(SouthernCompanyException):
    pass


class UsageDataFailure(SouthernCompanyException):
    pass
