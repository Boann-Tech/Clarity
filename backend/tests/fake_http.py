"""httpcore-shaped fakes shared by fetch tests."""


class FakeStreamResponse:
    def __init__(self, status_code=200, headers=None, body=b"<html>ok</html>"):
        self.status = status_code
        self.headers = [
            (key.encode("latin-1"), value.encode("latin-1"))
            for key, value in (headers or {"content-type": "text/html"}).items()
        ]
        self._body = body

    async def aiter_stream(self):
        yield self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakePool:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requested = []
        self.headers_seen = []
        self.extensions_seen = []
        self.closed = False

    def stream(self, _method, url, headers=None, extensions=None):
        self.requested.append(str(url))
        self.headers_seen.append(dict(headers or {}))
        self.extensions_seen.append(dict(extensions or {}))
        return self.responses.pop(0)

    async def aclose(self):
        self.closed = True


def use_pool(monkeypatch, pool):
    from app import evidence

    monkeypatch.setattr(evidence, "build_pool", lambda: pool)
    return pool
