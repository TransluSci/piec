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
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple, Union
import pandas as pd

from .contracts import (
    ConcurrentRunError,
    HardwareSafetyError,
    IllegalStateTransitionError,
    LifecycleCoordinator,
    ReservationToken,
    RunRecord,
    RunRequest,
    RunState,
    SafetyAction,
    SafetyReport,
    SafetyStatus,
    ShutdownAttemptRecorder,
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

    def configure_instruments(
        self, *, options: Optional[Mapping[str, Any]] = None
    ) -> None:
        """Configures instruments within the active session scope."""
        self._measurement._session_configure(options=options)

    def capture_data(
        self,
        *,
        on_update: Optional[Callable[[Any], None]] = None,
        options: Optional[Mapping[str, Any]] = None,
    ) -> pd.DataFrame:
        """Captures data within the active session scope (at most once)."""
        return self._measurement._session_capture(
            on_update=on_update, options=options
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

    def __init__(self) -> None:
        self._coordinator = LifecycleCoordinator()
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

    def snapshot(self) -> Mapping[str, Any]:
        """
        Public snapshot query wrapper (Section 6.1).

        Thread-safe read-only snapshot of current measurement state.
        """
        with self._coordinator._state_lock:
            return {
                "run_id": getattr(self._coordinator.active_token, "run_id", None),
                "generation": self._coordinator.generation,
                "state": self.run_state.value,
                "safety": self.safety_status.value,
            }

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
        """Emits exactly one terminal event to all registered listeners."""
        with self._coordinator._state_lock:
            listeners = list(self._event_listeners)

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
        )

        for listener in listeners:
            try:
                listener(event)
            except Exception:
                # Listener failures must never corrupt measurement lifecycle or mask errors
                pass

    # ========================================================================
    # Full-Run Execution Engine (Section 4.4 & 4.6)
    # ========================================================================

    def run_experiment(
        self,
        *,
        token: Optional[ReservationToken] = None,
        on_update: Optional[Callable[[Any], None]] = None,
        save: bool = True,
        save_partial: Optional[bool] = None,
        options: Optional[Mapping[str, Any]] = None,
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
        self._active_owner_thread_id = current_thread
        start_time = time.time()

        try:
            if token is None:
                token = self._reserve(request)

            # Reset active results for this run
            self._raw_data = None
            self._data = None
            self._filename = None
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
                # Token validation
                self._validate_token(token)

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

    def configure_instruments(
        self, *, options: Optional[Mapping[str, Any]] = None
    ) -> None:
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
            self._session_configure(options=options)
            return

        if (
            self._active_owner_thread_id is not None
            and self._active_owner_thread_id != current_thread
        ):
            raise ConcurrentRunError(
                "Cross-thread hardware-bearing calls are rejected while another thread owns execution"
            )

        # Standalone transient scope
        self._validate_options(options)
        request = RunRequest(save=False, save_partial=False, options=options)
        token = self._reserve(request)
        self._active_owner_thread_id = current_thread
        start_time = time.time()

        self._raw_data = None
        self._data = None
        self._filename = None
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
        options: Optional[Mapping[str, Any]] = None,
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
            return self._session_capture(on_update=on_update, options=options)

        if (
            self._active_owner_thread_id is not None
            and self._active_owner_thread_id != current_thread
        ):
            raise ConcurrentRunError(
                "Cross-thread hardware-bearing calls are rejected while another thread owns execution"
            )

        # Standalone transient scope
        self._validate_options(options)
        request = RunRequest(
            on_update=on_update,
            save=False,
            save_partial=False,
            options=options,
        )
        token = self._reserve(request)
        self._active_owner_thread_id = current_thread
        start_time = time.time()

        self._raw_data = None
        self._data = None
        self._filename = None
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

        Default implementation acts as an in-memory sink returning a virtual path.
        Checkpoints 11a-11c integrate real filesystem publication.
        """
        suffix = ".partial.csv" if is_partial else ".csv"
        return f"{self._coordinator.active_token.run_id}{suffix}"

    # ========================================================================
    # Internal Helpers
    # ========================================================================

    def _reserve(self, request: Optional[RunRequest] = None) -> ReservationToken:
        """Reserve a new run generation."""
        return self._coordinator.reserve(request)

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
