"""Holding connections without holding credentials.

The store keeps `Connection` rows, which are references. Turning a reference
into a credential is a separate act, performed by a resolver at the moment of
use, and the result is returned to one caller and kept nowhere.

Every read is tenant-scoped, and `resolve` re-checks the tenant rather than
trusting that whoever holds the object was entitled to it. That is not
belt-and-braces: a `Connection` is an ordinary value that can be passed around,
and the only place its ownership is certain is where it is being turned into a
credential.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from ..opportunity.tenancy import TenantId, owns
from ..opportunity.tenancy import require as _require_tenant
from .models import Connection, ConnectionKind

log = logging.getLogger(__name__)


class ConnectionNotFound(Exception):
    """No connection for this tenant and target. Never says whether one exists
    for a *different* tenant — that answer is itself information."""


class CredentialUnavailable(Exception):
    """The reference resolved to nothing.

    A missing credential is a configuration problem, not a publication failure,
    and separating them keeps "the token expired" from reading as "the customer's
    site was rejected".
    """


def from_environment(connection: Connection) -> str:
    """The default resolver: the reference names an environment variable.

    Deliberately the least magical thing that works. A vault-backed resolver is
    the same signature and the rest of this file does not change.
    """
    value = os.environ.get(connection.reference, "")
    if not value:
        raise CredentialUnavailable(
            # The reference, never a value, and never a hint about length or
            # shape. An error message is a place credentials leak.
            f"{connection.reference} is not set, so connection {connection.id} "
            "cannot be resolved")
    return value


def filesystem_root(connection: Connection) -> str:
    """For a filesystem target the reference *is* the value, and is not secret.

    Kept as its own resolver rather than special-cased in the caller, so that
    "this connection needs no secret" is a property of the connection's kind
    rather than a branch somewhere downstream.
    """
    return connection.reference


#: Which resolver serves which kind. A kind with no resolver cannot be used,
#: which is the right default for one nobody has implemented.
RESOLVERS: dict[ConnectionKind, Callable[[Connection], str]] = {
    ConnectionKind.FILESYSTEM: filesystem_root,
    ConnectionKind.API_TOKEN: from_environment,
    ConnectionKind.OAUTH: from_environment,
}


class ConnectionStore:
    """Connections, scoped by tenant on every read."""

    def __init__(self, resolvers: dict[ConnectionKind, Callable[[Connection], str]] | None = None
                 ) -> None:
        self._by_id: dict[str, Connection] = {}
        self._resolvers = dict(resolvers or RESOLVERS)

    def register(self, connection: Connection) -> Connection:
        self._by_id[connection.id] = connection
        # The id and the reference. Never resolved, so never a credential.
        log.info("connection registered: %s -> %s (%s)", connection.id,
                 connection.target, connection.reference)
        return connection

    def get(self, connection_id: str, *, tenant: TenantId | None) -> Connection | None:
        """TENANT_SCOPED. Another tenant's connection reads as absent."""
        tenant = _require_tenant(tenant, method="connections.get")
        found = self._by_id.get(connection_id)
        if found is None or not owns(found.tenant_id, tenant):
            return None
        return found

    def for_target(self, target: str, *, tenant: TenantId | None) -> Connection | None:
        """TENANT_SCOPED. The connection this tenant has for this target."""
        tenant = _require_tenant(tenant, method="connections.for_target")
        for connection in self._by_id.values():
            if connection.target == target and owns(connection.tenant_id, tenant):
                return connection
        return None

    def resolve(self, connection: Connection, *, tenant: TenantId | None) -> str:
        """The credential itself, for one use. Never stored, never logged.

        Re-checks ownership rather than trusting the object it was handed. A
        `Connection` is an ordinary value that can be passed anywhere, and this
        is the only point at which being entitled to it actually matters.
        """
        tenant = _require_tenant(tenant, method="connections.resolve")
        if not owns(connection.tenant_id, tenant):
            raise ConnectionNotFound(
                f"connection {connection.id} does not belong to this tenant")
        resolver = self._resolvers.get(connection.kind)
        if resolver is None:
            raise CredentialUnavailable(
                f"no resolver for {connection.kind.value} connections")
        return resolver(connection)
