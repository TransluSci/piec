"""
BaseMeasurement class implementing standardized lifecycle contracts.

Fulfills Checkpoint 8 of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Read-only run_state, safety_status, last_run_record, and run_records (Section 3.1);
- Cooperative stop and capability-gated pause controls (Section 3.1 & 4.3);
- Encapsulates LifecycleCoordinator for state transitions and reservations;
- Provides protected hooks for Checkpoint 9a full-run engine.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple
import pandas as pd

from .contracts import (
    LifecycleCoordinator,
    ReservationToken,
    RunRecord,
    RunRequest,
    RunState,
    SafetyStatus,
)


class BaseMeasurement:
    """
    Base class for PIEC standardized measurement families.

    Owns the execution lifecycle coordinator, state inspection, stop/pause controls,
    and history records.
    Subclasses implement protected hooks for instrument configuration, data capture,
    and setup-specific safe shutdown.
    """

    supports_pause: bool = False

    def __init__(self) -> None:
        self._coordinator = LifecycleCoordinator()
        self._raw_data: Optional[pd.DataFrame] = None
        self._data: Optional[pd.DataFrame] = None
        self._filename: Optional[str] = None
        self._partial_filename: Optional[str] = None

    @property
    def run_state(self) -> RunState:
        """Current execution lifecycle state."""
        return self._coordinator.run_state

    @property
    def safety_status(self) -> SafetyStatus:
        """Current verified safety status."""
        return self._coordinator.safety_status

    @property
    def last_run_record(self) -> Optional[RunRecord]:
        """Immutable RunRecord from the most recent run."""
        return self._coordinator.last_run_record

    @property
    def run_records(self) -> Tuple[RunRecord, ...]:
        """Immutable history of all run records in this instance."""
        return self._coordinator.run_records

    @property
    def active_token(self) -> Optional[ReservationToken]:
        """Current active reservation token, if any."""
        return self._coordinator.active_token

    @property
    def filename(self) -> Optional[str]:
        """Path to successfully published completed data CSV, or None."""
        return self._filename

    @property
    def partial_filename(self) -> Optional[str]:
        """Path to published incomplete/aborted data CSV, or None."""
        return self._partial_filename

    @property
    def data(self) -> Optional[pd.DataFrame]:
        """Analyzed result data, or raw partial data on abort/failure."""
        return self._data

    @property
    def raw_data(self) -> Optional[pd.DataFrame]:
        """Full raw acquisition data after completion."""
        return self._raw_data

    def request_stop(self) -> None:
        """Requests cooperative software stop of the active run."""
        self._coordinator.request_stop()

    def request_pause(self, paused: bool = True) -> None:
        """
        Requests cooperative pause if supported by the measurement family.

        Raises:
            NotImplementedError: If the measurement family does not support pause.
        """
        if not self.supports_pause:
            raise NotImplementedError(
                f"{self.__class__.__name__} does not support cooperative pause."
            )
        self._coordinator.request_pause(paused=paused)

    # --- Internal helpers for engine and subclasses (Checkpoint 9a) ---

    def _reserve(self, request: Optional[RunRequest] = None) -> ReservationToken:
        """Reserve a new run generation."""
        return self._coordinator.reserve(request)

    def _validate_token(self, token: ReservationToken) -> None:
        """Validate token before execution begins."""
        self._coordinator.validate_token(token)

    def _transition_to(self, next_state: RunState, reason: Optional[str] = None) -> None:
        """Execute a legal forward transition."""
        self._coordinator.transition_to(next_state, reason)

    def _record_run(self, record: RunRecord) -> None:
        """Finalize and record a run."""
        self._coordinator.record_run(record)

    def _idle_command_lease(self):
        """Acquire idle command lease."""
        return self._coordinator.idle_command_lease()
