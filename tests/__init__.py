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
