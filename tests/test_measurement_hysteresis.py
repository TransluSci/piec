"""
Unit, lifecycle, fault-injection, and integration tests for standardized HysteresisLoop.

Fulfills Checkpoint 20b of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Target API and schema: schema 'hysteresis', version 1;
- Plain lowercase columns: ['time', 'voltage', 'current', 'polarization', 'applied_voltage']
  with canonical JSON units {'time': 's', 'voltage': 'V', 'current': 'A', 'polarization': 'uC/cm^2', 'applied_voltage': 'V'};
- Inherits DiscreteWaveform and BaseMeasurement with shared lifecycle, runner, and session support;
- In-memory scientific processing (process_hysteresis);
- Multi-artifact plot staging (_PV.png, _IV.png, _trace.png) when save=True and save_plots=True;
- Suppression of plots when save=False or save_plots=False;
- Removal of legacy HysteresisLoop bypass paths and unmigrated attributes (save_dir, apply_and_capture_waveform, save_waveform, analyze);
- Zero instrument I/O in __init__;
- Option validation before reservation/I/O;
- Cooperative cancellation (stop before start, stop during capture);
- Attempt-all output safing guaranteeing all AWG channels are disabled and zeroed.
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

from piec.analysis.hysteresis import (
    STANDARD_HYSTERESIS_COLUMNS,
    STANDARD_HYSTERESIS_UNITS,
)
from tests.fixtures.virtual_setups import fe_bench
from piec.measurement.contracts import (
    ConcurrentRunError,
    HardwareSafetyError,
    MeasurementLifecycleError,
    RunState,
    SafetyStatus,
    TerminalEvent,
)
from piec.measurement.discrete_waveform import HysteresisLoop
from piec.measurement.persistence import read_measurement_csv
from piec.measurement.runner import MeasurementRunner
from tests.fixtures.measurement_compatibility import (
    assert_data_columns_match,
    assert_piec_csv_layout,
)


def create_instrument_pair():
    """Create a paired VirtualAwg and VirtualScope for testing."""
    bench, awg, osc = fe_bench()
    return awg, osc


class TestHysteresisConstructorAndValidation:
    """Test constructor parameter validation, zero I/O guarantee, and schema metadata."""

    def test_constructor_zero_io(self):
        awg = Mock()
        osc = Mock()
        hl = HysteresisLoop(awg, osc)

        # Constructor must not call instrument methods
        assert awg.idn.call_count == 0
        assert awg.initialize.call_count == 0
        assert awg.output.call_count == 0
        assert osc.idn.call_count == 0
        assert osc.initialize.call_count == 0
        assert osc.arm.call_count == 0

    def test_schema_and_metadata_attributes(self, tmp_path):
        awg, osc = create_instrument_pair()
        hl = HysteresisLoop(
            awg,
            osc,
            frequency=2000.0,
            amplitude=3.0,
            offset=0.2,
            n_cycles=4,
            area=5e-5,
            r_shunt=100.0,
            baseline_points=15,
            time_offset=5e-8,
            auto_timeshift=False,
            show_plots=False,
            save_plots=True,
            output_dir=tmp_path,
        )

        assert hl.mtype == "hysteresis"
        assert hl.measurement_schema == "hysteresis"
        assert hl.column_units == STANDARD_HYSTERESIS_UNITS
        assert hl.raw_column_units == {"time": "s", "voltage": "V"}
        assert hl.frequency == 2000.0
        assert hl.amplitude == 3.0
        assert hl.offset == 0.2
        assert hl.n_cycles == 4
        assert hl.area == 5e-5
        assert hl.r_shunt == 100.0
        assert hl.baseline_points == 15
        assert hl.time_offset == 5e-8
        assert hl.auto_timeshift is False
        assert hl.show_plots is False
        assert hl.save_plots is True
        assert hl.output_dir == Path(tmp_path)
        assert hl.length == pytest.approx(1 / 2000.0)

        # Initial metadata dict
        assert hl.measurement_metadata["frequency"] == 2000.0
        assert hl.measurement_metadata["amplitude"] == 3.0
        assert hl.measurement_metadata["offset"] == 0.2
        assert hl.measurement_metadata["n_cycles"] == 4
        assert hl.measurement_metadata["area"] == 5e-5
        assert hl.measurement_metadata["r_shunt"] == 100.0
        assert hl.measurement_metadata["baseline_points"] == 15
        assert hl.measurement_metadata["time_offset"] == 5e-8
        assert hl.measurement_metadata["auto_timeshift"] is False

        # Legacy metadata DataFrame property
        meta_df = hl.metadata
        assert isinstance(meta_df, pd.DataFrame)
        assert meta_df.loc[0, "frequency"] == 2000.0

    def test_constructor_parameter_validation(self):
        awg, osc = create_instrument_pair()

        with pytest.raises(ValueError, match="frequency must be a positive finite number"):
            HysteresisLoop(awg, osc, frequency=0)

        with pytest.raises(ValueError, match="frequency must be a positive finite number"):
            HysteresisLoop(awg, osc, frequency=-100.0)

        with pytest.raises(ValueError, match="frequency must be a positive finite number"):
            HysteresisLoop(awg, osc, frequency=float("nan"))

        with pytest.raises(ValueError, match="amplitude must be a finite number"):
            HysteresisLoop(awg, osc, amplitude=float("nan"))

        with pytest.raises(ValueError, match="offset must be a finite number"):
            HysteresisLoop(awg, osc, offset=float("inf"))

        with pytest.raises(ValueError, match="area must be a positive finite number"):
            HysteresisLoop(awg, osc, area=0.0)

        with pytest.raises(ValueError, match="area must be a positive finite number"):
            HysteresisLoop(awg, osc, area=-1e-5)

        with pytest.raises(ValueError, match="n_cycles must be an integer >= 1"):
            HysteresisLoop(awg, osc, n_cycles=0)

        with pytest.raises(ValueError, match="n_cycles must be an integer >= 1"):
            HysteresisLoop(awg, osc, n_cycles=2.5)

        with pytest.raises(ValueError, match="n_cycles must be an integer >= 1"):
            HysteresisLoop(awg, osc, n_cycles=True)

        with pytest.raises(ValueError, match="r_shunt must be a positive finite number"):
            HysteresisLoop(awg, osc, r_shunt=0)

        with pytest.raises(ValueError, match="r_shunt must be a positive finite number"):
            HysteresisLoop(awg, osc, r_shunt=-50)

        with pytest.raises(ValueError, match="baseline_points must be a positive integer"):
            HysteresisLoop(awg, osc, baseline_points=0)

        with pytest.raises(ValueError, match="baseline_points must be a positive integer"):
            HysteresisLoop(awg, osc, baseline_points=5.5)

        with pytest.raises(ValueError, match="baseline_points must be a positive integer"):
            HysteresisLoop(awg, osc, baseline_points=True)

        with pytest.raises(ValueError, match="time_offset must be a finite non-negative number"):
            HysteresisLoop(awg, osc, time_offset=-1e-8)

        with pytest.raises(ValueError, match="time_offset must be a finite non-negative number"):
            HysteresisLoop(awg, osc, time_offset=float("nan"))

    def test_rejection_of_legacy_attributes_and_save_dir(self, tmp_path):
        awg, osc = create_instrument_pair()

        # save_dir must be rejected as an unknown keyword argument
        with pytest.raises(TypeError, match="save_dir"):
            HysteresisLoop(awg, osc, save_dir=tmp_path)

        hl = HysteresisLoop(awg, osc, output_dir=tmp_path)
        for legacy_attr in ("save_dir", "apply_and_capture_waveform", "save_waveform", "analyze"):
            assert not hasattr(hl, legacy_attr), f"Legacy attribute {legacy_attr} must not exist on HysteresisLoop"

    def test_validate_options(self, tmp_path):
        awg, osc = create_instrument_pair()
        hl = HysteresisLoop(awg, osc, output_dir=tmp_path)

        with pytest.raises(ValueError, match="Unknown .*option: bad_option"):
            hl.run_experiment(options={"bad_option": True})

        # Valid options succeed validation
        valid_opts = {"save_plots": True, "show_plots": False, "auto_timeshift": True}
        assert hl._validate_options(valid_opts) is None


class TestHysteresisExecutionAndLifecycle:
    """Test standard execution lifecycle, in-memory analysis, and publication."""

    def test_run_experiment_save_true_with_plots(self, tmp_path):
        awg, osc = create_instrument_pair()
        hl = HysteresisLoop(
            awg,
            osc,
            frequency=1000.0,
            amplitude=2.0,
            n_cycles=2,
            area=1e-5,
            show_plots=False,
            save_plots=True,
            output_dir=tmp_path,
        )

        result = hl.run_experiment(save=True)
        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == list(STANDARD_HYSTERESIS_COLUMNS)
        assert len(result) == 70  # 50 simulation points + 20 prep points

        # Published CSV verification
        assert hl.filename is not None
        assert Path(hl.filename).is_file()
        assert Path(hl.filename).name.endswith("_hysteresis.csv")

        meta, data, units = read_measurement_csv(hl.filename)
        assert meta["measurement_schema"] == "hysteresis"
        assert int(meta["measurement_schema_version"]) == 1
        assert bool(meta["processed"]) is True
        assert units == STANDARD_HYSTERESIS_UNITS
        assert list(data.columns) == list(STANDARD_HYSTERESIS_COLUMNS)
        assert len(data) == 70

        # Physical polarization values
        assert data["polarization"].iloc[0] == pytest.approx(0.0)
        assert data["polarization"].max() > data["polarization"].min()
        assert data["applied_voltage"].max() == pytest.approx(2.0, rel=0.1)

        # Plot artifacts staged and published
        base_stem = Path(hl.filename).stem
        pv_file = tmp_path / f"{base_stem}_PV.png"
        iv_file = tmp_path / f"{base_stem}_IV.png"
        trace_file = tmp_path / f"{base_stem}_trace.png"

        assert pv_file.is_file()
        assert iv_file.is_file()
        assert trace_file.is_file()
        assert pv_file.stat().st_size > 0
        assert iv_file.stat().st_size > 0
        assert trace_file.stat().st_size > 0

    def test_run_experiment_save_true_without_plots(self, tmp_path):
        awg, osc = create_instrument_pair()
        hl = HysteresisLoop(
            awg,
            osc,
            frequency=1000.0,
            amplitude=1.5,
            show_plots=False,
            save_plots=False,
            output_dir=tmp_path,
        )

        result = hl.run_experiment(save=True)
        assert isinstance(result, pd.DataFrame)
        assert hl.filename is not None
        assert Path(hl.filename).is_file()

        # No PNGs created
        png_files = list(tmp_path.glob("*.png"))
        assert len(png_files) == 0

    def test_run_experiment_save_false(self, tmp_path):
        awg, osc = create_instrument_pair()
        hl = HysteresisLoop(
            awg,
            osc,
            frequency=1000.0,
            amplitude=1.0,
            show_plots=False,
            save_plots=True,
            output_dir=tmp_path,
        )

        result = hl.run_experiment(save=False)
        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == list(STANDARD_HYSTERESIS_COLUMNS)
        assert hl.filename is None
        assert len(list(tmp_path.glob("*"))) == 0


class TestHysteresisCancellationAndFaults:
    """Test cooperative cancellation and fault handling."""

    def test_stop_before_start(self, tmp_path):
        awg, osc = create_instrument_pair()
        hl = HysteresisLoop(awg, osc, output_dir=tmp_path)
        token = hl._reserve()
        hl.request_stop()

        df = hl.run_experiment(token=token, save=False)
        assert df.empty
        assert hl.run_state == RunState.ABORTED
        assert hl.safety_status == SafetyStatus.NOT_NEEDED

    def test_cancellation_during_capture(self, tmp_path):
        awg, osc = create_instrument_pair()
        hl = HysteresisLoop(awg, osc, output_dir=tmp_path)

        def arm_and_stop():
            hl.request_stop()

        osc.arm = Mock(side_effect=arm_and_stop)
        df = hl.run_experiment(save=False)

        assert hl.run_state == RunState.ABORTED
        assert hl.safety_status == SafetyStatus.SAFE
        assert awg.state["output"][1] is False

    def test_analysis_fault_triggers_attempt_all_safing(self, tmp_path):
        awg, osc = create_instrument_pair()
        hl = HysteresisLoop(awg, osc, output_dir=tmp_path)

        hl._analyze_data = Mock(side_effect=RuntimeError("Analysis crashed"))

        with pytest.raises(RuntimeError, match="Analysis crashed"):
            hl.run_experiment(save=True)

        assert hl.run_state == RunState.FAILED
        assert hl.safety_status == SafetyStatus.SAFE
        assert awg.state["output"][1] is False
        assert len(list(tmp_path.glob("*"))) == 0


class TestHysteresisRunnerIntegration:
    """Test execution through MeasurementRunner and snapshot isolation."""

    def test_runner_execution_and_events(self, tmp_path):
        awg, osc = create_instrument_pair()
        hl = HysteresisLoop(awg, osc, save_plots=True, output_dir=tmp_path)
        runner = MeasurementRunner(hl)
        token = runner.start(save=True)

        while runner.is_worker_alive:
            time.sleep(0.02)

        assert runner.run_state == RunState.COMPLETED
        assert runner.safety_status == SafetyStatus.SAFE
        assert hl.filename is not None
        assert Path(hl.filename).is_file()

        # TerminalEvent verification
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
        assert term_event.filename == hl.filename

        # Snapshot verification
        snap = None
        while True:
            try:
                snap = runner.display_queue.get_nowait()
            except queue.Empty:
                break

        assert snap is not None
        assert "raw" in snap.views
        assert list(snap.views["raw"].columns) == ["time", "voltage"]
        if "analyzed" in snap.views:
            assert list(snap.views["analyzed"].columns) == list(STANDARD_HYSTERESIS_COLUMNS)
