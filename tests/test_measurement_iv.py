"""
Unit and integration tests for standardized IVSweep measurement.

Fulfills Checkpoint 13 and Section 10.1 of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Target API and schema: schema 'iv_sweep', version 1;
- Plain lowercase columns: ['voltage', 'current'] with V/A metadata units;
- Inherits BaseMeasurement with shared lifecycle, runner, and session support;
- Zero instrument I/O in __init__;
- Option validation before reservation/I/O;
- Stop-before-start zero I/O with ABORTED state and NOT_NEEDED safety;
- Paced cancellable pre-ramp from 0.0 V to v_start;
- Cancellable dwell times and sweep reads;
- Preserves raw data on interruption and error;
- Fault injection at every configuration and acquisition step;
- Independent paced safing ramp to 0.0 V;
- Output disable guaranteed even if safing ramp fails;
- Execution with MeasurementRunner and queue event verification.
"""

from __future__ import annotations

import math
from pathlib import Path
import queue
import time
from unittest.mock import MagicMock, Mock, call

import numpy as np
import pandas as pd
import pytest

from piec.measurement.contracts import (
    ConcurrentRunError,
    HardwareSafetyError,
    RunState,
    SafetyStatus,
    TerminalEvent,
)
from piec.measurement.iv_sweep import IVSweep
from piec.measurement.persistence import read_measurement_csv
from piec.measurement.runner import MeasurementRunner


def create_mock_sourcemeter(resistance: float = 100.0) -> Mock:
    """Helper to create a mock sourcemeter simulating an ohmic load."""
    sm = Mock()
    sm.idn.return_value = "KEITHLEY INSTRUMENTS INC.,MODEL 2400,9999999,1.0"
    current_v = [0.0]

    def set_v(*args, **kwargs):
        if "voltage" in kwargs:
            v = kwargs["voltage"]
        elif len(args) == 2:
            v = args[1]
        elif len(args) == 1:
            v = args[0]
        else:
            v = 0.0
        current_v[0] = float(v)

    sm.set_source_voltage.side_effect = set_v
    sm.get_voltage.side_effect = lambda *args, **kwargs: current_v[0]
    sm.get_current.side_effect = lambda *args, **kwargs: current_v[0] / resistance
    return sm


class TestIVSweepConstructorAndValidation:
    """Test constructor parameter validation and zero I/O guarantee."""

    def test_constructor_zero_io(self):
        sm = create_mock_sourcemeter()
        iv = IVSweep(sm)
        # Constructor must not touch instrument at all
        assert sm.idn.call_count == 0
        assert sm.configure_voltage_source.call_count == 0
        assert sm.set_sense_mode.call_count == 0
        assert sm.output.call_count == 0
        assert sm.set_source_voltage.call_count == 0

    def test_constructor_parameter_validation(self):
        sm = create_mock_sourcemeter()

        with pytest.raises(ValueError, match="num_steps must be >= 1"):
            IVSweep(sm, num_steps=0)

        with pytest.raises(ValueError, match="current_compliance must be a positive finite number"):
            IVSweep(sm, current_compliance=-0.1)

        with pytest.raises(ValueError, match="current_compliance must be a positive finite number"):
            IVSweep(sm, current_compliance=float("nan"))

        with pytest.raises(ValueError, match="current_compliance must be a positive finite number"):
            IVSweep(sm, current_compliance=True)

        with pytest.raises(ValueError, match="dwell_time cannot be negative"):
            IVSweep(sm, dwell_time=-0.01)

        with pytest.raises(ValueError, match="sense_mode must be '2W' or '4W'"):
            IVSweep(sm, sense_mode="3W")

        with pytest.raises(ValueError, match="ramp_step must be positive"):
            IVSweep(sm, ramp_step=0.0)

        with pytest.raises(ValueError, match="ramp_delay cannot be negative"):
            IVSweep(sm, ramp_delay=-0.01)

    def test_options_validation_before_reservation(self):
        sm = create_mock_sourcemeter()
        iv = IVSweep(sm)

        # Invalid compliance_current option rejected before reservation/I/O
        with pytest.raises(ValueError, match="compliance_current must be a positive finite number"):
            iv.run_experiment(options={"compliance_current": -1.0})

        with pytest.raises(ValueError, match="compliance_current must be a positive finite number"):
            iv.run_experiment(options={"compliance_current": False})

        with pytest.raises(ValueError, match="Unknown option: bogus"):
            iv.run_experiment(options={"bogus": 123})

        assert sm.output.call_count == 0


