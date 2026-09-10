"""
BaseMeasurement class implementing standardized lifecycle contracts, full-run engine,
and piecewise execution sessions / standalone scopes.

Fulfills Checkpoint 8, 9a, and 9b of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Public execution wrapper run_experiment() enforcing canonical ordering (Section 3.1 & 4.4);
- Stop-before-start zero-I/O aborts with safety NOT_NEEDED (Section 4.2 & 4.4);
- Safing guarantee and error precedence handling (Section 5.1 & 5.3);
- Outcome and persistence matrix compliance (Section 4.6);
- Single RunRecord and TerminalEvent per reservation (Section 4.4 & 6.2);
- Piecewise execution sessions via session() context manager (Section 4.5);
- Standalone configure_instruments() and capture_data() scopes (Section 4.5);
- Idle safe_shutdown() with command lease, and non-owner deferral (Section 4.3 & 5.1);
- Protected subclass hooks for configuration, acquisition, safing, analysis, and publication.
"""

from __future__ import annotations

import inspect
import threading
import time
from pathlib import Path
import io
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple, Union
import pandas as pd

from .contracts import (
    ConcurrentRunError,
    ControlQueue,
    DisplayQueue,
    HardwareSafetyError,
    IllegalStateTransitionError,
    LifecycleCoordinator,
    MeasurementSnapshot,
    ReservationToken,
    RunRecord,
    RunRequest,
    RunState,
    SafetyAction,
    SafetyAlertEvent,
    SafetyReport,
    SafetyStatus,
    ShutdownAttemptRecorder,
    StateChangeEvent,
    TerminalEvent,
)


