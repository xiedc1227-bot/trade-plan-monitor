"""ASGI timing preserves FastAPI's existing validation/JSON serialization path."""

from trade_plan_monitor.diagnostics.read_tracing import read_trace, trace_point, trace_window


class ReadTracingMiddleware:
    def __init__(self, app, *, window):
        self.app, self.window = app, window

    async def __call__(self, scope, receive, send):
        if self.window is not None and scope["type"] == "lifespan":
            try:
                return await self.app(scope, receive, send)
            finally:
                self.window.close()
        if self.window is None or scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        token = trace_window.set(self.window)
        try:
            path = scope.get("path", "")
            if scope["type"] == "websocket":
                with read_trace("monitor.socket") as socket_trace:
                    async def socket_send(message):
                        if message["type"] == "websocket.accept":
                            trace_point("socket.accept")
                            if socket_trace is not None:
                                message = {**message, "headers": [*message.get("headers", []),
                                    (b"x-read-trace-id", socket_trace.trace_id.encode("ascii"))]}
                        await send(message)

                    async def socket_receive():
                        message = await receive()
                        if message["type"] == "websocket.disconnect":
                            trace_point("socket.disconnect")
                        return message
                    return await self.app(scope, socket_receive, socket_send)
            if scope.get("method") != "GET" or not path.startswith("/api/v1/"):
                return await self.app(scope, receive, send)
            entry = (
                "http.result" if path.startswith("/api/v1/backtest-runs/")
                else "http.backtest" if path.startswith("/api/v1/backtest-")
                else "http.monitor"
            )
            with read_trace(entry) as trace:
                async def observed_send(message):
                    if message["type"] == "http.response.start":
                        trace_point("http.headers", statusCode=message["status"])
                        if trace is not None:
                            message = {**message, "headers": [*message.get("headers", []),
                                (b"x-read-trace-id", trace.trace_id.encode("ascii"))]}
                    await send(message)
                    if message["type"] == "http.response.body":
                        trace_point("http.body", bytes=len(message.get("body", b"")))
                return await self.app(scope, receive, observed_send)
        finally:
            trace_window.reset(token)
