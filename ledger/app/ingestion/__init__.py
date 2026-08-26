from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import IngestionSummary, run_ingestion

__all__ = ["run_ingestion", "IngestionSummary"]


def __getattr__(name: str):
    """Resolve the compatibility exports without importing the runner eagerly.

    Runtime composition imports ``safe_fetch`` before the ingestion runner is
    available.  Keeping these historical package exports lazy removes that
    cycle while leaving the runner as the authority for ingestion behavior.
    """

    if name in __all__:
        from .runner import IngestionSummary, run_ingestion

        return {"run_ingestion": run_ingestion, "IngestionSummary": IngestionSummary}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
