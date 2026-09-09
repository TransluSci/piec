"""
BaseMeasurement class implementing standardized lifecycle contracts and full-run engine.

Fulfills Checkpoint 8 and 9a of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Public execution wrapper run_experiment() enforcing canonical ordering (Section 3.1 & 4.4);
- Stop-before-start zero-I/O aborts with safety NOT_NEEDED (Section 4.2 & 4.4);
- Safing guarantee and error precedence handling (Section 5.1 & 5.3);
- Outcome and persistence matrix compliance (Section 4.6);
- Single RunRecord and TerminalEvent per reservation (Section 4.4 & 6.2);
- Protected subclass hooks for configuration, acquisition, safing, analysis, and publication.
"""

from __future__ import annotations

import time
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple, Union
import pandas as pd

from .contracts import (
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
    TerminalEvent,
)


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
        self._validate_options(options)
        request = RunRequest(
            on_update=on_update,
            save=save,
            save_partial=save_partial,
            options=options,
        )

        start_time = time.time()
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
                self._transition_to(RunState.STOPPING, "Stop requested before I/O")
            self._transition_to(RunState.ABORTED, "Aborted before I/O began")
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
        primary_error_phase: Optional[str] = None
        configured_ok = False
        safety_report: Optional[SafetyReport] = None

        try:
            # Token validation
            self._validate_token(token)

            # Step 3: Configure instruments
            self._transition_to(RunState.CONFIGURING, "Configuring instruments")
            try:
                self._configure_instruments(request)
                configured_ok = True
            except BaseException as exc:
                primary_error = exc
                primary_error_phase = "CONFIGURING"

            # Step 4 & 5: Capture data
            if configured_ok:
                if self._coordinator.is_stop_requested:
                    if self.run_state != RunState.STOPPING:
                        self._transition_to(
                            RunState.STOPPING, "Stop requested before acquisition"
                        )
                else:
                    self._transition_to(RunState.RUNNING, "Starting acquisition")
                    try:
                        raw = self._capture_data(request, on_update=on_update)
                        self._raw_data = (
                            raw.copy() if raw is not None else pd.DataFrame()
                        )
                    except BaseException as exc:
                        primary_error = exc
                        primary_error_phase = "RUNNING"

                    if (
                        self._coordinator.is_stop_requested
                        and self.run_state == RunState.RUNNING
                    ):
                        self._transition_to(
                            RunState.STOPPING, "Stop requested during acquisition"
                        )

        finally:
            # Step 6 & 7: Safing
            if self.run_state.is_active and self.run_state != RunState.STARTING:
                if self.run_state != RunState.SAFING:
                    try:
                        self._transition_to(RunState.SAFING, "Performing safe shutdown")
                    except IllegalStateTransitionError:
                        pass

                try:
                    raw_safety = self._safe_shutdown()
                    if isinstance(raw_safety, SafetyReport):
                        safety_report = raw_safety
                    elif isinstance(raw_safety, (list, tuple)):
                        all_ok = all(
                            getattr(a, "succeeded", False) for a in raw_safety
                        )
                        st = SafetyStatus.SAFE if all_ok else SafetyStatus.UNSAFE
                        safety_report = SafetyReport(
                            status=st,
                            actions=tuple(raw_safety),
                            summary=(
                                "Safe shutdown completed"
                                if all_ok
                                else "One or more shutdown actions failed"
                            ),
                        )
                    else:
                        safety_report = SafetyReport(
                            status=SafetyStatus.SAFE, summary="Default clean shutdown"
                        )
                except BaseException as exc:
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        if primary_error is None:
                            primary_error = exc
                            primary_error_phase = "SAFING"

                    action = SafetyAction(
                        name="safe_shutdown",
                        attempted=True,
                        succeeded=False,
                        error=str(exc),
                    )
                    safety_report = SafetyReport(
                        status=SafetyStatus.UNSAFE,
                        actions=(action,),
                        error=str(exc),
                        summary=f"Shutdown failed: {exc}",
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
                self._data = analyzed.copy() if analyzed is not None else pd.DataFrame()
            except BaseException as exc:
                primary_error = exc
                primary_error_phase = "ANALYZING"
                target_outcome = RunState.FAILED

            # Step 9: Save
            if target_outcome == RunState.COMPLETED:
                if request.save:
                    self._transition_to(RunState.SAVING, "Publishing completed data")
                    try:
                        self._filename = self._publish_data(
                            self._data, request, is_partial=False
                        )
                        self._transition_to(
                            RunState.COMPLETED, "Completed successfully"
                        )
                    except BaseException as exc:
                        primary_error = exc
                        primary_error_phase = "SAVING"
                        self._transition_to(RunState.FAILED, "Publication failed")
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
            if should_save_partial and self._data is not None and not self._data.empty:
                self._transition_to(RunState.SAVING, "Publishing partial data")
                try:
                    self._partial_filename = self._publish_data(
                        self._data, request, is_partial=True
                    )
                    self._transition_to(
                        RunState.ABORTED, "Aborted with partial data saved"
                    )
                except BaseException as exc:
                    primary_error = exc
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
                request.save_partial if request.save_partial is not None else False
            )
            if should_save_partial and self._data is not None and not self._data.empty:
                try:
                    if self.run_state in {RunState.SAFING, RunState.ANALYZING}:
                        self._transition_to(
                            RunState.SAVING, "Publishing partial data on failure"
                        )
                        self._partial_filename = self._publish_data(
                            self._data, request, is_partial=True
                        )
                except Exception:
                    pass

            if self.run_state in {RunState.SAFING, RunState.ANALYZING, RunState.SAVING}:
                self._transition_to(RunState.FAILED, "Run failed")

        # Step 11: Finalize record and emit event
        end_time = time.time()
        sec_errors = []
        if (
            primary_error_phase != "SAFING"
            and safety_report.status == SafetyStatus.UNSAFE
        ):
            sec_errors.append(
                f"Shutdown error: {safety_report.error or safety_report.summary}"
            )

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
                type(primary_error).__name__ if primary_error is not None else None
            ),
            primary_error_message=(
                str(primary_error) if primary_error is not None else None
            ),
            secondary_errors=tuple(sec_errors),
            snapshot_count=0,
        )
        self._record_run(record)
        self._emit_terminal_event(record, self._data)

        # Step 12: Re-raise error or return data
        if primary_error is not None:
            raise primary_error
        if safety_report.status == SafetyStatus.UNSAFE:
            raise HardwareSafetyError(
                f"Hardware safety could not be verified: {safety_report.error or safety_report.summary}",
                safety_report=safety_report,
            )

        return self._data

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
