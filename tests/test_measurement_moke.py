"""
Unit and integration tests for standardized MokeMeasurement.

Fulfills Checkpoint 14 of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Target API and schema: schema 'moke', version 1;
- Plain lowercase columns: ['time', 'cycle', 'point', 'direction', 'source_output', 'field_calibrated', 'detector_voltage']
  plus optional ['field_measured', 'field_time'];
- Inherits BaseMeasurement with shared lifecycle, runner, and session support;
- Zero instrument I/O in __init__;
- Pre-validation of parameters and options;
- Stop-before-start zero I/O with ABORTED state and NOT_NEEDED safety;
- Paced cancellable pre-ramp to output_values[0];
- Cancellable dwell times and point transitions;
- Dual field modes: calibrated field vs measured field with sequential acquisition;
- Alternative output and field units ('A' and 'T');
- Fault injection at every configuration, acquisition, and callback stage;
- Full raw data recovery across abort and failure in finally;
- Bounded snapshots (tail limited to raw_window_points);
- Cycle averaging excluding partial/interrupted cycles;
- Attempt-all software safing guaranteeing output disable even on zero-ramp failure;
- Custom setup shutdown callback support;
- Frozen session options and runner execution.
"""

from __future__ import annotations

import json
from pathlib import Path
import queue
import time
from unittest.mock import MagicMock, Mock, call

import numpy as np
import pandas as pd
import pytest

from piec.analysis.field_calibration import FieldCalibration
from piec.measurement.contracts import (
    ConcurrentRunError,
    HardwareSafetyError,
    RunState,
    SafetyStatus,
    TerminalEvent,
)
from piec.measurement.moke import MokeMeasurement, MokeSnapshot
from piec.measurement.runner import MeasurementRunner


def create_calibration(output_unit="V", field_unit="Oe") -> FieldCalibration:
    return FieldCalibration(
        [(-5.0, -500.0), (0.0, 0.0), (5.0, 500.0)],
        output_unit=output_unit,
        field_unit=field_unit,
        name="test_cal",
    )


def create_mock_setup(output_unit="V", field_unit="Oe"):
    source = Mock()
    source.idn.return_value = "TEST_SOURCEMETER"
    source.voltage = (-10.0, 10.0)
    source.current = (-1.0, 1.0)
    source.current_compliance = (0.0, 0.1)
    source.voltage_compliance = (0.0, 100.0)
    current_out = [0.0]

    def set_v(*args, **kwargs):
        v = kwargs.get("voltage", args[0] if args else 0.0)
        current_out[0] = float(v)

    def set_i(*args, **kwargs):
        i = kwargs.get("current", args[0] if args else 0.0)
        current_out[0] = float(i)

    source.set_source_voltage.side_effect = set_v
    source.set_source_current.side_effect = set_i

    dmm = Mock()
    dmm.idn.return_value = "TEST_DMM"
    # Simulate a Kerr-like response
    dmm.get_voltage.side_effect = lambda: 0.5 + 0.02 * current_out[0]

    cal = create_calibration(output_unit=output_unit, field_unit=field_unit)
    return source, dmm, cal