class TestIVSweepLifecycleAndControls:
    """Test lifecycle states, Stop-before-start, cancellable ramps, and dwells."""

    def test_stop_before_start_zero_io(self):
        sm = create_mock_sourcemeter()
        iv = IVSweep(sm)

        # Pre-reserve generation, then latch stop before run starts
        token = iv._reserve()
        iv.request_stop()
        assert iv.run_state == RunState.STOPPING

        res = iv.run_experiment(token=token, save=False)

        assert iv.run_state == RunState.ABORTED
        assert iv.safety_status == SafetyStatus.NOT_NEEDED
        assert isinstance(res, pd.DataFrame)
        assert res.empty

        # Absolutely zero instrument I/O should have occurred
        assert sm.output.call_count == 0
        assert sm.configure_voltage_source.call_count == 0
        assert sm.set_source_voltage.call_count == 0

    def test_cancellable_pre_ramp(self):
        sm = create_mock_sourcemeter()
        # Set v_start to 2.0 V, ramp_step = 0.5 V
        iv = IVSweep(sm, v_start=2.0, v_stop=5.0, num_steps=4, ramp_step=0.5, ramp_delay=0.01)

        recorded_voltages = []

        def set_v(*args, **kwargs):
            v = kwargs.get("voltage", args[1] if len(args) == 2 else 0.0)
            recorded_voltages.append(float(v))
            # Stop mid pre-ramp after 1.0 V
            if float(v) >= 1.0:
                iv.request_stop()

        sm.set_source_voltage.side_effect = set_v

        res = iv.run_experiment(save=False)

        assert iv.run_state == RunState.ABORTED
        # Pre-ramp was stopped before completing sweep
        assert iv.safety_status == SafetyStatus.SAFE
        assert sm.output.call_args_list[-1] == call(channel=1, on=False)

    def test_cancellable_dwell_and_sweep(self):
        sm = create_mock_sourcemeter(resistance=10.0)
        iv = IVSweep(sm, v_start=0.0, v_stop=1.0, num_steps=10, dwell_time=0.1)

        step_counter = [0]

        def get_v(*args, **kwargs):
            step_counter[0] += 1
            if step_counter[0] == 3:
                iv.request_stop()
            return float(iv._current_voltage)

        sm.get_voltage.side_effect = get_v

        res = iv.run_experiment(save=False)

        assert iv.run_state == RunState.ABORTED
        assert iv.safety_status == SafetyStatus.SAFE
        # Raw data up to stop must be preserved
        assert len(res) >= 3
        assert list(res.columns) == ["voltage", "current"]
        assert iv.raw_data is not None
        assert len(iv.raw_data) == len(res)
        # Safing returned output to disabled
        assert sm.output.call_args_list[-1] == call(channel=1, on=False)


