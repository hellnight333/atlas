"""The control plane's own API: submit objectives, watch jobs, read provenance."""

from .api import build_router, install

__all__ = ["build_router", "install"]