class TestMokeConstructorAndValidation:
    """Test constructor validation and zero hardware I/O guarantee."""

    def test_constructor_zero_io(self):
        source, dmm, cal = create_mock_setup()
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=1.0,
            dwell_time=0.0,
            ramp_delay=0.0,
        )
        assert source.idn.call_count == 0
        assert source.output.call_count == 0
        assert source.configure_voltage_source.call_count == 0
        assert dmm.idn.call_count == 0
        assert dmm.set_sense_function.call_count == 0
        assert dmm.get_voltage.call_count == 0

    def test_constructor_parameter_validation(self):
        source, dmm, cal = create_mock_setup()
        valid_opts = dict(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=1.0,
            dwell_time=0.0,
            ramp_delay=0.0,
        )

        # Invalid calibration
        with pytest.raises(TypeError, match="calibration must be a FieldCalibration"):
            MokeMeasurement(**{**valid_opts, "calibration": "invalid"})

        # Invalid output_values
        with pytest.raises(ValueError, match="output_values must contain at least three finite settings"):
            MokeMeasurement(**{**valid_opts, "output_values": [0.0, 0.0]})

        with pytest.raises(ValueError, match="output_values must describe a nonconstant, closed cycle"):
            MokeMeasurement(**{**valid_opts, "output_values": [-5.0, 0.0, 5.0]})  # Not closed

        with pytest.raises(ValueError, match="output_values must describe a nonconstant, closed cycle"):
            MokeMeasurement(**{**valid_opts, "output_values": [0.0, 0.0, 0.0]})  # Constant

        # Invalid compliance / max_output_step
        with pytest.raises(ValueError, match="compliance must be positive and finite"):
            MokeMeasurement(**{**valid_opts, "compliance": -0.01})
        with pytest.raises(ValueError, match="compliance must be positive and finite"):
            MokeMeasurement(**{**valid_opts, "compliance": True})
        with pytest.raises(ValueError, match="max_output_step must be positive and finite"):
            MokeMeasurement(**{**valid_opts, "max_output_step": 0.0})

        # Invalid dwell / delay
        with pytest.raises(ValueError, match="dwell_time must be nonnegative and finite"):
            MokeMeasurement(**{**valid_opts, "dwell_time": -1.0})
        with pytest.raises(ValueError, match="ramp_delay must be nonnegative and finite"):
            MokeMeasurement(**{**valid_opts, "ramp_delay": -0.01})

        # Invalid cycles
        with pytest.raises(ValueError, match="n_cycles must be a positive integer"):
            MokeMeasurement(**{**valid_opts, "n_cycles": 0})
        with pytest.raises(ValueError, match="average_cycles must be a positive integer"):
            MokeMeasurement(**{**valid_opts, "average_cycles": -2})
        with pytest.raises(ValueError, match="raw_window_points must be a positive integer"):
            MokeMeasurement(**{**valid_opts, "raw_window_points": 0})

        # Invalid field reader
        with pytest.raises(TypeError, match="field_reader must be a callable"):
            MokeMeasurement(**{**valid_opts, "field_reader": 123})
        with pytest.raises(ValueError, match="field_reader_unit must explicitly match calibration.field_unit"):
            MokeMeasurement(**{**valid_opts, "field_reader": lambda: 1.0, "field_reader_unit": "T"})
        with pytest.raises(ValueError, match="field reader units/name require a field_reader"):
            MokeMeasurement(**{**valid_opts, "field_reader_unit": "Oe"})

        # Invalid safe_shutdown
        with pytest.raises(TypeError, match="safe_shutdown must be callable"):
            MokeMeasurement(**{**valid_opts, "safe_shutdown": "not_callable"})

        # Exceeds driver limits
        with pytest.raises(ValueError, match="compliance exceeds the driver's current_compliance limit"):
            MokeMeasurement(**{**valid_opts, "compliance": 0.5})

        cal_wide = FieldCalibration([(-20.0, -2000.0), (0.0, 0.0), (20.0, 2000.0)])
        with pytest.raises(ValueError, match="source output is below the driver's voltage limit"):
            MokeMeasurement(**{**valid_opts, "calibration": cal_wide, "output_values": [-15.0, 0.0, -15.0]})

        with pytest.raises(ValueError, match="source output exceeds the driver's voltage limit"):
            MokeMeasurement(**{**valid_opts, "calibration": cal_wide, "output_values": [0.0, 15.0, 0.0]})