class TestIVSweepFaultInjection:
    """Test fault injection at each hardware and callback stage."""

    def test_fault_in_configure_voltage_source(self):
        sm = create_mock_sourcemeter()
        sm.configure_voltage_source.side_effect = RuntimeError("SMU comm error in config")
        iv = IVSweep(sm)

        with pytest.raises(RuntimeError, match="SMU comm error in config"):
            iv.run_experiment(save=False)

        assert iv.run_state == RunState.FAILED
        # Safing attempted: output must be disabled
        sm.output.assert_called_with(channel=1, on=False)

    def test_fault_in_set_sense_mode(self):
        sm = create_mock_sourcemeter()
        sm.set_sense_mode.side_effect = RuntimeError("Sense mode error")
        iv = IVSweep(sm)

        with pytest.raises(RuntimeError, match="Sense mode error"):
            iv.run_experiment(save=False)

        assert iv.run_state == RunState.FAILED
        sm.output.assert_called_with(channel=1, on=False)

    def test_fault_during_sweep_set_source_voltage(self):
        sm = create_mock_sourcemeter()
        call_count = [0]

        def set_v(*args, **kwargs):
            call_count[0] += 1
            # Fail on the 3rd voltage step during sweep
            if call_count[0] == 3:
                raise RuntimeError("Hardware trip during voltage step")

        sm.set_source_voltage.side_effect = set_v
        iv = IVSweep(sm, v_start=0.0, v_stop=1.0, num_steps=5, dwell_time=0.0)

        with pytest.raises(RuntimeError, match="Hardware trip during voltage step"):
            iv.run_experiment(save=False)

        assert iv.run_state == RunState.FAILED
        # Raw data up to failure is preserved
        assert iv.raw_data is not None
        # Safing attempted: output disabled
        sm.output.assert_called_with(channel=1, on=False)

    def test_fault_in_get_voltage(self):
        sm = create_mock_sourcemeter()
        read_count = [0]

        def get_v(*args, **kwargs):
            read_count[0] += 1
            if read_count[0] == 3:
                raise RuntimeError("Read timeout on voltage")
            return 0.5

        sm.get_voltage.side_effect = get_v
        iv = IVSweep(sm, v_start=0.0, v_stop=1.0, num_steps=5, dwell_time=0.0)

        with pytest.raises(RuntimeError, match="Read timeout on voltage"):
            iv.run_experiment(save=False)

        assert iv.run_state == RunState.FAILED
        # 2 successful points preserved
        assert iv.raw_data is not None
        assert len(iv.raw_data) == 2
        sm.output.assert_called_with(channel=1, on=False)

    def test_fault_in_get_current(self):
        sm = create_mock_sourcemeter()
        read_count = [0]

        def get_i(*args, **kwargs):
            read_count[0] += 1
            if read_count[0] == 2:
                raise RuntimeError("Read timeout on current")
            return 0.005

        sm.get_current.side_effect = get_i
        iv = IVSweep(sm, v_start=0.0, v_stop=1.0, num_steps=5, dwell_time=0.0)

        with pytest.raises(RuntimeError, match="Read timeout on current"):
            iv.run_experiment(save=False)

        assert iv.run_state == RunState.FAILED
        # 1 successful point preserved
        assert iv.raw_data is not None
        assert len(iv.raw_data) == 1
        sm.output.assert_called_with(channel=1, on=False)

    def test_fault_in_on_update_callback(self):
        sm = create_mock_sourcemeter()
        iv = IVSweep(sm, v_start=0.0, v_stop=1.0, num_steps=5, dwell_time=0.0)

        calls = [0]

        def bad_callback(snap):
            calls[0] += 1
            if calls[0] == 2:
                raise ValueError("UI subscriber failed")

        with pytest.raises(ValueError, match="UI subscriber failed"):
            iv.run_experiment(on_update=bad_callback, save=False)

        assert iv.run_state == RunState.FAILED
        # Callback error treated as acquisition failure, preserving raw data
        assert iv.raw_data is not None
        assert len(iv.raw_data) == 2
        sm.output.assert_called_with(channel=1, on=False)


