"""Observe local browser read failures without changing the service response."""

from contextvars import ContextVar

from trade_plan_monitor.state.projections import ProjectionError
from trade_plan_monitor.web.errors import ApiError


def observe_read_failures(app, reader):
    """Record the original read exception beside its HTTP request identity."""
    diagnostics = []
    read_context = ContextVar("isolated_read_diagnostic", default=None)
    original_read = reader._read

    async def observed_read():
        try:
            return await original_read()
        except ApiError as error:
            holder = read_context.get()
            if holder is not None:
                cause = error.__context__
                holder.update(
                    cause=(
                        "BOUNDED_AUTHORITY_RACE"
                        if type(cause) is ProjectionError
                        and str(cause) == "Runtime authority changed during projection"
                        else "OTHER_READ_FAILURE"
                    ),
                    causeType=None if cause is None else type(cause).__name__,
                    causeMessage=None if cause is None else str(cause),
                )
            raise

    reader._read = observed_read

    class ReadDiagnosticMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await self.app(scope, receive, send)
            holder = {"cause": "UNKNOWN_READ_FAILURE"}
            token = read_context.set(holder)

            async def observed_send(message):
                if message["type"] == "http.response.start" and message["status"] == 503:
                    headers = dict(message["headers"])
                    diagnostics.append(
                        {
                            "path": scope["path"],
                            "method": scope["method"],
                            "status": 503,
                            "requestId": headers.get(b"x-request-id", b"").decode(),
                            "monitorContractVersion": headers.get(
                                b"x-monitor-contract-version", b""
                            ).decode(),
                            **holder,
                        }
                    )
                await send(message)

            try:
                await self.app(scope, receive, observed_send)
            finally:
                read_context.reset(token)

    app.add_middleware(ReadDiagnosticMiddleware)

    @app.get("/_test/read-diagnostics")
    async def read_diagnostics():
        return diagnostics

    return diagnostics
