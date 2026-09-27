"""Resolve owned SDK wrappers before an invocation-local permission guard."""

from abc import ABC, abstractmethod
from collections.abc import Callable


class PermissionEndpointResolver(ABC):
    """Nominal opt-in: preparation must return the inner callable, not a guard wrapper."""

    @abstractmethod
    def prepare_permission_endpoint(self, operation: str) -> Callable[..., object]:
        """Complete wrapper checks and resolve the endpoint for this invocation only."""


def resolve_permission_endpoint(client: object, operation: str) -> Callable[..., object]:
    """Never discover optional attributes on an SDK with dynamic endpoint lookup."""
    endpoint = (
        client.prepare_permission_endpoint(operation)
        if isinstance(client, PermissionEndpointResolver)
        else getattr(client, operation)
    )
    if not callable(endpoint):
        raise TypeError("permission SDK endpoint must be callable")
    return endpoint