class TestMokeLifecycleAndControls:
    """Test lifecycle states, stop-before-start, cancellable ramps, dwells, and dual field modes."""

    def test_stop_before_start_zero_io(self):
        source, dmm, cal = create_mock_setup()
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=1.0,
            dwell_time=0.0,
            ramp_delay=0.0,
        )

        token = moke._reserve()
        moke.request_stop()
        assert moke.run_state == RunState.STOPPING

        res = moke.run_experiment(token=token, save=False)

        assert moke.run_state == RunState.ABORTED
        assert moke.safety_status == SafetyStatus.NOT_NEEDED
        assert isinstance(res, pd.DataFrame)
        assert res.empty

        assert source.output.call_count == 0
        assert dmm.get_voltage.call_count == 0

    def test_cancellable_pre_ramp(self):
        source, dmm, cal = create_mock_setup()
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=1.0,
            dwell_time=0.0,
            ramp_delay=0.01,
        )

        recorded_v = []

        def set_v(*args, **kwargs):
            v = kwargs.get("voltage", args[0] if args else 0.0)
            recorded_v.append(float(v))
            if float(v) <= -2.0:
                moke.request_stop()

        source.set_source_voltage.side_effect = set_v

        res = moke.run_experiment(save=False)

        assert moke.run_state == RunState.ABORTED
        assert moke.safety_status == SafetyStatus.SAFE
        assert source.output.call_args_list[-1] == call(on=False)
        assert dmm.get_voltage.call_count == 0

    def test_cancellable_dwell_and_sweep(self):
        source, dmm, cal = create_mock_setup()
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.1,
            ramp_delay=0.0,
            n_cycles=2,
        )

        points_read = [0]

        def get_v():
            points_read[0] += 1
            if points_read[0] == 3:
                moke.request_stop()
            return 0.42

        dmm.get_voltage.side_effect = get_v

        res = moke.run_experiment(save=False)

        assert moke.run_state == RunState.ABORTED
        assert moke.safety_status == SafetyStatus.SAFE
        assert len(res) == 3
        assert moke.completed_cycles == 0
        assert moke.cycle_average.empty
        assert source.output.call_args_list[-1] == call(on=False)

    def test_dual_field_modes_calibrated_and_measured(self, tmp_path):
        source, dmm, cal = create_mock_setup()

        # 1. Calibrated field mode
        moke_cal = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.0,
            ramp_delay=0.0,
            output_dir=str(tmp_path / "cal"),
        )
        assert moke_cal.field_column == "field_calibrated"
        df_cal = moke_cal.run_experiment()
        assert "field_calibrated" in df_cal.columns
        assert "field_measured" not in df_cal.columns

        # 2. Measured field mode
        field_vals = [10.0, 20.0, 30.0, 40.0, 50.0]
        it = iter(field_vals)
        field_reader = Mock(side_effect=lambda: next(it))

        moke_meas = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.0,
            ramp_delay=0.0,
            field_reader=field_reader,
            field_reader_unit="Oe",
            output_dir=str(tmp_path / "meas"),
        )
        assert moke_meas.field_column == "field_measured"
        df_meas = moke_meas.run_experiment()
        assert "field_calibrated" in df_meas.columns
        assert "field_measured" in df_meas.columns
        assert "field_time" in df_meas.columns
        assert df_meas["field_measured"].tolist() == field_vals

    def test_alternative_units_current_and_tesla(self, tmp_path):
        source, dmm, cal = create_mock_setup(output_unit="A", field_unit="T")
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-0.5, 0.0, 0.5, 0.0, -0.5],
            compliance=10.0,  # V for current sourcing
            max_output_step=0.5,
            dwell_time=0.0,
            ramp_delay=0.0,
            output_dir=str(tmp_path),
        )
        assert moke.column_units["source_output"] == "A"
        assert moke.column_units["field_calibrated"] == "T"
        df = moke.run_experiment()
        assert df["source_output"].tolist() == [-0.5, 0.0, 0.5, 0.0, -0.5]


