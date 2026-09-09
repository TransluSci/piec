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

import collections
import collections.abc
import copy
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
import queue
import threading
import time
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union
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


class ShutdownAttemptRecorder:
    """
    Executes and records ordered shutdown actions (Section 5.1 & 5.3).

    Catches BaseException during individual action execution so all required
    actions are attempted even if an earlier action fails. Records timing,
    readback verification, errors, and deferred interrupts.
    """

    def __init__(self) -> None:
        self.actions: List[SafetyAction] = []
        self.interrupt_exc: Optional[BaseException] = None
        self.failures: List[Tuple[str, BaseException]] = []

    def record_action(
        self,
        name: str,
        action_fn: Callable[[], Any],
        *,
        readback_fn: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        Attempt a single shutdown action, catching BaseException to ensure
        all subsequent actions can still be attempted.
        """
        t0 = time.time()
        try:
            action_fn()
            dur = time.time() - t0
            readback_ok = False
            if readback_fn is not None:
                try:
                    readback_ok = bool(readback_fn())
                except BaseException:
                    readback_ok = False
            action = SafetyAction(
                name=name,
                attempted=True,
                succeeded=True,
                duration_seconds=dur,
                readback_verified=readback_ok,
            )
            self.actions.append(action)
            return True
        except BaseException as exc:
            dur = time.time() - t0
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                if self.interrupt_exc is None:
                    self.interrupt_exc = exc
            self.failures.append((name, exc))
            action = SafetyAction(
                name=name,
                attempted=True,
                succeeded=False,
                duration_seconds=dur,
                error=str(exc) or repr(exc),
                readback_verified=False,
            )
            self.actions.append(action)
            return False

    def build_report(self) -> SafetyReport:
        """Build an immutable SafetyReport summarizing all attempted actions."""
        if not self.actions:
            return SafetyReport(
                status=SafetyStatus.SAFE,
                summary="No shutdown actions registered",
            )
        all_succeeded = all(a.succeeded for a in self.actions)
        all_readback = all_succeeded and all(
            a.readback_verified for a in self.actions if a.succeeded
        )
        if all_succeeded:
            return SafetyReport(
                status=SafetyStatus.SAFE,
                actions=tuple(self.actions),
                readback_verified=all_readback,
                summary="All shutdown actions succeeded",
            )
        else:
            err_msgs = [
                f"{a.name}: {a.error}" for a in self.actions if not a.succeeded
            ]
            err_summary = "; ".join(err_msgs)
            return SafetyReport(
                status=SafetyStatus.UNSAFE,
                actions=tuple(self.actions),
                readback_verified=False,
                error=err_summary,
                summary=f"Shutdown actions failed: {err_summary}",
            )


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


# ============================================================================
# 3b. Snapshots and Events (Section 6.1 & 6.2)
# ============================================================================

class SnapshotViews(collections.abc.Mapping):
    """
    Read-only view mapping that defensively copies DataFrames upon retrieval (Section 6.1).
    """

    def __init__(self, views: Optional[Mapping[str, pd.DataFrame]] = None) -> None:
        self._views: Dict[str, pd.DataFrame] = {}
        if views:
            for k, v in views.items():
                if isinstance(v, pd.DataFrame):
                    self._views[str(k)] = v.copy(deep=True)
                else:
                    self._views[str(k)] = copy.deepcopy(v)

    def __getitem__(self, key: str) -> pd.DataFrame:
        v = self._views[key]
        return v.copy(deep=True) if isinstance(v, pd.DataFrame) else copy.deepcopy(v)

    def __iter__(self):
        return iter(self._views)

    def __len__(self) -> int:
        return len(self._views)

    def __contains__(self, key: object) -> bool:
        return key in self._views

    def keys(self):
        return self._views.keys()

    def values(self):
        return [self[k] for k in self._views]

    def items(self):
        return [(k, self[k]) for k in self._views]

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._views:
            return self[key]
        return default

    def to_dict(self) -> Dict[str, pd.DataFrame]:
        return {k: self[k] for k in self._views}

    def __repr__(self) -> str:
        return f"SnapshotViews({list(self._views.keys())})"


class MeasurementSnapshot:
    """
    Immutable, mutation-isolated snapshot of measurement state and bounded data views (Section 6.1).

    All DataFrame views are defensively copied on construction and on retrieval so consumer
    or UI mutations cannot corrupt internal measurement buffers or subsequent queries.
    """

    def __init__(
        self,
        run_id: Optional[str],
        generation: int,
        sequence: int,
        state: Union[RunState, str],
        safety: Union[SafetyStatus, str] = SafetyStatus.UNKNOWN,
        completed_steps: int = 0,
        total_steps: Optional[int] = None,
        message: str = "",
        views: Optional[Mapping[str, pd.DataFrame]] = None,
        timestamp: Optional[float] = None,
        **extra: Any,
    ) -> None:
        object.__setattr__(self, "_run_id", str(run_id) if run_id is not None else None)
        object.__setattr__(self, "_generation", int(generation))
        object.__setattr__(self, "_sequence", int(sequence))
        object.__setattr__(
            self, "_state", RunState(state) if isinstance(state, str) else state
        )
        object.__setattr__(
            self,
            "_safety",
            SafetyStatus(safety) if isinstance(safety, str) else safety,
        )
        object.__setattr__(self, "_completed_steps", int(completed_steps))
        object.__setattr__(
            self,
            "_total_steps",
            int(total_steps) if total_steps is not None else None,
        )
        object.__setattr__(self, "_message", str(message))
        object.__setattr__(
            self, "_timestamp", float(timestamp) if timestamp is not None else time.time()
        )
        object.__setattr__(self, "_views", SnapshotViews(views))
        object.__setattr__(self, "_extra", MappingProxyType(dict(extra)))

    @property
    def run_id(self) -> Optional[str]:
        return self._run_id

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def sequence(self) -> int:
        return self._sequence

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def safety(self) -> SafetyStatus:
        return self._safety

    @property
    def completed_steps(self) -> int:
        return self._completed_steps

    @property
    def total_steps(self) -> Optional[int]:
        return self._total_steps

    @property
    def message(self) -> str:
        return self._message

    @property
    def status_message(self) -> str:
        return self._message

    @property
    def timestamp(self) -> float:
        return self._timestamp

    @property
    def views(self) -> SnapshotViews:
        return self._views

    def get_view(self, name: str) -> Optional[pd.DataFrame]:
        """Returns a defensively copied DataFrame view if present, else None."""
        if name in self._views:
            return self._views[name]
        return None

    @property
    def raw_window(self) -> Optional[pd.DataFrame]:
        """Bounded raw window view (e.g. MOKE raw window points)."""
        if "raw_window" in self._views:
            return self.get_view("raw_window")
        if "raw" in self._views:
            return self.get_view("raw")
        return None

    @property
    def raw(self) -> Optional[pd.DataFrame]:
        """Alias for raw_window."""
        return self.raw_window

    @property
    def last_cycle(self) -> Optional[pd.DataFrame]:
        """Bounded last cycle view."""
        return self.get_view("last_cycle")

    @property
    def cycle_average(self) -> Optional[pd.DataFrame]:
        """Bounded cycle average view."""
        return self.get_view("cycle_average")

    def __getitem__(self, key: str) -> Any:
        if key == "run_id":
            return self.run_id
        elif key == "generation":
            return self.generation
        elif key == "sequence":
            return self.sequence
        elif key == "state":
            return self.state.value if isinstance(self.state, RunState) else self.state
        elif key == "safety":
            return self.safety.value if isinstance(self.safety, SafetyStatus) else self.safety
        elif key == "completed_steps":
            return self.completed_steps
        elif key == "total_steps":
            return self.total_steps
        elif key in ("message", "status_message"):
            return self.message
        elif key == "timestamp":
            return self.timestamp
        elif key == "views":
            return self.views
        elif key in self._views:
            return self.get_view(key)
        elif key in self._extra:
            return self._extra[key]
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        if key in {
            "run_id",
            "generation",
            "sequence",
            "state",
            "safety",
            "completed_steps",
            "total_steps",
            "message",
            "status_message",
            "timestamp",
            "views",
        }:
            return True
        if key in self._views or key in self._extra:
            return True
        return False

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def keys(self) -> Sequence[str]:
        standard = [
            "run_id",
            "generation",
            "sequence",
            "state",
            "safety",
            "completed_steps",
            "total_steps",
            "message",
            "timestamp",
            "views",
        ]
        return standard + list(self._views.keys()) + list(self._extra.keys())

    def __getattr__(self, name: str) -> Any:
        if "_extra" in self.__dict__ and name in self._extra:
            return self._extra[name]
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"'{type(self).__name__}' object is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"'{type(self).__name__}' object is immutable")

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "run_id": self.run_id,
            "generation": self.generation,
            "sequence": self.sequence,
            "state": self.state.value if isinstance(self.state, RunState) else str(self.state),
            "safety": self.safety.value if isinstance(self.safety, SafetyStatus) else str(self.safety),
            "completed_steps": self.completed_steps,
            "total_steps": self.total_steps,
            "message": self.message,
            "timestamp": self.timestamp,
            "views": self._views.to_dict(),
        }
        d.update(self._extra)
        return d

    def __repr__(self) -> str:
        views_keys = list(self._views.keys())
        return (
            f"MeasurementSnapshot(run_id={self.run_id!r}, gen={self.generation}, "
            f"seq={self.sequence}, state={self.state.value if isinstance(self.state, RunState) else self.state}, "
            f"views={views_keys})"
        )


@dataclass(frozen=True)
class StateChangeEvent:
    """
    Event emitted upon every forward legal state transition (Section 6.2).
    """

    run_id: str
    generation: int
    from_state: RunState
    to_state: RunState
    timestamp: float = field(default_factory=time.time)
    message: str = ""


@dataclass(frozen=True)
class SafetyAlertEvent:
    """
    Immediate safety alert event emitted when any required shutdown action fails (Section 4.4 & 6.2).
    """

    run_id: str
    generation: int
    safety_status: SafetyStatus
    report: SafetyReport
    timestamp: float = field(default_factory=time.time)
    message: str = ""


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
    final_snapshot: Optional[MeasurementSnapshot] = None


class DisplayQueue:
    """
    Bounded coalescing display queue for high-rate snapshot updates (Section 6.2).

    When queue capacity is saturated (len >= maxsize), oldest snapshots are discarded
    to ensure the publisher thread never blocks. Dropped snapshot count is tracked.
    """

    def __init__(self, maxsize: int = 1) -> None:
        if maxsize <= 0:
            raise ValueError(f"DisplayQueue maxsize must be >= 1, got {maxsize}")
        self._maxsize = int(maxsize)
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._deque: collections.deque[MeasurementSnapshot] = collections.deque()
        self._dropped_count = 0

    @property
    def maxsize(self) -> int:
        """Maximum capacity of the display queue."""
        return self._maxsize

    @property
    def dropped_count(self) -> int:
        """Total number of snapshots dropped due to queue saturation."""
        with self._lock:
            return self._dropped_count

    def put(self, snapshot: MeasurementSnapshot) -> None:
        """
        Pushes a snapshot into the queue without blocking.
        If queue is at capacity, the oldest unread snapshot is dropped.
        """
        if not isinstance(snapshot, MeasurementSnapshot):
            raise TypeError(
                f"DisplayQueue only accepts MeasurementSnapshot, got {type(snapshot).__name__}"
            )
        with self._lock:
            if len(self._deque) >= self._maxsize:
                self._deque.popleft()
                self._dropped_count += 1
            self._deque.append(snapshot)
            self._not_empty.notify()

    def get(self, block: bool = True, timeout: Optional[float] = None) -> MeasurementSnapshot:
        """
        Retrieves the next snapshot from the queue.
        """
        with self._not_empty:
            if not block:
                if not self._deque:
                    raise queue.Empty
                return self._deque.popleft()

            if timeout is None:
                while not self._deque:
                    self._not_empty.wait()
                return self._deque.popleft()

            if timeout < 0:
                raise ValueError("timeout must be non-negative")

            endtime = time.monotonic() + timeout
            while not self._deque:
                remaining = endtime - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                self._not_empty.wait(remaining)
            return self._deque.popleft()

    def get_nowait(self) -> MeasurementSnapshot:
        """Non-blocking get. Raises queue.Empty if queue is empty."""
        return self.get(block=False)

    def empty(self) -> bool:
        """Returns True if queue is empty."""
        with self._lock:
            return len(self._deque) == 0

    def full(self) -> bool:
        """Returns True if queue is at capacity."""
        with self._lock:
            return len(self._deque) >= self._maxsize

    def qsize(self) -> int:
        """Current number of snapshots in queue."""
        with self._lock:
            return len(self._deque)

    def clear(self) -> None:
        """Clears all queued snapshots."""
        with self._lock:
            self._deque.clear()


class ControlQueue:
    """
    Unbounded, non-droppable FIFO control queue (Section 6.2).

    Transports StateChangeEvent, SafetyAlertEvent, and TerminalEvent in strict FIFO order.
    Queue saturation on the display path can never discard control or safety information.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[Any] = queue.Queue()

    def put(self, event: Any) -> None:
        """Pushes a control event into the FIFO queue."""
        self._queue.put(event)

    def get(self, block: bool = True, timeout: Optional[float] = None) -> Any:
        """Retrieves the next control event from the queue."""
        return self._queue.get(block=block, timeout=timeout)

    def get_nowait(self) -> Any:
        """Non-blocking get. Raises queue.Empty if queue is empty."""
        return self._queue.get_nowait()

    def empty(self) -> bool:
        """Returns True if queue is empty."""
        return self._queue.empty()

    def qsize(self) -> int:
        """Current number of queued control events."""
        return self._queue.qsize()


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
        self._on_state_change: Optional[
            Callable[[RunState, RunState, Optional[str]], None]
        ] = None

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
        cb = self._on_state_change
        if cb is not None:
            try:
                cb(current, next_state, reason)
            except Exception:
                pass

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
