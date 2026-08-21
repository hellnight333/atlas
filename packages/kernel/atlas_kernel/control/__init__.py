"""The control plane's own API: submit objectives, watch jobs, read provenance."""

from .api import build_router
from .api import install as install_control
from .sales import install as install_sales


def install(app, runner=None) -> None:
    """Both routers. The sales workspace is a read model over the same data."""
    install_control(app, runner)
    install_sales(app)


__all__ = ["build_router", "install"]