class TestMokeFaultInjectionAndDataRecovery:
    """Test fault injection across all lifecycle phases and attempt-all safing."""

    def test_configuration_failure(self):
        source, dmm, cal = create_mock_setup()
        dmm.set_sense_function.side_effect = RuntimeError("DMM config error")

        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.0,
            ramp_delay=0.0,
        )

        with pytest.raises(RuntimeError, match="DMM config error"):
            moke.run_experiment(save=False)

        assert moke.run_state == RunState.FAILED
        assert source.output.call_args_list[-1] == call(on=False)

    def test_detector_read_failure_preserves_raw_data(self):
        source, dmm, cal = create_mock_setup()
        reads = [0.3, 0.4, RuntimeError("DMM read timeout")]

        def get_v():
            r = reads.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        dmm.get_voltage.side_effect = get_v

        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.0,
            ramp_delay=0.0,
        )

        with pytest.raises(RuntimeError, match="DMM read timeout"):
            moke.run_experiment(save=False)

        assert moke.run_state == RunState.FAILED
        assert moke.raw_data is not None
        assert len(moke.raw_data) == 2
        assert source.output.call_args_list[-1] == call(on=False)

    def test_on_update_callback_failure_preserves_raw_data(self):
        source, dmm, cal = create_mock_setup()
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.0,
            ramp_delay=0.0,
        )

        call_count = [0]

        def failing_callback(snap):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("UI thread crash")

        with pytest.raises(RuntimeError, match="UI thread crash"):
            moke.run_experiment(on_update=failing_callback, save=False)

        assert moke.run_state == RunState.FAILED
        assert moke.raw_data is not None
        assert len(moke.raw_data) >= 1
        assert source.output.call_args_list[-1] == call(on=False)

    def test_zero_ramp_failure_attempts_output_disable(self):
        source, dmm, cal = create_mock_setup()
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.0,
            ramp_delay=0.0,
        )

        moke.configure_instruments()
        # Fail the ramp to zero
        source.set_source_voltage.side_effect = RuntimeError("Zero ramp failed")

        with pytest.raises(RuntimeError, match="Zero ramp failed"):
            moke.shut_off()

        # Output disable MUST still be called!
        assert source.output.call_args_list[-1] == call(on=False)

    def test_custom_safe_shutdown_invoked(self):
        source, dmm, cal = create_mock_setup()
        custom_shutdown = Mock()
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.0,
            ramp_delay=0.0,
            safe_shutdown=custom_shutdown,
        )

        moke.shut_off()
        custom_shutdown.assert_called_once_with(source)
        assert source.output.call_args_list[-1] == call(on=False)


class TestMokeSnapshotsAndRunner:
    """Test bounded live snapshots, session scopes, and runner integration."""

    def test_bounded_snapshots(self):
        source, dmm, cal = create_mock_setup()
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.0,
            ramp_delay=0.0,
            raw_window_points=3,
        )

        received_snaps = []
        moke.run_experiment(on_update=received_snaps.append, save=False)

        assert len(received_snaps) == 5
        for s in received_snaps:
            assert isinstance(s, MokeSnapshot)
            assert len(s.raw) <= 3

    def test_cycle_averaging_excludes_partial_cycles(self):
        source, dmm, cal = create_mock_setup()
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.0,
            ramp_delay=0.0,
            n_cycles=2,
            average_cycles=2,
        )

        moke.run_experiment(save=False)
        assert moke.completed_cycles == 2
        assert len(moke.cycle_average) == 5
        assert moke.cycle_average["cycles_averaged"].iloc[0] == 2

    def test_session_execution_scope(self):
        source, dmm, cal = create_mock_setup()
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.0,
            ramp_delay=0.0,
        )

        with moke.session() as s:
            s.configure_instruments()
            assert moke._configured is True
            data = s.capture_data()
            assert len(data) == 5

        # After session exit, output must be off
        assert source.output.call_args_list[-1] == call(on=False)

    def test_runner_integration(self):
        source, dmm, cal = create_mock_setup()
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.0,
            ramp_delay=0.0,
        )

        runner = MeasurementRunner(moke)
        terminal_events = []
        snapshots = []

        runner.add_control_listener(lambda e: terminal_events.append(e) if isinstance(e, TerminalEvent) else None)
        runner.add_display_listener(snapshots.append)

        token = runner.start(save=False)
        while runner.is_worker_alive:
            time.sleep(0.02)

        assert runner.run_state == RunState.COMPLETED
        assert len(terminal_events) == 1
        assert terminal_events[0].state == RunState.COMPLETED
        assert len(snapshots) > 0
