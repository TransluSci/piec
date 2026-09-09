"""
Tests for Checkpoint 10a: Bounded Snapshots and Display/Control Paths.

Verifies:
- Mutation isolation (Section 6.1): DataFrame views are defensively copied on construction
  and retrieval; snapshot immutability.
- Snapshot properties, dict-like protocol, and extra metadata (Section 6.1).
- Bounded coalescing DisplayQueue (Section 6.2): drop-oldest policy on saturation,
  tracking of dropped_count, non-blocking put().
- Unbounded non-droppable ControlQueue (Section 6.2): StateChangeEvent, SafetyAlertEvent,
  and TerminalEvent delivered in strict FIFO order without loss.
- Immediate SafetyAlertEvent emission on shutdown failure (Section 4.4 & 6.2).
- Authoritative final_snapshot ordering on TerminalEvent (Section 6.2).
- High-rate concurrent publisher / slow consumer saturation resilience.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional

import numpy as np
import pandas as pd
import pytest

from piec.measurement import (
    BaseMeasurement,
    ControlQueue,
    DisplayQueue,
    HardwareSafetyError,
    MeasurementSnapshot,
    RunState,
    SafetyAlertEvent,
    SafetyReport,
    SafetyStatus,
    StateChangeEvent,
    TerminalEvent,
)


class DummySnapMeasurement(BaseMeasurement):
    """Concrete measurement instrumented for snapshot testing."""

    def __init__(self, steps: int = 5, fail_safing: bool = False) -> None:
        super().__init__()
        self.steps = steps
        self.fail_safing = fail_safing
        self.captured_snapshots: List[MeasurementSnapshot] = []

    def _configure_instruments(self, request) -> None:
        pass

    def _capture_data(
        self, request, on_update: Optional[Callable[[Any], None]] = None
    ) -> pd.DataFrame:
        rows = []
        for i in range(self.steps):
            if self._coordinator.is_stop_requested:
                break
            rows.append({"step": i, "value": i * 10.0})
            df_curr = pd.DataFrame(rows)
            # Publish snapshot during capture
            snap = self.publish_snapshot(
                views={"raw_window": df_curr, "last_cycle": df_curr.tail(1)},
                message=f"Step {i + 1}/{self.steps}",
                completed_steps=i + 1,
                total_steps=self.steps,
                field_column="field_calibrated",
            )
            self.captured_snapshots.append(snap)
            if on_update:
                on_update(snap)
        return pd.DataFrame(rows)

    def _safe_shutdown(self) -> SafetyReport:
        if self.fail_safing:
            return SafetyReport(
                status=SafetyStatus.UNSAFE,
                error="Simulated hardware shutdown failure",
                summary="Coil current could not be zeroed",
            )
        return SafetyReport(status=SafetyStatus.SAFE, summary="Safe shutdown verified")

    def _analyze_data(self, raw_data: pd.DataFrame, request) -> pd.DataFrame:
        analyzed = raw_data.copy()
        if not analyzed.empty:
            analyzed["processed"] = analyzed["value"] * 2.0
        return analyzed


# ============================================================================
# 1. Mutation Isolation & Snapshot Immutability (Section 6.1)
# ============================================================================

class TestSnapshotMutationIsolation:
    """Verifies that MeasurementSnapshot provides strict mutation isolation."""

    def test_view_defensive_copying_on_construction(self):
        """Mutating the source DataFrame after snapshot creation does not alter snapshot views."""
        df_source = pd.DataFrame({"a": [1, 2, 3], "b": [10.0, 20.0, 30.0]})
        snap = MeasurementSnapshot(
            run_id="run-123",
            generation=1,
            sequence=1,
            state=RunState.RUNNING,
            views={"raw_window": df_source},
        )

        # Mutate the source DataFrame
        df_source.loc[0, "a"] = 999
        df_source["new_col"] = "corrupt"

        view = snap.get_view("raw_window")
        assert view is not None
        assert view.loc[0, "a"] == 1
        assert "new_col" not in view.columns

    def test_view_defensive_copying_on_retrieval(self):
        """Mutating a retrieved view does not mutate subsequent view retrievals."""
        df_source = pd.DataFrame({"time": [0.1, 0.2], "voltage": [1.5, 2.5]})
        snap = MeasurementSnapshot(
            run_id="run-123",
            generation=1,
            sequence=1,
            state=RunState.RUNNING,
            views={"raw_window": df_source, "last_cycle": df_source},
        )

        # Mutate through get_view()
        v1 = snap.get_view("raw_window")
        assert v1 is not None
        v1.loc[0, "voltage"] = -999.0
        v1["mutated"] = True

        v2 = snap.get_view("raw_window")
        assert v2 is not None
        assert v2.loc[0, "voltage"] == 1.5
        assert "mutated" not in v2.columns

        # Mutate through raw_window property
        v_prop = snap.raw_window
        assert v_prop is not None
        v_prop.loc[0, "voltage"] = 888.0

        assert snap.raw_window.loc[0, "voltage"] == 1.5

        # Mutate through dict-like lookup
        v_dict = snap["raw_window"]
        v_dict.loc[0, "voltage"] = 777.0

        assert snap["raw_window"].loc[0, "voltage"] == 1.5

        # Mutate through views property
        v_map = snap.views["raw_window"]
        v_map.loc[0, "voltage"] = 666.0

        assert snap.views["raw_window"].loc[0, "voltage"] == 1.5

    def test_snapshot_attribute_immutability(self):
        """Snapshot fields cannot be reassigned or deleted."""
        snap = MeasurementSnapshot(
            run_id="run-123",
            generation=1,
            sequence=1,
            state=RunState.RUNNING,
        )

        with pytest.raises(AttributeError, match="immutable"):
            snap.sequence = 999

        with pytest.raises(AttributeError, match="immutable"):
            snap.state = RunState.COMPLETED

        with pytest.raises(AttributeError, match="immutable"):
            del snap.sequence

    def test_snapshot_views_mapping_immutability(self):
        """Snapshot views mapping does not support item assignment or deletion."""
        snap = MeasurementSnapshot(
            run_id="run-123",
            generation=1,
            sequence=1,
            state=RunState.RUNNING,
            views={"raw": pd.DataFrame({"x": [1]})},
        )

        with pytest.raises(TypeError):
            snap.views["new_view"] = pd.DataFrame()

        with pytest.raises(TypeError):
            del snap.views["raw"]

    def test_to_dict_mutation_isolation(self):
        """DataFrames in to_dict() are copies and do not affect the snapshot."""
        snap = MeasurementSnapshot(
            run_id="run-123",
            generation=1,
            sequence=1,
            state=RunState.RUNNING,
            views={"raw": pd.DataFrame({"x": [10]})},
        )
        d = snap.to_dict()
        assert d["views"]["raw"].loc[0, "x"] == 10
        d["views"]["raw"].loc[0, "x"] = 9999

        assert snap.get_view("raw").loc[0, "x"] == 10


# ============================================================================
# 2. Snapshot Fields & Convenience Protocol (Section 6.1)
# ============================================================================

class TestSnapshotProtocol:
    """Verifies snapshot convenience properties and mapping interface."""

    def test_convenience_properties(self):
        df_raw = pd.DataFrame({"time": [1], "voltage": [2]})
        df_cycle = pd.DataFrame({"time": [2], "voltage": [4]})
        df_avg = pd.DataFrame({"time": [1.5], "voltage": [3]})

        snap = MeasurementSnapshot(
            run_id="test-run",
            generation=2,
            sequence=42,
            state=RunState.RUNNING,
            safety=SafetyStatus.SAFE,
            completed_steps=10,
            total_steps=20,
            message="Halfway done",
            views={
                "raw_window": df_raw,
                "last_cycle": df_cycle,
                "cycle_average": df_avg,
            },
            field_column="field_calibrated",
        )

        assert snap.run_id == "test-run"
        assert snap.generation == 2
        assert snap.sequence == 42
        assert snap.state == RunState.RUNNING
        assert snap.safety == SafetyStatus.SAFE
        assert snap.completed_steps == 10
        assert snap.total_steps == 20
        assert snap.message == "Halfway done"
        assert snap.status_message == "Halfway done"
        assert isinstance(snap.timestamp, float)
        assert snap.raw_window is not None and snap.raw_window.equals(df_raw)
        assert snap.raw is not None and snap.raw.equals(df_raw)
        assert snap.last_cycle is not None and snap.last_cycle.equals(df_cycle)
        assert snap.cycle_average is not None and snap.cycle_average.equals(df_avg)
        assert snap.field_column == "field_calibrated"

    def test_mapping_protocol(self):
        snap = MeasurementSnapshot(
            run_id="m-run",
            generation=3,
            sequence=5,
            state=RunState.CONFIGURING,
            views={"raw": pd.DataFrame({"a": [1]})},
            custom_attr="custom_value",
        )

        assert snap["run_id"] == "m-run"
        assert snap["generation"] == 3
        assert snap["sequence"] == 5
        assert snap["state"] == RunState.CONFIGURING.value
        assert snap["safety"] == SafetyStatus.UNKNOWN.value
        assert snap["raw"].loc[0, "a"] == 1
        assert snap["custom_attr"] == "custom_value"

        assert "run_id" in snap
        assert "generation" in snap
        assert "raw" in snap
        assert "custom_attr" in snap
        assert "nonexistent" not in snap

        assert snap.get("custom_attr") == "custom_value"
        assert snap.get("missing", "default") == "default"


# ============================================================================
# 3. Bounded DisplayQueue Coalescing & Saturation (Section 6.2)
# ============================================================================

class TestDisplayQueue:
    """Verifies bounded coalescing DisplayQueue behavior."""

    def test_display_queue_coalescing_drops_oldest(self):
        """DisplayQueue with maxsize=1 drops oldest snapshots and tracks dropped_count."""
        q = DisplayQueue(maxsize=1)
        assert q.maxsize == 1
        assert q.empty()
        assert q.dropped_count == 0

        # Push 3 snapshots
        s1 = MeasurementSnapshot("run-1", 1, 1, RunState.RUNNING)
        s2 = MeasurementSnapshot("run-1", 1, 2, RunState.RUNNING)
        s3 = MeasurementSnapshot("run-1", 1, 3, RunState.RUNNING)

        q.put(s1)
        assert q.qsize() == 1
        assert q.full()
        assert q.dropped_count == 0

        q.put(s2)  # Drops s1
        assert q.qsize() == 1
        assert q.dropped_count == 1

        q.put(s3)  # Drops s2
        assert q.qsize() == 1
        assert q.dropped_count == 2

        # Getting the snapshot returns s3
        retrieved = q.get(block=False)
        assert retrieved.sequence == 3
        assert q.empty()
        assert q.dropped_count == 2

    def test_display_queue_blocking_and_timeout(self):
        """DisplayQueue.get() blocks until snapshot arrives or timeout expires."""
        q = DisplayQueue(maxsize=2)

        # Empty timeout
        t0 = time.monotonic()
        with pytest.raises(queue.Empty):
            q.get(block=True, timeout=0.05)
        assert time.monotonic() - t0 >= 0.04

        # Background producer
        snap = MeasurementSnapshot("run-1", 1, 1, RunState.RUNNING)

        def producer():
            time.sleep(0.05)
            q.put(snap)

        t = threading.Thread(target=producer)
        t.start()

        got = q.get(block=True, timeout=1.0)
        t.join()
        assert got.sequence == 1

    def test_display_queue_rejects_non_snapshot(self):
        """DisplayQueue rejects non-MeasurementSnapshot items."""
        q = DisplayQueue()
        with pytest.raises(TypeError, match="MeasurementSnapshot"):
            q.put("not a snapshot")  # type: ignore

    def test_display_queue_invalid_maxsize(self):
        """DisplayQueue rejects maxsize <= 0."""
        with pytest.raises(ValueError):
            DisplayQueue(maxsize=0)
        with pytest.raises(ValueError):
            DisplayQueue(maxsize=-1)


# ============================================================================
# 4. Unbounded Non-Droppable ControlQueue (Section 6.2)
# ============================================================================

class TestControlQueue:
    """Verifies unbounded FIFO delivery of lifecycle and safety events."""

    def test_control_queue_fifo_delivery(self):
        cq = ControlQueue()
        assert cq.empty()

        e1 = StateChangeEvent("run-1", 1, RunState.STARTING, RunState.CONFIGURING)
        e2 = StateChangeEvent("run-1", 1, RunState.CONFIGURING, RunState.RUNNING)
        e3 = SafetyAlertEvent(
            "run-1",
            1,
            SafetyStatus.UNSAFE,
            SafetyReport(SafetyStatus.UNSAFE, summary="Error"),
        )
        e4 = TerminalEvent(
            "run-1",
            1,
            RunState.COMPLETED,
            SafetyReport(SafetyStatus.SAFE),
        )

        cq.put(e1)
        cq.put(e2)
        cq.put(e3)
        cq.put(e4)

        assert cq.qsize() == 4

        assert cq.get() == e1
        assert cq.get() == e2
        assert cq.get() == e3
        assert cq.get() == e4
        assert cq.empty()


# ============================================================================
# 5. BaseMeasurement Event Distribution & Terminal Ordering (Section 6.2)
# ============================================================================

class TestBaseMeasurementEventPaths:
    """Verifies BaseMeasurement snapshot and event dispatch integration."""

    def test_clean_run_event_ordering_and_final_snapshot(self):
        """During a clean run, ControlQueue receives full state transition sequence and TerminalEvent with final snapshot."""
        meas = DummySnapMeasurement(steps=3)
        ctrl_q = meas.create_control_queue()
        disp_q = meas.create_display_queue(maxsize=1)

        control_events: List[Any] = []
        meas.add_control_listener(lambda e: control_events.append(e))

        df = meas.run_experiment(save=False)
        assert len(df) == 3

        # Drain control queue
        queued_events: List[Any] = []
        while not ctrl_q.empty():
            queued_events.append(ctrl_q.get_nowait())

        # Verify listener received same events as queue
        assert queued_events == control_events

        # Check sequence of state transitions
        state_changes = [e for e in queued_events if isinstance(e, StateChangeEvent)]
        transitions = [(e.from_state, e.to_state) for e in state_changes]
        expected_transitions = [
            (RunState.IDLE, RunState.STARTING),
            (RunState.STARTING, RunState.CONFIGURING),
            (RunState.CONFIGURING, RunState.RUNNING),
            (RunState.RUNNING, RunState.SAFING),
            (RunState.SAFING, RunState.ANALYZING),
            (RunState.ANALYZING, RunState.COMPLETED),
        ]
        assert transitions == expected_transitions

        # Check terminal event
        term_events = [e for e in queued_events if isinstance(e, TerminalEvent)]
        assert len(term_events) == 1
        term = term_events[0]
        assert term.state == RunState.COMPLETED
        assert term.safety.status == SafetyStatus.SAFE
        assert term.final_snapshot is not None
        assert term.final_snapshot.state == RunState.COMPLETED
        assert term.final_snapshot.sequence == 3
        assert term.final_snapshot.completed_steps == 3

        # Display queue holds the final snapshot
        disp_snap = disp_q.get_nowait()
        assert disp_snap.state == RunState.COMPLETED
        assert disp_q.dropped_count >= 2  # 3 published + 1 terminal into maxsize=1

    def test_immediate_safety_alert_on_safing_failure(self):
        """Safing failure emits immediate SafetyAlertEvent to ControlQueue before HardwareSafetyError is raised."""
        meas = DummySnapMeasurement(steps=2, fail_safing=True)
        ctrl_q = meas.create_control_queue()

        with pytest.raises(HardwareSafetyError):
            meas.run_experiment(save=False)

        queued_events: List[Any] = []
        while not ctrl_q.empty():
            queued_events.append(ctrl_q.get_nowait())

        # SafetyAlertEvent must be emitted
        alerts = [e for e in queued_events if isinstance(e, SafetyAlertEvent)]
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.safety_status == SafetyStatus.UNSAFE
        assert "Simulated hardware shutdown failure" in alert.message

        # TerminalEvent must also follow
        term_events = [e for e in queued_events if isinstance(e, TerminalEvent)]
        assert len(term_events) == 1
        assert term_events[0].state == RunState.FAILED
        assert term_events[0].safety.status == SafetyStatus.UNSAFE

        # Alert must precede TerminalEvent
        alert_idx = queued_events.index(alert)
        term_idx = queued_events.index(term_events[0])
        assert alert_idx < term_idx

    def test_snapshot_query_at_any_point(self):
        """measurement.snapshot() returns isolated copy reflecting current state."""
        meas = DummySnapMeasurement(steps=1)
        s0 = meas.snapshot()
        assert s0.state == RunState.IDLE
        assert s0.sequence == 0

        meas.run_experiment(save=False)

        s_final = meas.snapshot()
        assert s_final.state == RunState.COMPLETED
        assert s_final.sequence == 1
        assert s_final.raw_window is not None
        assert len(s_final.raw_window) == 1

        # Mutating view from snapshot does not affect next query
        df = s_final.raw_window
        df.loc[0, "value"] = 999999.0
        assert meas.snapshot().raw_window.loc[0, "value"] == 0.0

    def test_queue_and_listener_registration(self):
        """Tests registration and removal of display/control queues and listeners."""
        meas = DummySnapMeasurement(steps=1)

        dq = meas.create_display_queue()
        assert dq in meas._display_queues
        meas.remove_display_queue(dq)
        assert dq not in meas._display_queues

        cq = meas.create_control_queue()
        assert cq in meas._control_queues
        meas.remove_control_queue(cq)
        assert cq not in meas._control_queues

        dl_called = []
        dl = lambda s: dl_called.append(s)
        meas.add_display_listener(dl)
        assert dl in meas._display_listeners
        meas.remove_display_listener(dl)
        assert dl not in meas._display_listeners

        cl_called = []
        cl = lambda e: cl_called.append(e)
        meas.add_control_listener(cl)
        assert cl in meas._control_listeners
        meas.remove_control_listener(cl)
        assert cl not in meas._control_listeners


# ============================================================================
# 6. High-Rate Concurrency & Queue Saturation Load Test
# ============================================================================

class TestHighRateSaturationConcurrency:
    """Stress tests high-rate snapshot publishing with a slow consumer."""

    def test_high_rate_publishing_does_not_block_worker_and_preserves_control(self):
        """A worker publishing 200 snapshots into a maxsize=1 display queue finishes instantly without blocking."""
        meas = DummySnapMeasurement(steps=1)
        disp_q = meas.create_display_queue(maxsize=1)
        ctrl_q = meas.create_control_queue()

        def high_rate_worker():
            for i in range(200):
                df = pd.DataFrame({"step": [i], "data": [i * 2.0]})
                meas.publish_snapshot(
                    views={"raw_window": df},
                    message=f"Point {i}",
                    completed_steps=i,
                )

        t = threading.Thread(target=high_rate_worker)
        t0 = time.monotonic()
        t.start()
        t.join(timeout=2.0)
        elapsed = time.monotonic() - t0

        # Must finish well within 2 seconds (typically < 0.1s)
        assert not t.is_alive()
        assert elapsed < 1.5

        # Display queue held at most 1 item and dropped ~199
        assert disp_q.qsize() == 1
        assert disp_q.dropped_count == 199

        latest = disp_q.get_nowait()
        assert latest.sequence == 200
        assert latest.completed_steps == 199
