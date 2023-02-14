ga_power_sample_sc_response = {
    "statusCode": 200,
    "message": None,
    "data": {
        "result": 0,
        "token": "sample_sc_token",
        "emailValidated": None,
        "termsOfServiceAccepted": None,
        "errorMessage": "Login Succeeded.",
        "messages": [],
        "username": "sample@email.com",
        "rememberUsername": None,
        "staySignedIn": None,
        "recaptchaResponse": None,
        "targetPage": 1,
        "params": {
            "appBannerUrl": None,
            "appTheme": None,
            "appType": None,
            "appID": None,
            "returnUrl": "null",
            "cancelUrl": None,
            "logonID": None,
            "loginUrl": None,
            "originalReturnUrl": None,
            "scWebToken": None,
            "userID": None,
            "addProfileLink": None,
            "editProfileLink": None,
            "forgotPasswordLink": None,
            "forgotInfoLink": None,
            "southerncoApplication": None,
            "newUserHeaderText": None,
            "newUserText": None,
            "updateProfileText": None,
            "forgotInfoText": None,
            "emailValidationTicket": None,
            "ticket": None,
            "emailAddress": None,
            "postTarget": None,
            "compactDisplay": None,
            "errorDisplayType": None,
            "extendedIconVisible": None,
            "extendedPopupEnabled": None,
            "showLogin": None,
            "noTokenReturnUrl": None,
            "returnMethod": None,
            "tokenEncoding": None,
            "origin": None,
            "mfaConfigInternal": None,
            "mfaConfigUnknown": None,
            "mfaExcludeInternal": None,
            "mfaExcludeUnknown": None,
            "firstName": None,
            "lastName": None,
            "email": None,
            "phoneNumber": None,
            "oAuthLogoutId": None,
        },
        "html": "<form action='null' method='post' id='WL_Form' name='WL_Form' >"
        "<p><strong>Note:</strong> Since your browser does not support Javascript, you must press the Continue "
        'button once to proceed.</p><div><input type="submit" value="Continue"/></div><INPUT TYPE=\'hidden\' '
        "NAME='ScWebToken' value='sample_sc_token'><INPUT TYPE='hidden' NAME='WL_Error' value=''><INPUT "
        "TYPE='hidden' NAME='WL_LogonId' value=''><INPUT TYPE='hidden' NAME='WL_LoginResult' value="
        "'Success'><INPUT TYPE='hidden' NAME='CheckedExtended' value='True'></form>",
        "redirect": None,
        "origin": None,
    },
    "isSuccess": True,
    "modelErrors": None,
}

ga_power_southern_jwt_cookie_header = {
    "Cache-Control": "no-cache,no-store",
    "set-cookie": "SouthernJwtCookie=sample_cookie; path=/; secure; samesite=lax; httponly",
}

ga_power_jwt_header = {"set-cookie": "ScJwtToken=sample_jwt; path=/"}

ga_power_sample_account_response = {
    "StatusCode": 200,
    "Message": "Success",
    "MessageType": 0,
    "Data": [
        {
            "UserSid": "sample-user",
            "AccountNumber": 1,
            "Company": 2,
            "AccountType": 0,
            "Description": "Home Energy",
            "PrimaryAccount": "Y",
            "IsCurrentViewAccount": False,
            "IsNicknameChanged": False,
            "IsPrimaryAccountChanged": False,
            "DataPresentmentPilotParticipant": "",
            "BillStatus": 0,
            "IsLocked": False,
            "AccountLockedUntil": None,
            "IsPinRequired": False,
            "IsPinValidated": False,
            "LocalAddress": {
                "Number": "0000",
                "Structure": "",
                "Note": "",
                "PreDirection": "",
                "StreetName": "RANDOM_STREET",
                "PostDirection": "",
                "StreetType": "LANE",
                "AddressLine1": "0000 RANDOM_STREET LANE ",
                "AddressLine2": "",
                "City": "SOMEWHERE",
                "State": "GA",
                "Zip": "00000",
                "Country": None,
            },
            "PremiseNumber": None,
            "IsPrePayAccount": False,
            "IsInGulfDivestiturePilot": False,
            "EixLinkedClients": [],
            "IsEixConsented": False,
        }
    ],
    "IsScApiResult": True,
}