class TestIVSweepSafingGuarantees:
    """Test independent safing pacing and guaranteed output disable attempt."""

    def test_output_disable_attempted_even_if_safing_ramp_fails(self):
        sm = create_mock_sourcemeter()
        iv = IVSweep(sm, v_start=0.0, v_stop=2.0, num_steps=3, dwell_time=0.0)

        # Make sourcemeter set_source_voltage raise during shutdown
        orig_set_v = sm.set_source_voltage.side_effect

        def set_v_with_shutdown_fault(*args, **kwargs):
            v = kwargs.get("voltage", args[1] if len(args) == 2 else 0.0)
            # If ramping down to 0.0 during safing, throw an error
            if iv.run_state == RunState.SAFING:
                raise RuntimeError("Communication lost during safing ramp")
            return orig_set_v(*args, **kwargs)

        sm.set_source_voltage.side_effect = set_v_with_shutdown_fault

        # Run experiment; should raise HardwareSafetyError because shutdown failed
        with pytest.raises(HardwareSafetyError):
            iv.run_experiment(save=False)

        # Output disable MUST still have been attempted!
        sm.output.assert_called_with(channel=1, on=False)
        assert iv.safety_status == SafetyStatus.UNSAFE

    def test_independent_safing_pacing(self):
        sm = create_mock_sourcemeter()
        # Set ramp_delay to 0.02 s
        iv = IVSweep(sm, v_start=0.0, v_stop=2.0, num_steps=3, ramp_step=0.5, ramp_delay=0.02)

        t_start = time.time()
        iv.run_experiment(save=False)
        elapsed = time.time() - t_start

        # Safing ramp from 2.0 V to 0.0 V with ramp_step 0.5 takes 4 steps * 0.02s = 0.08s
        assert elapsed >= 0.06
        assert sm.output.call_args_list[-1] == call(channel=1, on=False)


class TestIVSweepRunnerAndPersistence:
    """Test background execution via MeasurementRunner and atomic persistence."""

    def test_runner_execution_and_queues(self, tmp_path):
        sm = create_mock_sourcemeter(resistance=200.0)
        iv = IVSweep(
            sm,
            v_start=0.0,
            v_stop=1.0,
            num_steps=5,
            dwell_time=0.01,
            output_dir=tmp_path,
        )

        runner = MeasurementRunner(iv)
        token = runner.start(save=True)

        # Wait for worker thread to complete
        while runner.is_worker_alive:
            time.sleep(0.02)

        assert runner.run_state == RunState.COMPLETED
        assert runner.safety_status == SafetyStatus.SAFE
        assert iv.filename is not None
        assert Path(iv.filename).is_file()

        # Verify control queue received TerminalEvent
        term_event = None
        while True:
            try:
                ev = runner.control_queue.get_nowait()
                if isinstance(ev, TerminalEvent):
                    term_event = ev
                    break
            except queue.Empty:
                break

        assert term_event is not None
        assert term_event.state == RunState.COMPLETED
        assert term_event.safety.status == SafetyStatus.SAFE
        assert term_event.filename == iv.filename

        # Verify display queue received snapshots
        snap = None
        while True:
            try:
                snap = runner.display_queue.get_nowait()
            except queue.Empty:
                break
        assert snap is not None
        assert "raw" in snap.views
        assert list(snap.views["raw"].columns) == ["voltage", "current"]

        # Verify saved file contents
        meta, data, units = read_measurement_csv(iv.filename)
        assert meta["measurement_schema"] == "iv_sweep"
        assert meta["measurement_schema_version"] == 1
        assert list(data.columns) == ["voltage", "current"]
        assert units == {"voltage": "V", "current": "A"}
        assert len(data) == 5

    def test_partial_save_on_abort(self, tmp_path):
        sm = create_mock_sourcemeter()
        iv = IVSweep(
            sm,
            v_start=0.0,
            v_stop=5.0,
            num_steps=10,
            dwell_time=0.05,
            output_dir=tmp_path,
        )

        def stop_after_two_points(snapshot):
            if snapshot.completed_steps == 2:
                iv.request_stop()

        res = iv.run_experiment(save=True, save_partial=True, on_update=stop_after_two_points)

        assert iv.run_state == RunState.ABORTED
        assert iv.filename is None
        assert iv.partial_filename is not None
        assert Path(iv.partial_filename).is_file()
        assert iv.partial_filename.endswith(".partial.csv")

        meta, data, units = read_measurement_csv(iv.partial_filename)
        assert meta["partial"] is True
        assert meta["outcome"] == "ABORTED"
        assert list(data.columns) == ["voltage", "current"]
        assert len(data) >= 2
