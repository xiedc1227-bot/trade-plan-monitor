"""R13 fault injection exclusively at the existing isolated AI HTTP boundary."""

import json

import httpx
from tests.browser import explicit_server

_transport = httpx.MockTransport


def fault_transport(handler):
    calls = 0

    def reply(request):
        nonlocal calls
        calls += 1
        response = handler(request)
        if calls == 1:
            return response
        if calls == 5:
            return httpx.Response(503, json={"error": "R13 isolated failure"})
        body = response.json()
        message = body["choices"][0]["message"]
        if calls == 2:
            message["content"] = "{invalid JSON"
        elif calls == 3:
            message["content"] = '{"draft":null,"draft":null}'
        elif calls == 4:
            message["content"] = "{}"
        elif calls == 6:
            body["choices"][0]["finish_reason"] = "length"
        elif calls == 7:
            output = json.loads(message["content"])
            output["draft"]["rules"].pop()
            message["content"] = json.dumps(output, ensure_ascii=False)
        else:
            raise AssertionError("unexpected AI call beyond bounded R13 fault cases")
        return httpx.Response(200, json=body)

    return _transport(reply)


if __name__ == "__main__":
    explicit_server.httpx.MockTransport = fault_transport
    explicit_server.main()