test_get_hourly_usage = {
    "StatusCode": 200,
    "Message": "Successfully retrieved My Power Usage data for Hourly Graph",
    "MessageType": 0,
    "Data": {
        "Data": '{"xAxis":{"labels":["2023-02-04T22:50:11","2023-02-04T23:50:11"]}'
        ',"series":{"cost":{"data":[{"x":1,"y":0.05,"name":"2023-02-04T23:50:11","resolution":"hourly"}]}'
        ',"usage":{"data":[{"x":1,"y":0.32,"name":"2023-02-04T23:50:11","resolution":"hourly"}]},'
        '"costDelayed":{"data":[{"x":0,"y":0.05,"name":"2023-02-04T22:50:11","resolution":"hourly"}]},'
        '"usageDelayed":{"data":[{"x":0,"y":0.32,"name":"2023-02-04T22:50:11","resolution":"hourly"}]},'
        '"temp":{"data":[{"x":0,"y":44.099998474121094,"name":"2023-02-04T22:50:11","resolution":"hourly"},'
        '{"x":1,"y":44.099998474121094,"name":"2023-02-04T23:50:11","resolution":"hourly"}]},'
        '"solarGeneration":{"data":[]},"solarGenerationDelayed":{"data":[]}}}',
        "ProjectedBillAmountHigh": 0.0,
        "ProjectedBillAmountLow": 0.0,
        "ProjectedUsageHigh": 0.0,
        "ProjectedUsageLow": 0.0,
        "AverageDailyCost": 0.0,
        "AverageDailyUsage": 0.0,
        "AverageDailyReceived": 0.0,
        "Days": 0.0,
        "DollarsToDate": 0.0,
        "TotalkWhUsed": 0.0,
        "TotalkWhReceived": 0.0,
        "HasData": True,
        "HasEstimatedBill": False,
        "IsPartialMonth": False,
        "AlertThreshold": 0,
        "AlertThresholdExceeded": False,
        "IsSolarActive": False,
        "ProjectedReceivedHigh": 0.0,
        "ProjectedReceivedLow": 0.0,
    },
    "ModelErrors": [],
    "IsScApiResult": True,
}

test_get_month_data = {
    "StatusCode": 200,
    "Message": "Successfully retrieved My Power Usage data for Daily Graph",
    "MessageType": 0,
    "Data": {
        "Data": "{}",
        "ProjectedBillAmountHigh": 91.0,
        "ProjectedBillAmountLow": 60.0,
        "ProjectedUsageHigh": 629.0,
        "ProjectedUsageLow": 419.0,
        "AverageDailyCost": 2.79,
        "AverageDailyUsage": 19.17,
        "AverageDailyReceived": 0.0,
        "Days": 27.0,
        "DollarsToDate": 13.974766406622413,
        "TotalkWhUsed": 97.0,
        "TotalkWhReceived": 0.0,
        "HasData": True,
        "HasEstimatedBill": True,
        "IsPartialMonth": True,
        "AlertThreshold": 0,
        "AlertThresholdExceeded": False,
        "IsSolarActive": False,
        "ProjectedReceivedHigh": 0.0,
        "ProjectedReceivedLow": 0.0,
    },
    "ModelErrors": [],
    "IsScApiResult": True,
}


class MockResponse:
    def __init__(self, text, status, mock_headers, json):
        self._text = text
        self._json = json
        self.status = status
        self._headers = mock_headers

    async def text(self):
        return self._text

    async def json(self):
        return self._json

    @property
    def headers(self):
        return self._headers

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def __aenter__(self):
        return self
