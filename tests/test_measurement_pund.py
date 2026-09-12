"""
Unit, lifecycle, fault-injection, and integration tests for standardized ThreePulsePund.

Fulfills Checkpoint 20c of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Target API and schema: schema 'three_pulse_pund', version 1;
- Plain lowercase columns:
  ['time', 'voltage', 'current', 'polarization', 'polarization_p_hat',
   'polarization_p_star', 'polarization_p_hat_r', 'polarization_p_star_r',
   'delta_polarization', 'applied_voltage']
  with canonical JSON units matching STANDARD_PUND_UNITS;
- Inherits DiscreteWaveform and BaseMeasurement with shared lifecycle, runner, and session support;
- In-memory scientific processing (process_pund);
- Multi-artifact plot staging (_dPvst.png, _trace.png) when save=True and save_plots=True;
- Suppression of plots when save=False or save_plots=False;
- Removal of legacy ThreePulsePund bypass paths and unmigrated attributes (save_dir, apply_and_capture_waveform, save_waveform, analyze);
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

from piec.analysis.pund import (
    STANDARD_PUND_COLUMNS,
    STANDARD_PUND_UNITS,
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
from piec.measurement.discrete_waveform import ThreePulsePund
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


class TestPundConstructorAndValidation:
    """Test constructor parameter validation, zero I/O guarantee, and schema metadata."""

    def test_constructor_zero_io(self):
        awg = Mock()
        osc = Mock()
        pund = ThreePulsePund(awg, osc)

        # Constructor must not call instrument methods
        assert awg.idn.call_count == 0
        assert awg.initialize.call_count == 0
        assert awg.output.call_count == 0
        assert osc.idn.call_count == 0
        assert osc.initialize.call_count == 0
        assert osc.arm.call_count == 0

    def test_schema_and_metadata_attributes(self, tmp_path):
        awg, osc = create_instrument_pair()
        pund = ThreePulsePund(
            awg,
            osc,
            reset_amp=2.0,
            reset_width=2e-3,
            reset_delay=1e-3,
            p_u_amp=1.5,
            p_u_width=1e-3,
            p_u_delay=2e-3,
            offset=0.1,
            area=2e-5,
            r_shunt=100.0,
            time_offset=5e-8,
            auto_timeshift=False,
            show_plots=False,
            save_plots=True,
            output_dir=tmp_path,
        )

        assert pund.mtype == "3pulsepund"
        assert pund.measurement_schema == "three_pulse_pund"
        assert pund.measurement_schema_version == 1
        assert pund.column_units == STANDARD_PUND_UNITS
        assert pund.raw_column_units == {"time": "s", "voltage": "V"}
        assert pund.reset_amp == 2.0
        assert pund.reset_width == 2e-3
        assert pund.reset_delay == 1e-3
        assert pund.p_u_amp == 1.5
        assert pund.p_u_width == 1e-3
        assert pund.p_u_delay == 2e-3
        assert pund.offset == 0.1
        assert pund.area == 2e-5
        assert pund.r_shunt == 100.0
        assert pund.time_offset == 5e-8
        assert pund.auto_timeshift is False
        assert pund.save_plots is True
        assert pund.notes == "2p0Vres_1p5Vpu"
        assert pund.length == pytest.approx(2e-3 + 1e-3 + 2 * 1e-3 + 2 * 2e-3)

    def test_constructor_parameter_validation(self):
        awg, osc = create_instrument_pair()

        with pytest.raises(ValueError, match="reset_width must be a positive finite number"):
            ThreePulsePund(awg, osc, reset_width=-1e-3)

        with pytest.raises(ValueError, match="reset_width must be a positive finite number"):
            ThreePulsePund(awg, osc, reset_width=0.0)

        with pytest.raises(ValueError, match="reset_delay must be a positive finite number"):
            ThreePulsePund(awg, osc, reset_delay=-1e-3)

        with pytest.raises(ValueError, match="p_u_width must be a positive finite number"):
            ThreePulsePund(awg, osc, p_u_width=0.0)

        with pytest.raises(ValueError, match="p_u_delay must be a positive finite number"):
            ThreePulsePund(awg, osc, p_u_delay=float("nan"))

        with pytest.raises(ValueError, match="reset_amp must be a finite number"):
            ThreePulsePund(awg, osc, reset_amp=float("inf"))

        with pytest.raises(ValueError, match="p_u_amp must be a finite number"):
            ThreePulsePund(awg, osc, p_u_amp=float("nan"))

        with pytest.raises(ValueError, match="offset must be a finite number"):
            ThreePulsePund(awg, osc, offset=float("-inf"))

        with pytest.raises(ValueError, match="area must be a positive finite number"):
            ThreePulsePund(awg, osc, area=-1e-5)

        with pytest.raises(ValueError, match="r_shunt must be a positive finite number"):
            ThreePulsePund(awg, osc, r_shunt=0)

        with pytest.raises(ValueError, match="r_shunt must be a positive finite number"):
            ThreePulsePund(awg, osc, r_shunt=-50)

        with pytest.raises(ValueError, match="time_offset must be a finite non-negative number"):
            ThreePulsePund(awg, osc, time_offset=-1e-8)

        with pytest.raises(ValueError, match="time_offset must be a finite non-negative number"):
            ThreePulsePund(awg, osc, time_offset=float("nan"))

        with pytest.raises(ValueError, match="auto_timeshift must be a boolean"):
            ThreePulsePund(awg, osc, auto_timeshift="True")

        with pytest.raises(ValueError, match="show_plots must be a boolean"):
            ThreePulsePund(awg, osc, show_plots=1)

        with pytest.raises(ValueError, match="save_plots must be a boolean"):
            ThreePulsePund(awg, osc, save_plots=0)

    def test_rejection_of_legacy_attributes_and_save_dir(self, tmp_path):
        awg, osc = create_instrument_pair()

        # save_dir must be rejected as an unknown keyword argument
        with pytest.raises(TypeError, match="save_dir"):
            ThreePulsePund(awg, osc, save_dir=tmp_path)

        pund = ThreePulsePund(awg, osc, output_dir=tmp_path)
        for legacy_attr in ("save_dir", "apply_and_capture_waveform", "save_waveform", "analyze"):
            assert not hasattr(pund, legacy_attr), f"Legacy attribute {legacy_attr} must not exist on ThreePulsePund"

    def test_validate_options(self, tmp_path):
        awg, osc = create_instrument_pair()
        pund = ThreePulsePund(awg, osc, output_dir=tmp_path)

        with pytest.raises(ValueError, match="Unknown .*option: bad_option"):
            pund.run_experiment(options={"bad_option": True})

        # Valid options succeed validation
        valid_opts = {"save_plots": True, "show_plots": False, "auto_timeshift": True}
        assert pund._validate_options(valid_opts) is None


class TestPundExecutionAndLifecycle:
    """Test standard execution lifecycle, in-memory analysis, and publication."""

    def test_run_experiment_save_true_with_plots(self, tmp_path):
        awg, osc = create_instrument_pair()
        pund = ThreePulsePund(
            awg,
            osc,
            reset_amp=1.0,
            reset_width=1e-3,
            reset_delay=1e-3,
            p_u_amp=1.0,
            p_u_width=1e-3,
            p_u_delay=1e-3,
            area=1e-5,
            show_plots=False,
            save_plots=True,
            output_dir=tmp_path,
        )

        result = pund.run_experiment(save=True)
        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == list(STANDARD_PUND_COLUMNS)
        assert len(result) == 70  # 50 simulation points + 20 prep points

        # Published CSV verification
        assert pund.filename is not None
        assert Path(pund.filename).is_file()
        assert Path(pund.filename).name.endswith("_three_pulse_pund.csv")

        meta, data, units = read_measurement_csv(pund.filename)
        assert meta["measurement_schema"] == "three_pulse_pund"
        assert int(meta["measurement_schema_version"]) == 1
        assert bool(meta["processed"]) is True
        assert units == STANDARD_PUND_UNITS
        assert list(data.columns) == list(STANDARD_PUND_COLUMNS)
        assert len(data) == 70

        # Physical polarization values
        assert data["polarization"].iloc[0] == pytest.approx(0.0)
        assert data["delta_polarization"].max() > 0.0

        # Plot artifacts staged and published
        base_stem = Path(pund.filename).stem
        dp_file = tmp_path / f"{base_stem}_dPvst.png"
        trace_file = tmp_path / f"{base_stem}_trace.png"

        assert dp_file.is_file(), f"Expected plot {dp_file} missing"
        assert trace_file.is_file(), f"Expected plot {trace_file} missing"
        assert dp_file.stat().st_size > 0
        assert trace_file.stat().st_size > 0

    def test_run_experiment_save_true_without_plots(self, tmp_path):
        awg, osc = create_instrument_pair()
        pund = ThreePulsePund(
            awg,
            osc,
            show_plots=False,
            save_plots=False,
            output_dir=tmp_path,
        )

        result = pund.run_experiment(save=True)
        assert isinstance(result, pd.DataFrame)
        assert pund.filename is not None
        assert Path(pund.filename).is_file()

        # No PNGs created when save_plots=False
        png_files = list(tmp_path.glob("*.png"))
        assert len(png_files) == 0

    def test_run_experiment_save_false(self, tmp_path):
        awg, osc = create_instrument_pair()
        pund = ThreePulsePund(
            awg,
            osc,
            show_plots=False,
            save_plots=True,
            output_dir=tmp_path,
        )

        result = pund.run_experiment(save=False)
        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == list(STANDARD_PUND_COLUMNS)
        assert pund.filename is None

        # Zero files written when save=False
        all_files = list(tmp_path.glob("*"))
        assert len(all_files) == 0


class TestPundCancellationAndFaults:
    """Test cooperative cancellation and fault handling."""

    def test_stop_before_start(self, tmp_path):
        awg, osc = create_instrument_pair()
        pund = ThreePulsePund(awg, osc, output_dir=tmp_path)
        token = pund._reserve()
        pund.request_stop()

        df = pund.run_experiment(token=token, save=False)
        assert df.empty
        assert pund.run_state == RunState.ABORTED
        assert pund.safety_status == SafetyStatus.NOT_NEEDED

    def test_cancellation_during_capture(self, tmp_path):
        awg, osc = create_instrument_pair()
        pund = ThreePulsePund(awg, osc, output_dir=tmp_path)

        def arm_and_stop():
            pund.request_stop()

        osc.arm = Mock(side_effect=arm_and_stop)
        df = pund.run_experiment(save=False)

        assert pund.run_state == RunState.ABORTED
        assert pund.safety_status == SafetyStatus.SAFE
        assert awg.state["output"][1] is False

    def test_analysis_fault_triggers_attempt_all_safing(self, tmp_path):
        awg, osc = create_instrument_pair()
        pund = ThreePulsePund(awg, osc, output_dir=tmp_path)

        pund._analyze_data = Mock(side_effect=RuntimeError("PUND analysis crashed"))

        with pytest.raises(RuntimeError, match="PUND analysis crashed"):
            pund.run_experiment(save=True)

        assert pund.run_state == RunState.FAILED
        assert pund.safety_status == SafetyStatus.SAFE
        assert awg.state["output"][1] is False
        assert len(list(tmp_path.glob("*"))) == 0

    def test_attempt_all_safe_shutdown(self):
        awg = Mock()
        osc = Mock()
        awg.channel = [1, 2]
        pund = ThreePulsePund(awg, osc)

        report = pund.safe_shutdown()
        assert report.status == SafetyStatus.SAFE
        # Both channels must be disabled
        awg.output.assert_has_calls([call(channel=1, on=False), call(channel=2, on=False)], any_order=True)


class TestPundRunnerIntegration:
    """Test execution through MeasurementRunner and snapshot isolation."""

    def test_runner_execution_and_events(self, tmp_path):
        awg, osc = create_instrument_pair()
        pund = ThreePulsePund(awg, osc, save_plots=True, output_dir=tmp_path)
        runner = MeasurementRunner(pund)
        token = runner.start(save=True)

        while runner.is_worker_alive:
            time.sleep(0.02)

        assert runner.run_state == RunState.COMPLETED
        assert runner.safety_status == SafetyStatus.SAFE
        assert pund.filename is not None
        assert Path(pund.filename).is_file()

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
        assert term_event.filename == pund.filename

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
            assert list(snap.views["analyzed"].columns) == list(STANDARD_PUND_COLUMNS)
