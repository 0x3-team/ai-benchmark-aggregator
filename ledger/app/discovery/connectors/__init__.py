"""Bounded, fixture-only discovery connectors (DSC-01 seam, DSC-02 families)."""

from app.discovery.connectors.base import (
    ConnectorError,
    ConnectorObservation,
    DiscoveryConnector,
    StaticFixtureConnector,
)

__all__ = [
    "ConnectorError",
    "ConnectorObservation",
    "DiscoveryConnector",
    "StaticFixtureConnector",
]
