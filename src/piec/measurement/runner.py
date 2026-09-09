"""
MeasurementRunner: thread-safe background runner for PIEC measurements.

Fulfills Checkpoint 10b of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Synchronous reservation before worker launch (Section 4.2);
- Non-daemon background worker execution (Section 3.2 & 6.3);
- Worker thread-start failure recovery finalizing reservation as FAILED with NOT_NEEDED safety (Section 4.2);
- Cooperative stop and pause controls (Section 4.3);
- Close coordination preventing premature exit before worker death, terminal delivery,
  and confirmed hardware safety (Section 6.3);
- Strict separation of concerns: runner owns no science and performs no hardware I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd

from .base import BaseMeasurement
from .contracts import (
    ConcurrentRunError,
    ControlQueue,
    DisplayQueue,
    HardwareSafetyError,
    MeasurementLifecycleError,
    MeasurementSnapshot,
    ReservationToken,
    RunRecord,
    RunRequest,
    RunState,
    SafetyAlertEvent,
    SafetyReport,
    SafetyStatus,
    StateChangeEvent,
    TerminalEvent,
)


@dataclass(frozen=True)
class CloseCoordinationStatus:
    """
    Status report for application / window close coordination (Section 6.3).
    """

    is_closing: bool
    is_worker_alive: bool
    run_state: RunState
    safety_status: SafetyStatus
    can_close: bool
    reason: str
    elapsed_since_request: Optional[float] = None


class MeasurementRunner:
    """
    Thread-safe execution runner coordinating background worker threads, synchronous
    reservations, lifecycle events, and application close coordination (Section 3.2 & 6.3).

    The runner executes measurements in a dedicated non-daemon thread, ensuring
    the process does not terminate abruptly while hardware outputs are active.
    It owns no instrument I/O or scientific processing, delegating entirely to BaseMeasurement.
    """

    def __init__(
        self,
        measurement: BaseMeasurement,
        *,
        default_display_maxsize: int = 1,
    ) -> None:
        if not isinstance(measurement, BaseMeasurement):
            raise TypeError(
                f"MeasurementRunner requires a BaseMeasurement instance, got {type(measurement).__name__}"
            )
        self._measurement = measurement
        self._lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None
        self._active_token: Optional[ReservationToken] = None
        self._last_worker_exc: Optional[BaseException] = None
        self._is_closing = False
        self._close_requested_time: Optional[float] = None

        # Dedicated display and control queues for convenient GUI / consumer binding
        self._display_queue = self._measurement.create_display_queue(
            maxsize=default_display_maxsize
        )
        self._control_queue = self._measurement.create_control_queue()

    @property
    def measurement(self) -> BaseMeasurement:
        """The underlying BaseMeasurement instance."""
        return self._measurement

    @property
    def display_queue(self) -> DisplayQueue:
        """Bounded coalescing display queue for high-rate snapshot visualization."""
        return self._display_queue

    @property
    def control_queue(self) -> ControlQueue:
        """Unbounded FIFO control queue for lifecycle, safety, and terminal events."""
        return self._control_queue

    @property
    def run_state(self) -> RunState:
        """Current execution lifecycle state."""
        return self._measurement.run_state

    @property
    def safety_status(self) -> SafetyStatus:
        """Current verified hardware safety status."""
        return self._measurement.safety_status

    @property
    def is_active(self) -> bool:
        """Whether a run reservation or execution is currently active."""
        return self.run_state.is_active

    @property
    def is_worker_alive(self) -> bool:
        """Whether the background worker thread is currently running."""
        with self._lock:
            return self._worker_thread is not None and self._worker_thread.is_alive()

    @property
    def is_closing(self) -> bool:
        """Whether application/window close coordination has been requested."""
        with self._lock:
            return self._is_closing

    @property
    def active_token(self) -> Optional[ReservationToken]:
        """Active run reservation token, or None."""
        return self._measurement.active_token

    @property
    def last_run_record(self) -> Optional[RunRecord]:
        """RunRecord from the most recent run."""
        return self._measurement.last_run_record

    @property
    def run_records(self) -> Tuple[RunRecord, ...]:
        """Immutable history of all completed, aborted, or failed run records."""
        return self._measurement.run_records

    @property
    def last_error(self) -> Optional[BaseException]:
        """The unhandled exception from the worker thread, if any occurred."""
        with self._lock:
            return self._last_worker_exc

    def snapshot(self) -> MeasurementSnapshot:
        """Thread-safe query returning a mutation-isolated snapshot of current state."""
        return self._measurement.snapshot()

    def create_display_queue(self, maxsize: int = 1) -> DisplayQueue:
        """Creates and registers an additional DisplayQueue on the measurement."""
        return self._measurement.create_display_queue(maxsize=maxsize)

    def remove_display_queue(self, queue: DisplayQueue) -> None:
        """Unregisters a DisplayQueue."""
        self._measurement.remove_display_queue(queue)

    def create_control_queue(self) -> ControlQueue:
        """Creates and registers an additional ControlQueue on the measurement."""
        return self._measurement.create_control_queue()

    def remove_control_queue(self, queue: ControlQueue) -> None:
        """Unregisters a ControlQueue."""
        self._measurement.remove_control_queue(queue)

    def add_display_listener(
        self, listener: Callable[[MeasurementSnapshot], None]
    ) -> None:
        """Registers a callback for display snapshot updates."""
        self._measurement.add_display_listener(listener)

    def remove_display_listener(
        self, listener: Callable[[MeasurementSnapshot], None]
    ) -> None:
        """Unregisters a display snapshot callback."""
        self._measurement.remove_display_listener(listener)

    def add_control_listener(
        self,
        listener: Callable[
            [Union[StateChangeEvent, SafetyAlertEvent, TerminalEvent]], None
        ],
    ) -> None:
        """Registers a callback for lifecycle and safety control events."""
        self._measurement.add_control_listener(listener)

    def remove_control_listener(
        self,
        listener: Callable[
            [Union[StateChangeEvent, SafetyAlertEvent, TerminalEvent]], None
        ],
    ) -> None:
        """Unregisters a control event callback."""
        self._measurement.remove_control_listener(listener)

    # ========================================================================
    # Execution Lifecycle (Section 4.2 & 6.3)
    # ========================================================================

    def start(
        self,
        *,
        on_update: Optional[Callable[[Any], None]] = None,
        save: bool = True,
        save_partial: Optional[bool] = None,
        options: Optional[Mapping[str, Any]] = None,
    ) -> ReservationToken:
        """
        Reserves a new run synchronously and launches a non-daemon worker thread (Section 4.2).

        Steps under Section 4.2:
        1. Validates and freezes options into RunRequest.
        2. Reserves run generation synchronously under the state lock. Rejects nested
           or concurrent runs before launching a worker.
        3. Launches a non-daemon worker thread (`daemon=False`).
        4. If thread start fails, finalizes reservation as FAILED with safety NOT_NEEDED.

        Returns:
            ReservationToken bound to the new generation.

        Raises:
            ConcurrentRunError: If another run or idle command lease is active.
            MeasurementLifecycleError: If the measurement cannot be reserved.
            Exception: If thread creation fails (after cleanly finalizing reservation).
        """
        request = RunRequest(
            on_update=on_update,
            save=save,
            save_partial=save_partial,
            options=options,
        )

        with self._lock:
            if self._is_closing:
                raise ConcurrentRunError("Cannot start run while window/application is closing")

            # Step 1 & 2: Synchronous reservation on caller thread
            token = self._measurement._reserve(request)
            self._active_token = token
            self._last_worker_exc = None

            # Step 3: Create non-daemon worker thread
            worker = threading.Thread(
                target=self._worker_entry,
                args=(token, request),
                name=f"MeasurementWorker-{token.run_id[:8]}",
                daemon=False,
            )

            # Step 4: Launch worker thread with start failure handling
            try:
                worker.start()
                self._worker_thread = worker
                return token
            except BaseException as exc:
                # Thread start failed: finalize reservation as FAILED with safety NOT_NEEDED
                start_time = time.time()
                try:
                    self._measurement._transition_to(
                        RunState.FAILED, f"Worker thread start failed: {exc}"
                    )
                except Exception:
                    pass

                safety = SafetyReport(
                    status=SafetyStatus.NOT_NEEDED,
                    summary=f"Worker thread creation failed: {exc}",
                )
                self._measurement._coordinator.set_safety_status(safety.status)

                record = RunRecord(
                    run_id=token.run_id,
                    generation=token.generation,
                    start_time=start_time,
                    end_time=time.time(),
                    state=RunState.FAILED,
                    safety=safety,
                    save_requested=request.save,
                    primary_error_phase="STARTING",
                    primary_error_type=type(exc).__name__,
                    primary_error_message=str(exc) or repr(exc),
                )
                try:
                    self._measurement._record_run(record)
                    self._measurement._emit_terminal_event(record, None)
                except Exception:
                    pass

                raise exc

    def _worker_entry(
        self, token: ReservationToken, request: RunRequest
    ) -> None:
        """Internal entrypoint for the background non-daemon worker thread."""
        try:
            self._measurement.run_experiment(
                token=token,
                on_update=request.on_update,
                save=request.save,
                save_partial=request.save_partial,
                options=request.options,
            )
        except BaseException as exc:
            with self._lock:
                self._last_worker_exc = exc

    def request_stop(self) -> None:
        """
        Cooperative cross-thread Stop control (Section 4.3).
        Latches the stop event and transitions active states to STOPPING.
        """
        self._measurement.request_stop()

    def request_pause(self, paused: bool = True) -> None:
        """
        Cooperative cross-thread Pause control (Section 4.3).
        """
        self._measurement.request_pause(paused=paused)

    def join(self, timeout: Optional[float] = None) -> bool:
        """
        Waits for the worker thread to finish execution (synchronous / testing helper).

        Returns:
            True if worker terminated, False if timeout expired.
        """
        with self._lock:
            thread = self._worker_thread

        if thread is None:
            return True

        thread.join(timeout=timeout)
        return not thread.is_alive()

    # ========================================================================
    # Close Coordination (Section 6.3)
    # ========================================================================

    def request_close(self) -> None:
        """
        Initiates cooperative application / window close coordination (Section 6.3).

        - Sets closing flag.
        - Requests cooperative stop of any active run.
        - The caller should continue polling `can_close()` through non-blocking checks
          (e.g. Tk `after()` or Qt timer) rather than blocking on `join()`.
        """
        with self._lock:
            if not self._is_closing:
                self._is_closing = True
                self._close_requested_time = time.time()
        self.request_stop()

    def can_close(self) -> bool:
        """
        Checks whether it is safe to close the application / window (Section 6.3).

        Close is permitted ONLY when:
        1. The worker thread is completely terminated;
        2. Measurement lifecycle state is IDLE or terminal (COMPLETED, ABORTED, FAILED);
        3. Hardware safety is confirmed (SAFE or NOT_NEEDED).

        Never blocks.
        """
        status = self.check_close_status()
        return status.can_close

    def check_close_status(self) -> CloseCoordinationStatus:
        """
        Returns a comprehensive diagnostic report of close readiness (Section 6.3).
        """
        with self._lock:
            closing = self._is_closing
            worker_alive = (
                self._worker_thread is not None and self._worker_thread.is_alive()
            )
            req_time = self._close_requested_time

        elapsed = time.time() - req_time if req_time is not None else None
        state = self.run_state
        safety = self.safety_status

        if worker_alive:
            return CloseCoordinationStatus(
                is_closing=closing,
                is_worker_alive=True,
                run_state=state,
                safety_status=safety,
                can_close=False,
                reason="Worker thread is still executing",
                elapsed_since_request=elapsed,
            )

        if state.is_active:
            return CloseCoordinationStatus(
                is_closing=closing,
                is_worker_alive=False,
                run_state=state,
                safety_status=safety,
                can_close=False,
                reason=f"Measurement run state is still active ({state.value})",
                elapsed_since_request=elapsed,
            )

        if safety == SafetyStatus.UNSAFE:
            return CloseCoordinationStatus(
                is_closing=closing,
                is_worker_alive=False,
                run_state=state,
                safety_status=safety,
                can_close=False,
                reason="Hardware safety could not be verified (UNSAFE). Manual interlock action required.",
                elapsed_since_request=elapsed,
            )

        if safety == SafetyStatus.SAFING:
            return CloseCoordinationStatus(
                is_closing=closing,
                is_worker_alive=False,
                run_state=state,
                safety_status=safety,
                can_close=False,
                reason="Hardware shutdown actions are still in progress",
                elapsed_since_request=elapsed,
            )

        if safety in {SafetyStatus.SAFE, SafetyStatus.NOT_NEEDED}:
            return CloseCoordinationStatus(
                is_closing=closing,
                is_worker_alive=False,
                run_state=state,
                safety_status=safety,
                can_close=True,
                reason="Worker dead, terminal reached, and hardware safety confirmed",
                elapsed_since_request=elapsed,
            )

        # SafetyStatus.UNKNOWN: permitted only when clean idle without ever energizing
        if state == RunState.IDLE:
            return CloseCoordinationStatus(
                is_closing=closing,
                is_worker_alive=False,
                run_state=state,
                safety_status=safety,
                can_close=True,
                reason="Idle measurement; no hardware operations were attempted",
                elapsed_since_request=elapsed,
            )

        return CloseCoordinationStatus(
            is_closing=closing,
            is_worker_alive=False,
            run_state=state,
            safety_status=safety,
            can_close=False,
            reason="Safety status is UNKNOWN following an active run",
            elapsed_since_request=elapsed,
        )
