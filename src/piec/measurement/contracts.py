"""
Measurement lifecycle contracts, states, tokens, records, and coordination.

Fulfills Checkpoint 8 of MEASUREMENT_STANDARDIZATION_PLAN.md:
- RunState enum and legal forward transition validation (Section 4.1);
- SafetyStatus enum (Section 4.1);
- ReservationToken, RunRequest, SafetyReport, and immutable RunRecord (Section 3.2 & 4.2);
- LifecycleCoordinator for thread-safe reservation, token validation, stop/pause control,
  idle lease protection, and run record history (Section 4.2 & 4.3).
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
import threading
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple
import uuid

import pandas as pd


# ============================================================================
# 1. State Enums & Legal Transitions (Section 4.1)
# ============================================================================

class RunState(str, Enum):
    """
    Standard lifecycle states for all PIEC measurements.
    """

    IDLE = "IDLE"
    STARTING = "STARTING"
    CONFIGURING = "CONFIGURING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    SAFING = "SAFING"
    ANALYZING = "ANALYZING"
    SAVING = "SAVING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        """Whether this state represents a finalized terminal outcome."""
        return self in {RunState.COMPLETED, RunState.ABORTED, RunState.FAILED}

    @property
    def is_active(self) -> bool:
        """Whether this state represents an active reservation or in-progress run."""
        return not self.is_terminal and self != RunState.IDLE


class SafetyStatus(str, Enum):
    """
    Independent hardware safety status.
    """

    UNKNOWN = "UNKNOWN"
    NOT_NEEDED = "NOT_NEEDED"
    SAFING = "SAFING"
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"


# Strict legal forward transition table per Section 4.1 of MEASUREMENT_STANDARDIZATION_PLAN.md
LEGAL_TRANSITIONS: Dict[RunState, Set[RunState]] = {
    RunState.IDLE: {RunState.STARTING},
    RunState.STARTING: {RunState.CONFIGURING, RunState.STOPPING, RunState.FAILED},
    RunState.CONFIGURING: {RunState.RUNNING, RunState.STOPPING, RunState.SAFING},
    RunState.RUNNING: {RunState.STOPPING, RunState.SAFING},
    RunState.STOPPING: {RunState.SAFING, RunState.ABORTED},
    RunState.SAFING: {
        RunState.ANALYZING,
        RunState.SAVING,
        RunState.COMPLETED,
        RunState.ABORTED,
        RunState.FAILED,
    },
    RunState.ANALYZING: {RunState.SAVING, RunState.COMPLETED, RunState.FAILED},
    RunState.SAVING: {RunState.COMPLETED, RunState.ABORTED, RunState.FAILED},
    RunState.COMPLETED: {RunState.STARTING},
    RunState.ABORTED: {RunState.STARTING},
    RunState.FAILED: {RunState.STARTING},
}


# ============================================================================
# 2. Lifecycle Exceptions
# ============================================================================

class MeasurementLifecycleError(Exception):
    """Base exception for measurement lifecycle violations."""


class IllegalStateTransitionError(MeasurementLifecycleError):
    """Raised when an illegal state transition is attempted."""


class ConcurrentRunError(MeasurementLifecycleError, RuntimeError):
    """Raised when a run reservation is attempted while another run or idle lease is active."""


class StaleTokenError(MeasurementLifecycleError):
    """Raised when an execution token is stale, mismatched, or invalid."""


class DuplicateExecutionError(MeasurementLifecycleError):
    """Raised when a reservation token is executed more than once."""


class HardwareSafetyError(MeasurementLifecycleError):
    """
    Raised when required hardware cleanup fails without an earlier primary error.
    """

    def __init__(self, message: str, safety_report: Optional[SafetyReport] = None):
        super().__init__(message)
        self.safety_report = safety_report


# ============================================================================
# 3. Data Contracts, Tokens & Records
# ============================================================================

@dataclass(frozen=True)
class ReservationToken:
    """
    Opaque token bound to a specific run reservation generation (Section 4.2).

    Attributes:
        run_id: Unique 128-bit UUID string.
        generation: Monotonically increasing local integer.
    """

    run_id: str
    generation: int


@dataclass(frozen=True)
class RunRequest:
    """
    Immutable validated specification for a measurement run (Section 3.1).
    """

    on_update: Optional[Callable[[Any], None]] = None
    save: bool = True
    save_partial: Optional[bool] = None
    options: Mapping[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        *,
        on_update: Optional[Callable[[Any], None]] = None,
        save: bool = True,
        save_partial: Optional[bool] = None,
        options: Optional[Mapping[str, Any]] = None,
    ):
        object.__setattr__(self, "on_update", on_update)
        object.__setattr__(self, "save", bool(save))
        object.__setattr__(
            self, "save_partial", None if save_partial is None else bool(save_partial)
        )
        opts = copy.deepcopy(dict(options)) if options is not None else {}
        object.__setattr__(self, "options", MappingProxyType(opts))


@dataclass(frozen=True)
class SafetyAction:
    """
    Record of a specific safety action attempted during shutdown.
    """

    name: str
    attempted: bool
    succeeded: bool
    duration_seconds: float = 0.0
    error: Optional[str] = None
    readback_verified: bool = False


@dataclass(frozen=True)
class SafetyReport:
    """
    Summary report of all shutdown actions attempted and verified safety status.
    """

    status: SafetyStatus
    actions: Tuple[SafetyAction, ...] = ()
    readback_verified: bool = False
    error: Optional[str] = None
    summary: str = ""


@dataclass(frozen=True)
class RunRecord:
    """
    Immutable record summarizing a completed, aborted, or failed run reservation (Section 3.2).
    """

    run_id: str
    generation: int
    start_time: float
    end_time: Optional[float] = None
    state: RunState = RunState.IDLE
    safety: SafetyReport = field(
        default_factory=lambda: SafetyReport(status=SafetyStatus.UNKNOWN)
    )
    save_requested: bool = True
    filename: Optional[str] = None
    partial_filename: Optional[str] = None
    primary_error_phase: Optional[str] = None
    primary_error_type: Optional[str] = None
    primary_error_message: Optional[str] = None
    secondary_errors: Tuple[str, ...] = ()
    schema_name: Optional[str] = None
    schema_version: Optional[int] = None
    snapshot_count: int = 0
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __init__(
        self,
        run_id: str,
        generation: int,
        start_time: float,
        end_time: Optional[float] = None,
        state: RunState = RunState.IDLE,
        safety: Optional[SafetyReport] = None,
        save_requested: bool = True,
        filename: Optional[str] = None,
        partial_filename: Optional[str] = None,
        primary_error_phase: Optional[str] = None,
        primary_error_type: Optional[str] = None,
        primary_error_message: Optional[str] = None,
        secondary_errors: Optional[Sequence[str]] = None,
        schema_name: Optional[str] = None,
        schema_version: Optional[int] = None,
        snapshot_count: int = 0,
        metadata: Optional[Mapping[str, Any]] = None,
    ):
        object.__setattr__(self, "run_id", str(run_id))
        object.__setattr__(self, "generation", int(generation))
        object.__setattr__(self, "start_time", float(start_time))
        object.__setattr__(
            self, "end_time", float(end_time) if end_time is not None else None
        )
        object.__setattr__(self, "state", RunState(state))
        object.__setattr__(
            self,
            "safety",
            safety if safety is not None else SafetyReport(status=SafetyStatus.UNKNOWN),
        )
        object.__setattr__(self, "save_requested", bool(save_requested))
        object.__setattr__(
            self, "filename", str(filename) if filename is not None else None
        )
        object.__setattr__(
            self,
            "partial_filename",
            str(partial_filename) if partial_filename is not None else None,
        )
        object.__setattr__(
            self,
            "primary_error_phase",
            str(primary_error_phase) if primary_error_phase is not None else None,
        )
        object.__setattr__(
            self,
            "primary_error_type",
            str(primary_error_type) if primary_error_type is not None else None,
        )
        object.__setattr__(
            self,
            "primary_error_message",
            str(primary_error_message) if primary_error_message is not None else None,
        )
        object.__setattr__(
            self, "secondary_errors", tuple(str(e) for e in (secondary_errors or ()))
        )
        object.__setattr__(
            self, "schema_name", str(schema_name) if schema_name is not None else None
        )
        object.__setattr__(
            self,
            "schema_version",
            int(schema_version) if schema_version is not None else None,
        )
        object.__setattr__(self, "snapshot_count", int(snapshot_count))
        meta = copy.deepcopy(dict(metadata)) if metadata is not None else {}
        object.__setattr__(self, "metadata", MappingProxyType(meta))


@dataclass(frozen=True)
class TerminalEvent:
    """
    Terminal event emitted upon conclusion of a run reservation (Section 6.2).
    """

    run_id: str
    generation: int
    state: RunState
    safety: SafetyReport
    filename: Optional[str] = None
    partial_filename: Optional[str] = None
    primary_error_phase: Optional[str] = None
    primary_error_type: Optional[str] = None
    primary_error_message: Optional[str] = None
    secondary_errors: Tuple[str, ...] = ()
    record: Optional[RunRecord] = None
    data: Optional[pd.DataFrame] = None


# ============================================================================
# 4. Lifecycle Coordinator (Section 4.2 & 4.3)
# ============================================================================

class LifecycleCoordinator:
    """
    Thread-safe coordinator for measurement run lifecycle states, reservation,
    token validation, and run record history.
    """

    def __init__(self) -> None:
        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._run_state = RunState.IDLE
        self._safety_status = SafetyStatus.UNKNOWN
        self._generation = 0
        self._active_token: Optional[ReservationToken] = None
        self._consumed_token: Optional[ReservationToken] = None
        self._idle_lease_active = False
        self._last_run_record: Optional[RunRecord] = None
        self._run_records: List[RunRecord] = []

    @property
    def run_state(self) -> RunState:
        """Current execution lifecycle state."""
        with self._state_lock:
            return self._run_state

    @property
    def safety_status(self) -> SafetyStatus:
        """Current verified safety status."""
        with self._state_lock:
            return self._safety_status

    @property
    def generation(self) -> int:
        """Current monotonically increasing generation counter."""
        with self._state_lock:
            return self._generation

    @property
    def active_token(self) -> Optional[ReservationToken]:
        """Currently active reservation token, if any."""
        with self._state_lock:
            return self._active_token

    @property
    def stop_event(self) -> threading.Event:
        """Stop synchronization event."""
        return self._stop_event

    @property
    def pause_event(self) -> threading.Event:
        """Pause synchronization event."""
        return self._pause_event

    @property
    def is_stop_requested(self) -> bool:
        """Whether a cooperative stop has been requested."""
        return self._stop_event.is_set()

    @property
    def is_pause_requested(self) -> bool:
        """Whether a cooperative pause has been requested."""
        return self._pause_event.is_set()

    @property
    def last_run_record(self) -> Optional[RunRecord]:
        """Most recent finalized run record."""
        with self._state_lock:
            return self._last_run_record

    @property
    def run_records(self) -> Tuple[RunRecord, ...]:
        """Immutable sequence of all finalized run records."""
        with self._state_lock:
            return tuple(self._run_records)

    def reserve(self, request: Optional[RunRequest] = None) -> ReservationToken:
        """
        Synchronously reserves the measurement runner for a new generation.

        Requirements (Section 4.2 & 4.3):
        1. Accept only IDLE or a terminal state.
        2. Reject if an active run or idle shutdown lease is in progress.
        3. Clear the stop event and pause event.
        4. Generate 128-bit UUID and increment generation.
        5. Transition state to STARTING.
        6. Return opaque ReservationToken.
        """
        with self._state_lock:
            if self._idle_lease_active:
                raise ConcurrentRunError(
                    "Cannot reserve run while idle shutdown lease is active."
                )
            if self._run_state.is_active:
                raise ConcurrentRunError(
                    f"Cannot reserve run while another run is active (current state: {self._run_state.value})."
                )

            # Clear stop and pause events
            self._stop_event.clear()
            self._pause_event.clear()

            # Increment monotonic generation and generate UUID
            self._generation += 1
            run_id = str(uuid.uuid4())
            token = ReservationToken(run_id=run_id, generation=self._generation)

            self._active_token = token
            self._consumed_token = None
            self._safety_status = SafetyStatus.UNKNOWN

            # Move state to STARTING
            self._transition_to(RunState.STARTING, "Reserved new run generation")
            return token

    def validate_token(self, token: ReservationToken) -> None:
        """
        Validates token before worker execution begins (Section 4.2 & 4.3).

        Guards against:
        - None or wrong token type.
        - Stale tokens (generation < current_generation).
        - Mismatched or unknown tokens (run_id != active_token.run_id).
        - Duplicate execution of the same token.
        """
        with self._state_lock:
            if not isinstance(token, ReservationToken):
                raise TypeError(f"Expected ReservationToken, got {type(token).__name__}")

            if token.generation < self._generation:
                raise StaleTokenError(
                    f"Reservation token generation {token.generation} is stale; "
                    f"current generation is {self._generation}."
                )

            if (
                self._active_token is None
                or token.generation != self._active_token.generation
                or token.run_id != self._active_token.run_id
            ):
                raise StaleTokenError(
                    f"Reservation token ({token.run_id}, gen {token.generation}) does not match "
                    f"active reservation ({getattr(self._active_token, 'run_id', None)}, gen {getattr(self._active_token, 'generation', None)})."
                )

            if self._consumed_token == token:
                raise DuplicateExecutionError(
                    f"Reservation token generation {token.generation} (run_id={token.run_id}) "
                    "has already begun execution."
                )

            self._consumed_token = token

    def transition_to(self, next_state: RunState, reason: Optional[str] = None) -> None:
        """
        Validates and executes a legal forward state transition under the state lock.
        """
        with self._state_lock:
            self._transition_to(next_state, reason)

    def _transition_to(self, next_state: RunState, reason: Optional[str] = None) -> None:
        """Internal transition under lock without re-acquiring lock."""
        next_state = RunState(next_state)
        current = self._run_state
        allowed = LEGAL_TRANSITIONS.get(current, set())
        if next_state not in allowed:
            raise IllegalStateTransitionError(
                f"Illegal state transition from {current.value} to {next_state.value}. "
                f"Allowed transitions: {[s.value for s in allowed]}"
            )
        self._run_state = next_state

    def set_safety_status(self, status: SafetyStatus) -> None:
        """Sets the current safety status."""
        with self._state_lock:
            self._safety_status = SafetyStatus(status)

    def request_stop(self) -> None:
        """
        Cooperative cross-thread Stop control write (Section 4.3).

        - STARTING, CONFIGURING, RUNNING: sets stop event and transitions to STOPPING.
        - STOPPING: leave state unchanged (idempotent).
        - SAFING, ANALYZING, SAVING: sets stop event but leaves state unchanged (never moves backward).
        - IDLE or terminal: ignore the request.
        """
        with self._state_lock:
            if self._run_state in {
                RunState.STARTING,
                RunState.CONFIGURING,
                RunState.RUNNING,
            }:
                self._stop_event.set()
                self._transition_to(RunState.STOPPING, "Stop requested")
            elif self._run_state == RunState.STOPPING:
                self._stop_event.set()
            elif self._run_state in {
                RunState.SAFING,
                RunState.ANALYZING,
                RunState.SAVING,
            }:
                self._stop_event.set()
                # Do not move backward
            elif self._run_state == RunState.IDLE or self._run_state.is_terminal:
                pass  # Ignore

    def request_pause(self, paused: bool = True) -> None:
        """
        Cooperative cross-thread pause control.
        """
        with self._state_lock:
            if paused:
                self._pause_event.set()
            else:
                self._pause_event.clear()

    @contextmanager
    def idle_command_lease(self):
        """
        Context manager to lease command ownership for idle operations (e.g. safe_shutdown)
        when no run is active (Section 4.3).

        Rejects if a run is active or another idle lease is held.
        While held, prevents new run reservations.
        """
        with self._state_lock:
            if self._run_state.is_active:
                raise ConcurrentRunError(
                    f"Cannot acquire idle command lease while run is active (state: {self._run_state.value})."
                )
            if self._idle_lease_active:
                raise ConcurrentRunError("Idle command lease is already active.")
            self._idle_lease_active = True

        try:
            yield
        finally:
            with self._state_lock:
                self._idle_lease_active = False

    def record_run(self, record: RunRecord) -> None:
        """
        Finalizes run record, updates history, and transitions to record's terminal state
        if not already at that state.
        """
        if not isinstance(record, RunRecord):
            raise TypeError(f"Expected RunRecord, got {type(record).__name__}")
        if not record.state.is_terminal:
            raise ValueError(
                f"RunRecord state must be terminal (COMPLETED, ABORTED, FAILED), got {record.state.value}"
            )

        with self._state_lock:
            if self._run_state != record.state:
                self._transition_to(
                    record.state, f"Finalized run record ({record.state.value})"
                )
            self._safety_status = record.safety.status
            self._last_run_record = record
            self._run_records.append(record)