class MeasurementSession:
    """
    Context manager representing a piecewise execution session (Section 4.5).

    Created via `measurement.session(*, save=False, save_partial=None, options=None)`.
    Owns one synchronous reservation and exactly one shutdown boundary on exit.
    """

    def __init__(
        self,
        measurement: BaseMeasurement,
        save: bool = False,
        save_partial: Optional[bool] = None,
        options: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._measurement = measurement
        self._save = save
        self._save_partial = save_partial
        self._options = options
        self._token: Optional[ReservationToken] = None
        self._request: Optional[RunRequest] = None
        self._start_time: float = 0.0
        self._captured: bool = False
        self._configured: bool = False

    @property
    def token(self) -> Optional[ReservationToken]:
        """Active reservation token for this session."""
        return self._token

    @property
    def run_state(self) -> RunState:
        """Current lifecycle run state."""
        return self._measurement.run_state

    @property
    def safety_status(self) -> SafetyStatus:
        """Current verified safety status."""
        return self._measurement.safety_status

    @property
    def data(self) -> Optional[pd.DataFrame]:
        """Analyzed result data, or raw partial data on abort/failure."""
        return self._measurement.data

    @property
    def raw_data(self) -> Optional[pd.DataFrame]:
        """Full raw acquisition data after completion."""
        return self._measurement.raw_data

    @property
    def filename(self) -> Optional[str]:
        """Path to successfully published completed data CSV, or None."""
        return self._measurement.filename

    @property
    def partial_filename(self) -> Optional[str]:
        """Path to published incomplete/aborted data CSV, or None."""
        return self._measurement.partial_filename

    def configure_instruments(self) -> None:
        """Configures instruments within the active session scope."""
        self._measurement._session_configure()

    def capture_data(
        self,
        *,
        on_update: Optional[Callable[[Any], None]] = None,
    ) -> pd.DataFrame:
        """Captures data within the active session scope (at most once)."""
        return self._measurement._session_capture(
            on_update=on_update
        )

    def safe_shutdown(self) -> SafetyReport:
        """Safely shuts down instruments within the session."""
        return self._measurement.safe_shutdown()

    def request_stop(self) -> None:
        """Requests cooperative stop."""
        self._measurement.request_stop()

    def __enter__(self) -> MeasurementSession:
        self._measurement._enter_session(
            self, self._save, self._save_partial, self._options
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        return self._measurement._exit_session(self, exc_type, exc_val, exc_tb)


class BaseMeasurement:
    """
    Base class for PIEC standardized measurement families.

    Owns the execution lifecycle coordinator, full-run engine, state inspection,
    stop/pause controls, event distribution, and history records.
    Subclasses implement protected hooks for instrument configuration, data capture,
    and setup-specific safe shutdown.
    """

    supports_pause: bool = False

    def __init__(
        self, *, output_dir=None, measurement_schema=None, column_units=None,
        raw_column_units=None, metadata=None,
    ) -> None:
        self.output_dir = Path(output_dir) if output_dir is not None else None
        self.measurement_schema = measurement_schema
        self.column_units = dict(column_units) if column_units is not None else None
        self.raw_column_units = dict(raw_column_units) if raw_column_units is not None else None
        self.measurement_metadata = dict(metadata or {})
        self.recoverable_staging_paths = ()
        self._coordinator = LifecycleCoordinator()
        self._coordinator._on_state_change = self._on_coordinator_state_change
        self._event_listeners: List[Callable[[TerminalEvent], None]] = []
        self._raw_data: Optional[pd.DataFrame] = None
        self._data: Optional[pd.DataFrame] = None
        self._filename: Optional[str] = None
        self._partial_filename: Optional[str] = None
        self._active_session: Optional[MeasurementSession] = None
        self._active_owner_thread_id: Optional[int] = None
        self._session_capture_count: int = 0
        self._last_safing_exc: Optional[BaseException] = None
        self._active_shutdown_recorder: Optional[ShutdownAttemptRecorder] = None

        # Checkpoint 10a: Snapshot and two-event-path state (Section 6.1 & 6.2)
        self._snapshot_lock = threading.Lock()
        self._snapshot_sequence: int = 0
        self._latest_snapshot: Optional[MeasurementSnapshot] = None
        self._display_queues: List[DisplayQueue] = []
        self._control_queues: List[ControlQueue] = []
        self._display_listeners: List[Callable[[MeasurementSnapshot], None]] = []
        self._control_listeners: List[
            Callable[[Union[StateChangeEvent, SafetyAlertEvent, TerminalEvent]], None]
        ] = []

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

    @property
    def active_session(self) -> Optional[MeasurementSession]:
        """Current active piecewise session context, if any."""
        return self._active_session

    def snapshot(self) -> MeasurementSnapshot:
        """
        Public snapshot query wrapper (Section 6.1).

        Thread-safe read-only snapshot of current measurement state with mutation-isolated views.
        """
        with self._snapshot_lock:
            if self._latest_snapshot is not None:
                return MeasurementSnapshot(
                    run_id=self._latest_snapshot.run_id,
                    generation=self._latest_snapshot.generation,
                    sequence=self._latest_snapshot.sequence,
                    state=self.run_state,
                    safety=self.safety_status,
                    completed_steps=self._latest_snapshot.completed_steps,
                    total_steps=self._latest_snapshot.total_steps,
                    message=self._latest_snapshot.message,
                    views=self._latest_snapshot.views,
                    timestamp=self._latest_snapshot.timestamp,
                    **self._latest_snapshot._extra,
                )
            else:
                active_tok = self.active_token
                return MeasurementSnapshot(
                    run_id=active_tok.run_id if active_tok is not None else None,
                    generation=active_tok.generation if active_tok is not None else self._coordinator.generation,
                    sequence=0,
                    state=self.run_state,
                    safety=self.safety_status,
                    completed_steps=0,
                    total_steps=None,
                    message="",
                    views={},
                )

    def publish_snapshot(
        self,
        views: Optional[Mapping[str, pd.DataFrame]] = None,
        *,
        message: str = "",
        completed_steps: int = 0,
        total_steps: Optional[int] = None,
        **extra: Any,
    ) -> MeasurementSnapshot:
        """
        Creates, stores, and publishes a fresh bounded snapshot (Section 6.1 & 6.2).

        - Defensively copies all DataFrame views under the snapshot lock.
        - Increments monotonic snapshot sequence number.
        - Updates latest snapshot.
        - Dispatches non-blocking to all registered DisplayQueues (dropping older if full).
        - Dispatches to registered display listeners.
        """
        with self._snapshot_lock:
            self._snapshot_sequence += 1
            seq = self._snapshot_sequence
            active_tok = self.active_token
            run_id = active_tok.run_id if active_tok is not None else ""
            generation = (
                active_tok.generation
                if active_tok is not None
                else self._coordinator.generation
            )
            state = self.run_state
            safety = self.safety_status

            snap = MeasurementSnapshot(
                run_id=run_id,
                generation=generation,
                sequence=seq,
                state=state,
                safety=safety,
                completed_steps=completed_steps,
                total_steps=total_steps,
                message=message,
                views=views or {},
                **extra,
            )
            self._latest_snapshot = snap
            queues = list(self._display_queues)
            listeners = list(self._display_listeners)

        for q in queues:
            try:
                q.put(snap)
            except Exception:
                pass

        for listener in listeners:
            try:
                listener(snap)
            except Exception:
                pass

        return snap

    def create_display_queue(self, maxsize: int = 1) -> DisplayQueue:
        """
        Creates, registers, and returns a bounded coalescing DisplayQueue (Section 6.2).
        """
        q = DisplayQueue(maxsize=maxsize)
        with self._snapshot_lock:
            self._display_queues.append(q)
        return q

    def remove_display_queue(self, queue: DisplayQueue) -> None:
        """Unregisters a DisplayQueue."""
        with self._snapshot_lock:
            if queue in self._display_queues:
                self._display_queues.remove(queue)

    def create_control_queue(self) -> ControlQueue:
        """
        Creates, registers, and returns an unbounded non-droppable ControlQueue (Section 6.2).
        """
        q = ControlQueue()
        with self._coordinator._state_lock:
            self._control_queues.append(q)
        return q

    def remove_control_queue(self, queue: ControlQueue) -> None:
        """Unregisters a ControlQueue."""
        with self._coordinator._state_lock:
            if queue in self._control_queues:
                self._control_queues.remove(queue)

    def add_display_listener(
        self, listener: Callable[[MeasurementSnapshot], None]
    ) -> None:
        """Registers a callback for display snapshot updates."""
        if not callable(listener):
            raise TypeError("Display listener must be callable")
        with self._snapshot_lock:
            if listener not in self._display_listeners:
                self._display_listeners.append(listener)

    def remove_display_listener(
        self, listener: Callable[[MeasurementSnapshot], None]
    ) -> None:
        """Unregisters a display snapshot callback."""
        with self._snapshot_lock:
            if listener in self._display_listeners:
                self._display_listeners.remove(listener)

    def add_control_listener(
        self,
        listener: Callable[
            [Union[StateChangeEvent, SafetyAlertEvent, TerminalEvent]], None
        ],
    ) -> None:
        """Registers a callback for control events (state changes, safety alerts, terminal events)."""
        if not callable(listener):
            raise TypeError("Control listener must be callable")
        with self._coordinator._state_lock:
            if listener not in self._control_listeners:
                self._control_listeners.append(listener)

    def remove_control_listener(
        self,
        listener: Callable[
            [Union[StateChangeEvent, SafetyAlertEvent, TerminalEvent]], None
        ],
    ) -> None:
        """Unregisters a control event callback."""
        with self._coordinator._state_lock:
            if listener in self._control_listeners:
                self._control_listeners.remove(listener)

    def _on_coordinator_state_change(
        self, from_state: RunState, to_state: RunState, reason: Optional[str] = None
    ) -> None:
        """Callback invoked by coordinator under lock on every state transition."""
        if from_state == to_state:
            return
        active_tok = self.active_token
        event = StateChangeEvent(
            run_id=active_tok.run_id if active_tok is not None else "",
            generation=(
                active_tok.generation
                if active_tok is not None
                else self._coordinator.generation
            ),
            from_state=from_state,
            to_state=to_state,
            message=reason or "",
        )
        self._dispatch_control_event(event)

    def _dispatch_control_event(
        self, event: Union[StateChangeEvent, SafetyAlertEvent, TerminalEvent]
    ) -> None:
        """Dispatches control events in order to registered queues and listeners."""
        with self._coordinator._state_lock:
            queues = list(self._control_queues)
            listeners = list(self._control_listeners)

        for q in queues:
            try:
                q.put(event)
            except Exception:
                pass

        for listener in listeners:
            try:
                listener(event)
            except Exception:
                pass

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

    def add_event_listener(self, listener: Callable[[TerminalEvent], None]) -> None:
        """Register a callback for terminal lifecycle events."""
        if not callable(listener):
            raise TypeError("Event listener must be callable")
        with self._coordinator._state_lock:
            if listener not in self._event_listeners:
                self._event_listeners.append(listener)

    def remove_event_listener(self, listener: Callable[[TerminalEvent], None]) -> None:
        """Unregister a terminal event callback."""
        with self._coordinator._state_lock:
            if listener in self._event_listeners:
                self._event_listeners.remove(listener)

    def _emit_terminal_event(self, record: RunRecord, data: Optional[pd.DataFrame]) -> None:
        """Emits exactly one terminal event to all registered listeners, queues, and control paths."""
        with self._coordinator._state_lock:
            listeners = list(self._event_listeners)

        # Build authoritative final snapshot (Section 6.2)
        with self._snapshot_lock:
            if self._latest_snapshot is not None:
                final_views = {
                    k: self._latest_snapshot.get_view(k)
                    for k in self._latest_snapshot.views
                }
                completed_steps = self._latest_snapshot.completed_steps
                total_steps = self._latest_snapshot.total_steps
                extra = dict(self._latest_snapshot._extra)
            else:
                final_views = {}
                completed_steps = 0
                total_steps = None
                extra = {}

            # Display views may be truncated or precede analysis. The terminal
            # data view must always describe the actual result, including empty.
            if data is not None:
                final_views["data"] = data.copy()

            final_snapshot = MeasurementSnapshot(
                run_id=record.run_id,
                generation=record.generation,
                sequence=self._snapshot_sequence,
                state=record.state,
                safety=record.safety.status,
                completed_steps=completed_steps,
                total_steps=total_steps,
                message=f"Terminal state {record.state.value}",
                views=final_views,
                **extra,
            )
            self._latest_snapshot = final_snapshot
            display_queues = list(self._display_queues)
            display_listeners = list(self._display_listeners)

        # Put final snapshot into display queues and notify display listeners
        for dq in display_queues:
            try:
                dq.put(final_snapshot)
            except Exception:
                pass
        for dl in display_listeners:
            try:
                dl(final_snapshot)
            except Exception:
                pass

        event = TerminalEvent(
            run_id=record.run_id,
            generation=record.generation,
            state=record.state,
            safety=record.safety,
            filename=record.filename,
            partial_filename=record.partial_filename,
            primary_error_phase=record.primary_error_phase,
            primary_error_type=record.primary_error_type,
            primary_error_message=record.primary_error_message,
            secondary_errors=record.secondary_errors,
            record=record,
            data=data.copy() if data is not None else None,
            final_snapshot=final_snapshot,
        )

        for listener in listeners:
            try:
                listener(event)
            except Exception:
                # Listener failures must never corrupt measurement lifecycle or mask errors
                pass

        # Dispatch to control queues and listeners
        self._dispatch_control_event(event)

    # ========================================================================
    # Full-Run Execution Engine (Section 4.4 & 4.6)
    # ========================================================================

    def run_experiment(
        self,
        *,
        on_update: Optional[Callable[[Any], None]] = None,
        save: bool = True,
        save_partial: Optional[bool] = None,
        options: Optional[Mapping[str, Any]] = None,
        token: Optional[ReservationToken] = None,
    ) -> pd.DataFrame:
        """
        Public full-run execution wrapper (Section 3.1 & 4.4).

        Executes the canonical full-run ordering:
        1. Reserve generation and enter STARTING (or accept existing token).
        2. Check Stop-before-start; if latched, finalize as ABORTED without I/O.
        3. Enter CONFIGURING and configure instruments with outputs disabled.
        4. Atomically choose RUNNING or STOPPING based on cancellation.
        5. Capture data. A callback failure is an acquisition failure.
        6. Enter SAFING immediately after configuration/acquisition finishes or raises.
        7. Attempt every required shutdown action and record safety report.
        8. Only when acquisition completed and safing succeeded, enter ANALYZING.
        9. If saving requested, enter SAVING and publish data.
        10. On abort or failure, skip scientific analysis and optionally stage partial artifact.
        11. Record diagnostics/history, finalize RunRecord, and emit TerminalEvent.
        12. Re-raise primary error (or HardwareSafetyError if cleanup failed), otherwise return data.
        """
        if self._active_session is not None:
            raise ConcurrentRunError(
                "Cannot call run_experiment() while a session is active."
            )

        self._validate_options(options)
        request = RunRequest(
            on_update=on_update,
            save=save,
            save_partial=save_partial,
            options=options,
        )

        current_thread = threading.get_ident()
        # Claim execution before touching results or entering cleanup. A rejected
        # caller must never safe hardware owned by another invocation.
        if token is None:
            with self._coordinator._state_lock:
                if self._active_owner_thread_id is not None:
                    raise ConcurrentRunError("Previous execution owner has not returned")
            token = self._reserve(request)
        with self._coordinator._state_lock:
            self._validate_token(token)
            self._active_owner_thread_id = current_thread
        start_time = time.time()

        try:
            # Reset active results for this run
            self._raw_data = None
            self._data = None
            self._filename = None
            self.recoverable_staging_paths = ()
            self._partial_filename = None

            # Step 2: Stop-before-start check (Section 4.2 & 4.4)
            if self._coordinator.is_stop_requested:
                if self.run_state != RunState.STOPPING:
                    self._transition_to(
                        RunState.STOPPING, "Stop requested before I/O"
                    )
                self._transition_to(
                    RunState.ABORTED, "Aborted before I/O began"
                )
                safety = SafetyReport(
                    status=SafetyStatus.NOT_NEEDED,
                    summary="Stop requested before instrument I/O began",
                )
                record = RunRecord(
                    run_id=token.run_id,
                    generation=token.generation,
                    start_time=start_time,
                    end_time=time.time(),
                    state=RunState.ABORTED,
                    safety=safety,
                    save_requested=False,
                )
                self._record_run(record)
                self._data = pd.DataFrame()
                self._emit_terminal_event(record, self._data)
                return self._data

            primary_error: Optional[BaseException] = None
            primary_error_tb = None
            primary_error_phase: Optional[str] = None
            configured_ok = False
            safety_report: Optional[SafetyReport] = None
            sec_errors: List[str] = []

            try:
                # Step 3: Configure instruments
                self._transition_to(
                    RunState.CONFIGURING, "Configuring instruments"
                )
                try:
                    self._configure_instruments(request)
                    configured_ok = True
                except BaseException as exc:
                    primary_error = exc
                    primary_error_tb = getattr(exc, "__traceback__", None)
                    primary_error_phase = "CONFIGURING"

                # Step 4 & 5: Capture data
                if configured_ok:
                    if self._coordinator.is_stop_requested:
                        if self.run_state != RunState.STOPPING:
                            self._transition_to(
                                RunState.STOPPING,
                                "Stop requested before acquisition",
                            )
                    else:
                        self._transition_to(
                            RunState.RUNNING, "Starting acquisition"
                        )
                        try:
                            raw = self._capture_data(
                                request, on_update=on_update
                            )
                            self._raw_data = (
                                raw.copy()
                                if raw is not None
                                else pd.DataFrame()
                            )
                        except BaseException as exc:
                            primary_error = exc
                            primary_error_tb = getattr(exc, "__traceback__", None)
                            primary_error_phase = "RUNNING"

                        if (
                            self._coordinator.is_stop_requested
                            and self.run_state == RunState.RUNNING
                        ):
                            self._transition_to(
                                RunState.STOPPING,
                                "Stop requested during acquisition",
                            )

            finally:
                # Step 6 & 7: Safing
                if (
                    self.run_state.is_active
                    and self.run_state != RunState.STARTING
                ):
                    if self.run_state != RunState.SAFING:
                        try:
                            self._transition_to(
                                RunState.SAFING, "Performing safe shutdown"
                            )
                        except IllegalStateTransitionError:
                            pass

                    safety_report = self._perform_safe_shutdown()
                    if self._last_safing_exc is not None:
                        if primary_error is None:
                            if isinstance(
                                self._last_safing_exc,
                                (KeyboardInterrupt, SystemExit),
                            ):
                                primary_error = self._last_safing_exc
                                primary_error_tb = getattr(
                                    self._last_safing_exc, "__traceback__", None
                                )
                                primary_error_phase = "SAFING"
                        else:
                            sec_errors.append(
                                f"Shutdown error: {safety_report.error or self._last_safing_exc}"
                            )

                if safety_report is None:
                    safety_report = SafetyReport(status=SafetyStatus.NOT_NEEDED)

            # Step 8, 9, 10: Analysis and Persistence (Section 4.4 & 4.6)
            target_outcome = RunState.COMPLETED
            if primary_error is not None:
                target_outcome = RunState.FAILED
            elif self._coordinator.is_stop_requested:
                target_outcome = RunState.ABORTED
            elif safety_report.status == SafetyStatus.UNSAFE:
                target_outcome = RunState.FAILED

            if target_outcome == RunState.COMPLETED:
                # Step 8: Analyze
                self._transition_to(RunState.ANALYZING, "Analyzing data")
                raw_to_analyze = (
                    self._raw_data.copy()
                    if self._raw_data is not None
                    else pd.DataFrame()
                )
                try:
                    analyzed = self._analyze_data(raw_to_analyze, request)
                    self._data = (
                        analyzed.copy()
                        if analyzed is not None
                        else pd.DataFrame()
                    )
                except BaseException as exc:
                    primary_error = exc
                    primary_error_tb = getattr(exc, "__traceback__", None)
                    primary_error_phase = "ANALYZING"
                    target_outcome = RunState.FAILED

                # Step 9: Save
                if target_outcome == RunState.COMPLETED:
                    if request.save:
                        self._transition_to(
                            RunState.SAVING, "Publishing completed data"
                        )
                        try:
                            self._publication_outcome = target_outcome
                            self._filename = self._publish_data(
                                self._data, request, is_partial=False
                            )
                            self._transition_to(
                                RunState.COMPLETED, "Completed successfully"
                            )
                        except BaseException as exc:
                            primary_error = exc
                            primary_error_tb = getattr(exc, "__traceback__", None)
                            primary_error_phase = "SAVING"
                            self._transition_to(
                                RunState.FAILED, "Publication failed"
                            )
                            target_outcome = RunState.FAILED
                    else:
                        self._transition_to(
                            RunState.COMPLETED, "Completed without saving"
                        )

            if target_outcome == RunState.ABORTED:
                # Analysis skipped; data is raw partial data
                self._data = (
                    self._raw_data.copy()
                    if self._raw_data is not None
                    else pd.DataFrame()
                )
                should_save_partial = (
                    request.save_partial
                    if request.save_partial is not None
                    else (
                        request.save
                        and self._data is not None
                        and not self._data.empty
                    )
                )
                if (
                    should_save_partial
                    and self._data is not None
                    and not self._data.empty
                ):
                    self._transition_to(
                        RunState.SAVING, "Publishing partial data"
                    )
                    try:
                        self._publication_outcome = target_outcome
                        self._partial_filename = self._publish_data(
                            self._data, request, is_partial=True
                        )
                        self._transition_to(
                            RunState.ABORTED, "Aborted with partial data saved"
                        )
                    except BaseException as exc:
                        primary_error = exc
                        primary_error_tb = getattr(exc, "__traceback__", None)
                        primary_error_phase = "SAVING"
                        self._transition_to(
                            RunState.FAILED, "Partial save failed after abort"
                        )
                        target_outcome = RunState.FAILED
                else:
                    self._transition_to(
                        RunState.ABORTED, "Aborted without saving partial"
                    )

            if target_outcome == RunState.FAILED:
                # Analysis skipped; data is raw partial data
                self._data = (
                    self._raw_data.copy()
                    if self._raw_data is not None
                    else pd.DataFrame()
                )
                should_save_partial = (
                    request.save_partial
                    if request.save_partial is not None
                    else False
                )
                if (
                    should_save_partial
                    and self._data is not None
                    and not self._data.empty
                ):
                    try:
                        if self.run_state in {
                            RunState.SAFING,
                            RunState.ANALYZING,
                        }:
                            self._transition_to(
                                RunState.SAVING,
                                "Publishing partial data on failure",
                            )
                            self._publication_outcome = target_outcome
                            self._partial_filename = self._publish_data(
                                self._data, request, is_partial=True
                            )
                    except BaseException as exc:
                        sec_errors.append(f"Partial save error: {exc}")

                if self.run_state in {
                    RunState.SAFING,
                    RunState.ANALYZING,
                    RunState.SAVING,
                }:
                    self._transition_to(RunState.FAILED, "Run failed")

            # Step 11: Finalize record and emit event
            end_time = time.time()
            if (
                primary_error_phase != "SAFING"
                and safety_report.status == SafetyStatus.UNSAFE
            ):
                err_msg = f"Shutdown error: {safety_report.error or safety_report.summary}"
                if err_msg not in sec_errors:
                    sec_errors.append(err_msg)

            record = RunRecord(
                run_id=token.run_id,
                generation=token.generation,
                start_time=start_time,
                end_time=end_time,
                state=self.run_state,
                safety=safety_report,
                save_requested=request.save,
                filename=self._filename,
                partial_filename=self._partial_filename,
                primary_error_phase=primary_error_phase,
                primary_error_type=(
                    type(primary_error).__name__
                    if primary_error is not None
                    else None
                ),
                primary_error_message=(
                    str(primary_error) if primary_error is not None else None
                ),
                secondary_errors=tuple(sec_errors),
                metadata={"recoverable_staging_paths": self.recoverable_staging_paths},
                snapshot_count=0,
            )
            try:
                self._record_run(record)
            except Exception:
                pass
            try:
                self._emit_terminal_event(record, self._data)
            except Exception:
                pass

            # Step 12: Re-raise error or return data
            if primary_error is not None:
                if (
                    primary_error_tb is not None
                    and getattr(primary_error, "__traceback__", None)
                    is not primary_error_tb
                ):
                    raise primary_error.with_traceback(primary_error_tb)
                raise primary_error
            if safety_report.status == SafetyStatus.UNSAFE:
                raise HardwareSafetyError(
                    f"Hardware safety could not be verified: {safety_report.error or safety_report.summary}",
                    safety_report=safety_report,
                )

            return self._data
        finally:
            self._active_owner_thread_id = None

    # ========================================================================
    # Sessions & Standalone Scopes (Section 4.5 & 5.1)
    # ========================================================================

    def session(
        self,
        *,
        save: bool = False,
        save_partial: Optional[bool] = None,
        options: Optional[Mapping[str, Any]] = None,
    ) -> MeasurementSession:
        """
        Public piecewise session context manager (Section 3.1 & 4.5).

        Creates one synchronous reservation bound to the calling thread and owns
        exactly one shutdown boundary on exit. Default save is False.
        """
        return MeasurementSession(
            measurement=self,
            save=save,
            save_partial=save_partial,
            options=options,
        )

    def configure_instruments(self) -> None:
        """
        Public instrument configuration wrapper (Section 3.1 & 4.5).

        - Inside an active session on owner thread: executes within session scope without creating nested reservations.
        - Outside session: transient operation scope that enters CONFIGURING, executes configuration hook,
          safes on exit, and transitions to COMPLETED without analyzing or saving.
        """
        current_thread = threading.get_ident()
        if self._active_session is not None:
            if self._active_owner_thread_id != current_thread:
                raise ConcurrentRunError(
                    "Cross-thread hardware-bearing calls are rejected while another thread owns execution"
                )
            self._session_configure()
            return

        if (
            self._active_owner_thread_id is not None
            and self._active_owner_thread_id != current_thread
        ):
            raise ConcurrentRunError(
                "Cross-thread hardware-bearing calls are rejected while another thread owns execution"
            )

        # Standalone transient scope
        self._validate_options(None)
        request = RunRequest(save=False, save_partial=False)
        token = self._reserve(request)
        self._active_owner_thread_id = current_thread
        start_time = time.time()

        self._raw_data = None
        self._data = None
        self._filename = None
        self.recoverable_staging_paths = ()
        self._partial_filename = None

        if self._coordinator.is_stop_requested:
            self._transition_to(
                RunState.STOPPING, "Stop requested before configuration"
            )
            self._transition_to(RunState.ABORTED, "Aborted before I/O began")
            safety = SafetyReport(status=SafetyStatus.NOT_NEEDED)
            record = RunRecord(
                run_id=token.run_id,
                generation=token.generation,
                start_time=start_time,
                end_time=time.time(),
                state=RunState.ABORTED,
                safety=safety,
                save_requested=False,
            )
            self._record_run(record)
            self._emit_terminal_event(record, pd.DataFrame())
            self._active_owner_thread_id = None
            return

        primary_error: Optional[BaseException] = None
        primary_error_tb = None
        primary_error_phase: Optional[str] = None
        safety_report: Optional[SafetyReport] = None
        sec_errors: List[str] = []

        try:
            self._validate_token(token)
            self._transition_to(RunState.CONFIGURING, "Configuring instruments")
            self._configure_instruments(request)
        except BaseException as exc:
            primary_error = exc
            primary_error_tb = getattr(exc, "__traceback__", None)
            primary_error_phase = "CONFIGURING"
        finally:
            if self.run_state.is_active:
                if self.run_state != RunState.SAFING:
                    try:
                        self._transition_to(
                            RunState.SAFING, "Performing safe shutdown"
                        )
                    except IllegalStateTransitionError:
                        pass
                safety_report = self._perform_safe_shutdown()
                if self._last_safing_exc is not None:
                    if primary_error is None:
                        if isinstance(
                            self._last_safing_exc, (KeyboardInterrupt, SystemExit)
                        ):
                            primary_error = self._last_safing_exc
                            primary_error_tb = getattr(
                                self._last_safing_exc, "__traceback__", None
                            )
                            primary_error_phase = "SAFING"
                    else:
                        sec_errors.append(
                            f"Shutdown error: {safety_report.error or self._last_safing_exc}"
                        )

            if safety_report is None:
                safety_report = SafetyReport(status=SafetyStatus.NOT_NEEDED)

            target_outcome = RunState.COMPLETED
            if (
                primary_error is not None
                or safety_report.status == SafetyStatus.UNSAFE
            ):
                target_outcome = RunState.FAILED
            elif self._coordinator.is_stop_requested:
                target_outcome = RunState.ABORTED

            self._transition_to(
                target_outcome, f"Configuration finished ({target_outcome.value})"
            )

            if (
                primary_error_phase != "SAFING"
                and safety_report.status == SafetyStatus.UNSAFE
            ):
                err_msg = f"Shutdown error: {safety_report.error or safety_report.summary}"
                if err_msg not in sec_errors:
                    sec_errors.append(err_msg)

            record = RunRecord(
                run_id=token.run_id,
                generation=token.generation,
                start_time=start_time,
                end_time=time.time(),
                state=self.run_state,
                safety=safety_report,
                save_requested=False,
                primary_error_phase=primary_error_phase,
                primary_error_type=(
                    type(primary_error).__name__
                    if primary_error is not None
                    else None
                ),
                primary_error_message=(
                    str(primary_error) if primary_error is not None else None
                ),
                secondary_errors=tuple(sec_errors),
                metadata={"recoverable_staging_paths": self.recoverable_staging_paths},
            )
            try:
                self._record_run(record)
            except Exception:
                pass
            try:
                self._emit_terminal_event(record, pd.DataFrame())
            except Exception:
                pass
            self._active_owner_thread_id = None

        if primary_error is not None:
            if (
                primary_error_tb is not None
                and getattr(primary_error, "__traceback__", None)
                is not primary_error_tb
            ):
                raise primary_error.with_traceback(primary_error_tb)
            raise primary_error
        if safety_report.status == SafetyStatus.UNSAFE:
            raise HardwareSafetyError(
                f"Hardware safety could not be verified: {safety_report.error or safety_report.summary}",
                safety_report=safety_report,
            )

    def capture_data(
        self,
        *,
        on_update: Optional[Callable[[Any], None]] = None,
    ) -> pd.DataFrame:
        """
        Public data capture wrapper (Section 3.1 & 4.5).

        - Inside an active session on owner thread: delegates within session scope without a second cleanup.
        - Outside session: transient capture scope that passes through CONFIGURING for prerequisite validation,
          runs acquisition, safes on exit, and transitions to COMPLETED without analyzing or saving. Returns raw DataFrame.
        """
        current_thread = threading.get_ident()
        if self._active_session is not None:
            if self._active_owner_thread_id != current_thread:
                raise ConcurrentRunError(
                    "Cross-thread hardware-bearing calls are rejected while another thread owns execution"
                )
            return self._session_capture(on_update=on_update)

        if (
            self._active_owner_thread_id is not None
            and self._active_owner_thread_id != current_thread
        ):
            raise ConcurrentRunError(
                "Cross-thread hardware-bearing calls are rejected while another thread owns execution"
            )

        # Standalone transient scope
        self._validate_options(None)
        request = RunRequest(
            on_update=on_update,
            save=False,
            save_partial=False,
        )
        token = self._reserve(request)
        self._active_owner_thread_id = current_thread
        start_time = time.time()

        self._raw_data = None
        self._data = None
        self._filename = None
        self.recoverable_staging_paths = ()
        self._partial_filename = None

        if self._coordinator.is_stop_requested:
            self._transition_to(
                RunState.STOPPING, "Stop requested before capture"
            )
            self._transition_to(RunState.ABORTED, "Aborted before I/O began")
            safety = SafetyReport(status=SafetyStatus.NOT_NEEDED)
            record = RunRecord(
                run_id=token.run_id,
                generation=token.generation,
                start_time=start_time,
                end_time=time.time(),
                state=RunState.ABORTED,
                safety=safety,
                save_requested=False,
            )
            self._record_run(record)
            self._data = pd.DataFrame()
            self._emit_terminal_event(record, self._data)
            self._active_owner_thread_id = None
            return self._data

        primary_error: Optional[BaseException] = None
        primary_error_tb = None
        primary_error_phase: Optional[str] = None
        safety_report: Optional[SafetyReport] = None
        configured_ok = False
        sec_errors: List[str] = []

        try:
            self._validate_token(token)
            # Pass through CONFIGURING for prerequisite validation
            self._transition_to(
                RunState.CONFIGURING, "Validating prerequisites"
            )
            try:
                self._configure_instruments(request)
                configured_ok = True
            except BaseException as exc:
                primary_error = exc
                primary_error_tb = getattr(exc, "__traceback__", None)
                primary_error_phase = "CONFIGURING"

            if configured_ok:
                if self._coordinator.is_stop_requested:
                    if self.run_state != RunState.STOPPING:
                        self._transition_to(
                            RunState.STOPPING, "Stop requested before acquisition"
                        )
                else:
                    self._transition_to(
                        RunState.RUNNING, "Starting standalone acquisition"
                    )
                    try:
                        raw = self._capture_data(request, on_update=on_update)
                        self._raw_data = (
                            raw.copy() if raw is not None else pd.DataFrame()
                        )
                        self._data = self._raw_data.copy()
                    except BaseException as exc:
                        primary_error = exc
                        primary_error_tb = getattr(exc, "__traceback__", None)
                        primary_error_phase = "RUNNING"

                    if (
                        self._coordinator.is_stop_requested
                        and self.run_state == RunState.RUNNING
                    ):
                        self._transition_to(
                            RunState.STOPPING,
                            "Stop requested during acquisition",
                        )
        finally:
            if self.run_state.is_active:
                if self.run_state != RunState.SAFING:
                    try:
                        self._transition_to(
                            RunState.SAFING, "Performing safe shutdown"
                        )
                    except IllegalStateTransitionError:
                        pass
                safety_report = self._perform_safe_shutdown()
                if self._last_safing_exc is not None:
                    if primary_error is None:
                        if isinstance(
                            self._last_safing_exc, (KeyboardInterrupt, SystemExit)
                        ):
                            primary_error = self._last_safing_exc
                            primary_error_tb = getattr(
                                self._last_safing_exc, "__traceback__", None
                            )
                            primary_error_phase = "SAFING"
                    else:
                        sec_errors.append(
                            f"Shutdown error: {safety_report.error or self._last_safing_exc}"
                        )

            if safety_report is None:
                safety_report = SafetyReport(status=SafetyStatus.NOT_NEEDED)

            target_outcome = RunState.COMPLETED
            if (
                primary_error is not None
                or safety_report.status == SafetyStatus.UNSAFE
            ):
                target_outcome = RunState.FAILED
            elif self._coordinator.is_stop_requested:
                target_outcome = RunState.ABORTED

            self._transition_to(
                target_outcome, f"Capture finished ({target_outcome.value})"
            )

            if (
                primary_error_phase != "SAFING"
                and safety_report.status == SafetyStatus.UNSAFE
            ):
                err_msg = f"Shutdown error: {safety_report.error or safety_report.summary}"
                if err_msg not in sec_errors:
                    sec_errors.append(err_msg)

            record = RunRecord(
                run_id=token.run_id,
                generation=token.generation,
                start_time=start_time,
                end_time=time.time(),
                state=self.run_state,
                safety=safety_report,
                save_requested=False,
                primary_error_phase=primary_error_phase,
                primary_error_type=(
                    type(primary_error).__name__
                    if primary_error is not None
                    else None
                ),
                primary_error_message=(
                    str(primary_error) if primary_error is not None else None
                ),
                secondary_errors=tuple(sec_errors),
                metadata={"recoverable_staging_paths": self.recoverable_staging_paths},
            )
            try:
                self._record_run(record)
            except Exception:
                pass
            try:
                self._emit_terminal_event(record, self._data)
            except Exception:
                pass
            self._active_owner_thread_id = None

        if primary_error is not None:
            if (
                primary_error_tb is not None
                and getattr(primary_error, "__traceback__", None)
                is not primary_error_tb
            ):
                raise primary_error.with_traceback(primary_error_tb)
            raise primary_error
        if safety_report.status == SafetyStatus.UNSAFE:
            raise HardwareSafetyError(
                f"Hardware safety could not be verified: {safety_report.error or safety_report.summary}",
                safety_report=safety_report,
            )

        return self._data if self._data is not None else pd.DataFrame()

    def safe_shutdown(self) -> SafetyReport:
        """
        Public safe shutdown wrapper (Section 5.1).

        - If an active run or session is owned by another thread:
          Latches cooperative Stop and raises RuntimeError("Shutdown deferred to execution owner").
          Does not write hardware.
        - If called by the owner during an active run or session:
          Executes shutdown actions directly and returns SafetyReport.
        - If called when IDLE/terminal:
          Acquires idle command lease, executes shutdown actions, sets safety status,
          and returns SafetyReport.
        """
        current_thread = threading.get_ident()
        is_active = (
            self._coordinator.run_state.is_active
            or self._active_session is not None
        )

        if is_active:
            if (
                self._active_owner_thread_id is not None
                and self._active_owner_thread_id != current_thread
            ):
                self.request_stop()
                raise RuntimeError("Shutdown deferred to execution owner")
            report = self._perform_safe_shutdown()
            if self._last_safing_exc is not None and isinstance(
                self._last_safing_exc, (KeyboardInterrupt, SystemExit)
            ):
                raise self._last_safing_exc
            if report.status == SafetyStatus.UNSAFE:
                raise HardwareSafetyError(
                    f"Hardware safety could not be verified: {report.error or report.summary}",
                    safety_report=report,
                )
            return report

        with self._coordinator.idle_command_lease():
            report = self._perform_safe_shutdown()
            if self._last_safing_exc is not None and isinstance(
                self._last_safing_exc, (KeyboardInterrupt, SystemExit)
            ):
                raise self._last_safing_exc
            if report.status == SafetyStatus.UNSAFE:
                raise HardwareSafetyError(
                    f"Hardware safety could not be verified: {report.error or report.summary}",
                    safety_report=report,
                )
            return report

    def record_shutdown_action(
        self,
        name: str,
        action_fn: Callable[[], Any],
        *,
        readback_fn: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        Records and executes a single shutdown action via the active attempt recorder (Section 5.1).

        If called during safe shutdown, executes within the active attempt recorder catching
        BaseException so subsequent actions can still be attempted.
        Returns True if the action succeeded, False otherwise.
        """
        if getattr(self, "_active_shutdown_recorder", None) is not None:
            return self._active_shutdown_recorder.record_action(
                name, action_fn, readback_fn=readback_fn
            )
        try:
            action_fn()
            return True
        except BaseException:
            return False

    def _perform_safe_shutdown(self) -> SafetyReport:
        """
        Executes setup-specific safe shutdown hook through attempt recorder (Section 5.1 & 5.3).
        """
        self._last_safing_exc = None
        recorder = ShutdownAttemptRecorder()
        self._active_shutdown_recorder = recorder
        try:
            try:
                sig = inspect.signature(self._safe_shutdown)
                if len(sig.parameters) > 0:
                    raw_safety = self._safe_shutdown(recorder)
                else:
                    raw_safety = self._safe_shutdown()
            except TypeError:
                raw_safety = self._safe_shutdown()

            if isinstance(raw_safety, SafetyReport):
                safety_report = raw_safety
            elif isinstance(raw_safety, (list, tuple)):
                if (
                    raw_safety
                    and isinstance(raw_safety[0], (list, tuple))
                    and len(raw_safety[0]) >= 2
                ):
                    for item in raw_safety:
                        name = item[0]
                        fn = item[1]
                        rb = item[2] if len(item) > 2 else None
                        recorder.record_action(name, fn, readback_fn=rb)
                    safety_report = recorder.build_report()
                elif raw_safety and isinstance(raw_safety[0], SafetyAction):
                    all_ok = all(a.succeeded for a in raw_safety)
                    st = SafetyStatus.SAFE if all_ok else SafetyStatus.UNSAFE
                    all_rb = all_ok and all(
                        a.readback_verified for a in raw_safety
                    )
                    errs = [
                        f"{a.name}: {a.error}"
                        for a in raw_safety
                        if not a.succeeded
                    ]
                    safety_report = SafetyReport(
                        status=st,
                        actions=tuple(raw_safety),
                        readback_verified=all_rb,
                        error="; ".join(errs) if errs else None,
                        summary=(
                            "Safe shutdown completed"
                            if all_ok
                            else f"Shutdown failed: {'; '.join(errs)}"
                        ),
                    )
                elif not raw_safety:
                    safety_report = SafetyReport(
                        status=SafetyStatus.SAFE,
                        summary="Clean shutdown (empty action list)",
                    )
                else:
                    safety_report = recorder.build_report()
            elif recorder.actions:
                safety_report = recorder.build_report()
            else:
                safety_report = SafetyReport(
                    status=SafetyStatus.SAFE,
                    summary="Default clean safe shutdown",
                )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                if recorder.interrupt_exc is None:
                    recorder.interrupt_exc = exc
            self._last_safing_exc = exc
            action = SafetyAction(
                name="safe_shutdown",
                attempted=True,
                succeeded=False,
                error=str(exc) or repr(exc),
                readback_verified=False,
            )
            recorder.actions.append(action)
            safety_report = SafetyReport(
                status=SafetyStatus.UNSAFE,
                actions=tuple(recorder.actions),
                error=str(exc) or repr(exc),
                summary=f"Shutdown failed: {exc}",
            )
        finally:
            self._active_shutdown_recorder = None

        if recorder.interrupt_exc is not None:
            self._last_safing_exc = recorder.interrupt_exc

        if safety_report.actions and any(
            not a.succeeded for a in safety_report.actions
        ):
            if safety_report.status != SafetyStatus.UNSAFE:
                safety_report = SafetyReport(
                    status=SafetyStatus.UNSAFE,
                    actions=safety_report.actions,
                    readback_verified=False,
                    error=safety_report.error
                    or "One or more shutdown actions failed",
                    summary=safety_report.summary
                    or "One or more shutdown actions failed",
                )

        self._coordinator.set_safety_status(safety_report.status)
        if safety_report.status == SafetyStatus.UNSAFE:
            active_tok = self.active_token
            alert_event = SafetyAlertEvent(
                run_id=active_tok.run_id if active_tok is not None else "",
                generation=(
                    active_tok.generation
                    if active_tok is not None
                    else self._coordinator.generation
                ),
                safety_status=SafetyStatus.UNSAFE,
                report=safety_report,
                message=(
                    safety_report.error
                    or safety_report.summary
                    or "Safe shutdown failed"
                ),
            )
            self._dispatch_control_event(alert_event)
        return safety_report

    # ========================================================================
    # Internal Session Delegation Handlers
    # ========================================================================

    def _enter_session(
        self,
        session: MeasurementSession,
        save: bool,
        save_partial: Optional[bool],
        options: Optional[Mapping[str, Any]],
    ) -> None:
        """Called by MeasurementSession.__enter__."""
        self._validate_options(options)
        with self._coordinator._state_lock:
            if (
                self._coordinator.run_state.is_active
                or self._active_session is not None
            ):
                raise ConcurrentRunError(
                    "Cannot start session: another run or session is currently active "
                    f"(state: {self._coordinator.run_state.value})."
                )
            request = RunRequest(
                save=save,
                save_partial=save_partial,
                options=options,
            )
            token = self._reserve(request)
            session._token = token
            session._request = request
            session._start_time = time.time()
            self._active_session = session
            self._active_owner_thread_id = threading.get_ident()
            self._session_capture_count = 0

        # Reset active results for this session
        self._raw_data = None
        self._data = None
        self._filename = None
        self.recoverable_staging_paths = ()
        self._partial_filename = None

    def _session_configure(
        self, *, options: Optional[Mapping[str, Any]] = None
    ) -> None:
        """Session-scoped instrument configuration."""
        current_thread = threading.get_ident()
        if self._active_owner_thread_id != current_thread:
            raise ConcurrentRunError(
                "Cross-thread hardware-bearing calls are rejected while another thread owns execution"
            )
        if self._active_session is None:
            raise RuntimeError("No active session")

        if self.run_state == RunState.STARTING:
            self._transition_to(
                RunState.CONFIGURING, "Session configuring instruments"
            )
        elif self.run_state != RunState.CONFIGURING:
            raise IllegalStateTransitionError(
                f"Cannot configure instruments in state {self.run_state.value}"
            )

        request = self._active_session._request
        if options is not None:
            self._validate_options(options)
            opts = dict(request.options)
            opts.update(options)
            request = RunRequest(
                save=request.save,
                save_partial=request.save_partial,
                options=opts,
            )
            self._active_session._request = request

        self._configure_instruments(request)
        self._active_session._configured = True

    def _session_capture(
        self,
        *,
        on_update: Optional[Callable[[Any], None]] = None,
        options: Optional[Mapping[str, Any]] = None,
    ) -> pd.DataFrame:
        """Session-scoped data acquisition (at most once per session)."""
        current_thread = threading.get_ident()
        if self._active_owner_thread_id != current_thread:
            raise ConcurrentRunError(
                "Cross-thread hardware-bearing calls are rejected while another thread owns execution"
            )
        if self._active_session is None:
            raise RuntimeError("No active session")

        if self._session_capture_count >= 1:
            raise RuntimeError(
                "A session supports at most one capture operation; repeated acquisition belongs "
                "inside the concrete capture hook or in separate sessions."
            )
        self._session_capture_count += 1

        request = self._active_session._request
        if options is not None or on_update is not None:
            opts = dict(request.options)
            if options is not None:
                self._validate_options(options)
                opts.update(options)
            request = RunRequest(
                on_update=(
                    on_update if on_update is not None else request.on_update
                ),
                save=request.save,
                save_partial=request.save_partial,
                options=opts,
            )
            self._active_session._request = request

        # Prerequisite validation / transition
        if self.run_state == RunState.STARTING:
            self._transition_to(
                RunState.CONFIGURING, "Validating prerequisites"
            )
            self._configure_instruments(request)
            self._active_session._configured = True

        if self.run_state == RunState.CONFIGURING:
            if self._coordinator.is_stop_requested:
                self._transition_to(
                    RunState.STOPPING, "Stop requested before acquisition"
                )
                return pd.DataFrame()
            self._transition_to(
                RunState.RUNNING, "Starting session acquisition"
            )
        elif self.run_state != RunState.RUNNING:
            raise IllegalStateTransitionError(
                f"Cannot capture data in state {self.run_state.value}"
            )

        raw = self._capture_data(request, on_update=request.on_update)
        self._raw_data = raw.copy() if raw is not None else pd.DataFrame()
        self._data = self._raw_data.copy()
        self._active_session._captured = True

        if (
            self._coordinator.is_stop_requested
            and self.run_state == RunState.RUNNING
        ):
            self._transition_to(
                RunState.STOPPING, "Stop requested during acquisition"
            )

        return self._raw_data

    def _exit_session(
        self,
        session: MeasurementSession,
        exc_type,
        exc_val,
        exc_tb,
    ) -> bool:
        """Called by MeasurementSession.__exit__."""
        start_time = session._start_time
        token = session._token
        request = session._request
        primary_error = exc_val
        primary_error_tb = exc_tb
        primary_error_phase = "SESSION" if exc_val is not None else None
        safety_report: Optional[SafetyReport] = None
        sec_errors: List[str] = []

        try:
            # Step 1: Safing boundary
            if self.run_state.is_active:
                if (
                    not session._configured
                    and not session._captured
                    and (self.run_state == RunState.STOPPING or self._coordinator.is_stop_requested)
                ):
                    if self.run_state == RunState.STARTING:
                        self._transition_to(
                            RunState.STOPPING, "Stop requested in session before I/O"
                        )
                    if self.run_state == RunState.STOPPING:
                        self._transition_to(
                            RunState.ABORTED, "Aborted before I/O began"
                        )
                    safety_report = SafetyReport(
                        status=SafetyStatus.NOT_NEEDED,
                        summary="Stop requested before instrument I/O began",
                    )
                    self._coordinator.set_safety_status(safety_report.status)
                else:
                    if self.run_state == RunState.STARTING:
                        self._transition_to(
                            RunState.CONFIGURING,
                            "Transient configuration for safing",
                        )
                    if self.run_state != RunState.SAFING:
                        self._transition_to(
                            RunState.SAFING,
                            "Session exit safe shutdown",
                        )
                    safety_report = self._perform_safe_shutdown()
                    if self._last_safing_exc is not None:
                        if primary_error is None:
                            if isinstance(
                                self._last_safing_exc,
                                (KeyboardInterrupt, SystemExit),
                            ):
                                primary_error = self._last_safing_exc
                                primary_error_tb = getattr(
                                    self._last_safing_exc, "__traceback__", None
                                )
                                primary_error_phase = "SAFING"
                        else:
                            sec_errors.append(
                                f"Shutdown error: {safety_report.error or self._last_safing_exc}"
                            )

            if safety_report is None:
                safety_report = SafetyReport(status=SafetyStatus.NOT_NEEDED)

            # Step 2: Determine outcome
            target_outcome = RunState.COMPLETED
            if primary_error is not None:
                target_outcome = RunState.FAILED
            elif self._coordinator.is_stop_requested:
                target_outcome = RunState.ABORTED
            elif safety_report.status == SafetyStatus.UNSAFE:
                target_outcome = RunState.FAILED

            # Step 3: Analysis & Saving (Section 4.5 & 4.6)
            if target_outcome == RunState.COMPLETED:
                if session._captured:
                    # After capture, clean session exit safes first and then runs analysis
                    self._transition_to(
                        RunState.ANALYZING, "Session analyzing data"
                    )
                    raw_to_analyze = (
                        self._raw_data.copy()
                        if self._raw_data is not None
                        else pd.DataFrame()
                    )
                    try:
                        analyzed = self._analyze_data(raw_to_analyze, request)
                        self._data = (
                            analyzed.copy()
                            if analyzed is not None
                            else pd.DataFrame()
                        )
                    except BaseException as exc:
                        primary_error = exc
                        primary_error_tb = getattr(exc, "__traceback__", None)
                        primary_error_phase = "ANALYZING"
                        target_outcome = RunState.FAILED

                    if target_outcome == RunState.COMPLETED:
                        if request.save:
                            self._transition_to(
                                RunState.SAVING, "Publishing completed data"
                            )
                            try:
                                self._publication_outcome = target_outcome
                                self._filename = self._publish_data(
                                    self._data, request, is_partial=False
                                )
                                self._transition_to(
                                    RunState.COMPLETED,
                                    "Completed successfully",
                                )
                            except BaseException as exc:
                                primary_error = exc
                                primary_error_tb = getattr(
                                    exc, "__traceback__", None
                                )
                                primary_error_phase = "SAVING"
                                self._transition_to(
                                    RunState.FAILED, "Publication failed"
                                )
                                target_outcome = RunState.FAILED
                        else:
                            self._transition_to(
                                RunState.COMPLETED,
                                "Completed without saving",
                            )
                else:
                    # Configuration-only session has no analysis step
                    if self.run_state != RunState.COMPLETED:
                        self._transition_to(
                            RunState.COMPLETED,
                            "Configuration-only session completed",
                        )

            if target_outcome == RunState.ABORTED and self.run_state != RunState.ABORTED:
                self._data = (
                    self._raw_data.copy()
                    if self._raw_data is not None
                    else pd.DataFrame()
                )
                should_save_partial = (
                    request.save_partial
                    if request.save_partial is not None
                    else (
                        request.save
                        and self._data is not None
                        and not self._data.empty
                    )
                )
                if (
                    should_save_partial
                    and self._data is not None
                    and not self._data.empty
                ):
                    self._transition_to(
                        RunState.SAVING, "Publishing partial data"
                    )
                    try:
                        self._publication_outcome = target_outcome
                        self._partial_filename = self._publish_data(
                            self._data, request, is_partial=True
                        )
                        self._transition_to(
                            RunState.ABORTED,
                            "Aborted with partial data saved",
                        )
                    except BaseException as exc:
                        primary_error = exc
                        primary_error_tb = getattr(exc, "__traceback__", None)
                        primary_error_phase = "SAVING"
                        self._transition_to(
                            RunState.FAILED, "Partial save failed after abort"
                        )
                        target_outcome = RunState.FAILED
                else:
                    self._transition_to(
                        RunState.ABORTED, "Aborted without saving partial"
                    )

            if target_outcome == RunState.FAILED and self.run_state != RunState.FAILED:
                self._data = (
                    self._raw_data.copy()
                    if self._raw_data is not None
                    else pd.DataFrame()
                )
                should_save_partial = (
                    request.save_partial
                    if request.save_partial is not None
                    else False
                )
                if (
                    should_save_partial
                    and self._data is not None
                    and not self._data.empty
                ):
                    try:
                        if self.run_state in {
                            RunState.SAFING,
                            RunState.ANALYZING,
                        }:
                            self._transition_to(
                                RunState.SAVING,
                                "Publishing partial data on failure",
                            )
                            self._publication_outcome = target_outcome
                            self._partial_filename = self._publish_data(
                                self._data, request, is_partial=True
                            )
                    except BaseException as exc:
                        sec_errors.append(f"Partial save error: {exc}")
                if self.run_state in {
                    RunState.SAFING,
                    RunState.ANALYZING,
                    RunState.SAVING,
                }:
                    self._transition_to(RunState.FAILED, "Session failed")

            # Step 4: Finalize RunRecord and emit TerminalEvent
            end_time = time.time()
            if (
                primary_error_phase != "SAFING"
                and safety_report.status == SafetyStatus.UNSAFE
            ):
                err_msg = f"Shutdown error: {safety_report.error or safety_report.summary}"
                if err_msg not in sec_errors:
                    sec_errors.append(err_msg)

            record = RunRecord(
                run_id=token.run_id,
                generation=token.generation,
                start_time=start_time,
                end_time=end_time,
                state=self.run_state,
                safety=safety_report,
                save_requested=request.save,
                filename=self._filename,
                partial_filename=self._partial_filename,
                primary_error_phase=primary_error_phase,
                primary_error_type=(
                    type(primary_error).__name__
                    if primary_error is not None
                    else None
                ),
                primary_error_message=(
                    str(primary_error) if primary_error is not None else None
                ),
                secondary_errors=tuple(sec_errors),
                metadata={"recoverable_staging_paths": self.recoverable_staging_paths},
            )
            try:
                self._record_run(record)
            except Exception:
                pass
            try:
                self._emit_terminal_event(record, self._data)
            except Exception:
                pass

        finally:
            self._active_session = None
            self._active_owner_thread_id = None
            self._session_capture_count = 0

        # Step 5: Error handling per Section 5.3
        if primary_error is not None:
            if exc_val is not None and primary_error is exc_val:
                return False  # Let caller exception propagate
            if (
                primary_error_tb is not None
                and getattr(primary_error, "__traceback__", None)
                is not primary_error_tb
            ):
                raise primary_error.with_traceback(primary_error_tb)
            raise primary_error

        if safety_report.status == SafetyStatus.UNSAFE:
            raise HardwareSafetyError(
                f"Hardware safety could not be verified: {safety_report.error or safety_report.summary}",
                safety_report=safety_report,
            )

        return False

    # ========================================================================
    # Protected Subclass Hooks (Section 3.1 & 4.4)
    # ========================================================================

    def _validate_options(self, options: Optional[Mapping[str, Any]]) -> None:
        """
        Validates run options before reservation.

        Subclasses override to validate specific allowed option keys and values.
        """
        if options is not None and not isinstance(options, (dict, Mapping)):
            raise TypeError(
                f"options must be a Mapping or None, got {type(options).__name__}"
            )

    def _configure_instruments(self, request: RunRequest) -> None:
        """
        Protected hook to configure instruments with outputs disabled.

        Subclasses override with instrument configuration logic.
        """
        pass

    def _capture_data(
        self, request: RunRequest, on_update: Optional[Callable[[Any], None]]
    ) -> pd.DataFrame:
        """
        Protected hook to perform data acquisition loop.

        Subclasses override with acquisition logic.
        """
        return pd.DataFrame()

    def _safe_shutdown(self) -> Union[SafetyReport, Sequence[SafetyAction]]:
        """
        Protected hook to execute hardware shutdown actions.

        Subclasses override with setup-specific safe shutdown policy.
        """
        return SafetyReport(
            status=SafetyStatus.SAFE, summary="Default clean safe shutdown"
        )

    def _analyze_data(
        self, raw_data: pd.DataFrame, request: RunRequest
    ) -> pd.DataFrame:
        """
        Protected hook to perform scientific analysis on raw data.

        Subclasses override with scientific analysis logic.
        """
        return raw_data.copy()

    def _publish_data(
        self, data: pd.DataFrame, request: RunRequest, is_partial: bool = False
    ) -> Optional[str]:
        """
        Protected hook to publish completed or partial data artifact.

        Requires output_dir, measurement_schema and explicit column_units supplied
        to the constructor. raw_column_units can describe a different partial view.
        Side-artifact hooks stage files under the shared reserved basename.
        """
        from .persistence import (
            STANDARD_SCHEMAS, _prepare_metadata, create_staging_file,
            reserve_candidate_filename, publish_artifact_bundle,
            write_measurement_handle, write_partial_csv,
        )
        if self.output_dir is None or self.measurement_schema not in STANDARD_SCHEMAS:
            raise ValueError("Saving requires output_dir and a standard measurement_schema")
        units = self.raw_column_units if is_partial and self.raw_column_units is not None else self.column_units
        if units is None:
            raise ValueError("Saving requires explicit column_units")
        run_id = self._coordinator.active_token.run_id
        metadata = dict(self.measurement_metadata)
        metadata.update(
            measurement_schema=self.measurement_schema,
            measurement_schema_version=STANDARD_SCHEMAS[self.measurement_schema],
            run_id=run_id, outcome=self._publication_outcome.value,
            partial=is_partial, save_requested=request.save,
        )
        prepared = _prepare_metadata(metadata, data, units)
        self.recoverable_staging_paths = ()
        with reserve_candidate_filename(self.output_dir, self.measurement_schema, run_id) as reservation:
            if is_partial:
                try:
                    return str(write_partial_csv(
                        self.output_dir, reservation.candidate_basename, run_id, prepared, data,
                    ).resolve())
                except BaseException as exc:
                    self.recoverable_staging_paths = tuple(
                        str(path) for path in getattr(exc, "recoverable_staging_paths", ())
                    )
                    raise
            fd, staging = create_staging_file(self.output_dir, prefix=f".{run_id}-csv-")
            try:
                with io.open(fd, "w", encoding="utf-8", newline="") as handle:
                    write_measurement_handle(handle, prepared, data)
                sides = self._stage_side_artifacts(data, request, reservation)
                return str(publish_artifact_bundle(reservation, staging, sides).resolve())
            except BaseException as exc:
                paths = list(getattr(exc, "recoverable_staging_paths", ()))
                if staging.exists() and staging not in paths:
                    paths.append(staging)
                self.recoverable_staging_paths = tuple(str(path) for path in paths)
                exc.recoverable_staging_paths = self.recoverable_staging_paths
                raise

    def _stage_side_artifacts(self, data, request, reservation):
        """Return (staging, target) pairs using reservation.candidate_basename.

        Families producing plots override this hook. Keep raw data in memory;
        report any staging paths if staging itself fails.
        """
        return ()

    # ========================================================================
    # Internal Helpers
    # ========================================================================

    def _reserve(self, request: Optional[RunRequest] = None) -> ReservationToken:
        """Reserve a new run generation."""
        token = self._coordinator.reserve(request)
        with self._snapshot_lock:
            self._snapshot_sequence = 0
            self._latest_snapshot = None
        return token

    def _validate_token(self, token: ReservationToken) -> None:
        """Validate token before execution begins."""
        self._coordinator.validate_token(token)

    def _transition_to(
        self, next_state: RunState, reason: Optional[str] = None
    ) -> None:
        """Execute a legal forward transition."""
        self._coordinator.transition_to(next_state, reason)

    def _record_run(self, record: RunRecord) -> None:
        """Finalize and record a run."""
        self._coordinator.record_run(record)

    def _idle_command_lease(self):
        """Acquire idle command lease."""
        return self._coordinator.idle_command_lease()
