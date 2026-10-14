"""BASK'D: a small calendar service with a pluggable provider.

The package is organised so that the public HTTP behaviour (``baskd.api``) never
depends on a concrete provider. Everything in between speaks the provider-neutral
vocabulary defined in :mod:`baskd.models`, :mod:`baskd.errors` and :mod:`baskd.ports`.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("baskd")
except PackageNotFoundError:  # pragma: no cover - only when running from an unbuilt checkout
    __version__ = "0.0.0"

__all__ = ["__version__"]
