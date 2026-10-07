"""HTTP layer: routers, dependency wiring and the error envelope.

Nothing in this package imports a concrete provider; routes only see
:class:`~baskd.ports.CalendarProvider`.
"""
