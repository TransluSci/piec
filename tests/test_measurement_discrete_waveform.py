"""
Unit, lifecycle, fault-injection, and integration tests for standardized DiscreteWaveform.

Fulfills Checkpoint 20a of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Target API and schema: schema 'discrete_waveform', version 1;
- Plain lowercase columns: ['time', 'voltage'] with canonical units {'time': 's', 'voltage': 'V'};
- Inherits BaseMeasurement with shared lifecycle, runner, and session support;
- Zero instrument I/O in __init__;
- Option validation before reservation/I/O;
- Stop-before-start zero I/O with ABORTED state and NOT_NEEDED safety;
- Strict trigger ordering: arm scope -> enable AWG output -> fire AWG trigger;
- WaveformReader setup adapter standardizes oscilloscope reads;
- Attempt-all output safing guaranteeing all AWG channels are disabled and zeroed;
- Execution with MeasurementRunner and snapshot isolation.
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

from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.measurement.contracts import (
    ConcurrentRunError,
    HardwareSafetyError,
    MeasurementLifecycleError,
    RunState,
    SafetyStatus,
    TerminalEvent,
)
from piec.measurement.discrete_waveform import DiscreteWaveform
from piec.measurement.persistence import read_measurement_csv
from piec.measurement.runner import MeasurementRunner


def create_instrument_pair():
    """Create a paired VirtualAwg and VirtualScope for testing."""
    awg = VirtualAwg(simulation_points=50)
    osc = VirtualScope(simulation_points=50)
    return awg, osc


class TestDiscreteWaveformConstructorAndValidation:
    """Test constructor parameter validation and zero I/O guarantee."""

    def test_constructor_zero_io(self):
        awg = Mock()
        osc = Mock()
        dw = DiscreteWaveform(awg, osc)

        # Constructor must not call instrument methods
        assert awg.idn.call_count == 0
        assert awg.initialize.call_count == 0
        assert awg.output.call_count == 0
        assert osc.idn.call_count == 0
        assert osc.initialize.call_count == 0
        assert osc.arm.call_count == 0

    def test_constructor_parameter_validation(self):
        awg, osc = create_instrument_pair()

        with pytest.raises(ValueError, match="v_div must be a positive finite number"):
            DiscreteWaveform(awg, osc, v_div=-0.01)

        with pytest.raises(ValueError, match="v_div must be a positive finite number"):
            DiscreteWaveform(awg, osc, v_div=float("nan"))

        with pytest.raises(ValueError, match="length must be a positive finite number"):
            DiscreteWaveform(awg, length=0, osc=osc)

        with pytest.raises(ValueError, match="length must be a positive finite number"):
            DiscreteWaveform(awg, osc, length=float("inf"))

        with pytest.raises(ValueError, match="osc_channel must be a positive integer"):
            DiscreteWaveform(awg, osc, osc_channel=0)

        with pytest.raises(ValueError, match="osc_channel must be a positive integer"):
            DiscreteWaveform(awg, osc, osc_channel=True)

        with pytest.raises(ValueError, match="voltage_channel must be convertible to int"):
            DiscreteWaveform(awg, osc, voltage_channel="invalid")

    def test_validate_options(self, tmp_path):
        awg, osc = create_instrument_pair()
        dw = DiscreteWaveform(awg, osc, output_dir=tmp_path)

        with pytest.raises(ValueError, match="Unknown option: bad_option"):
            dw.run_experiment(options={"bad_option": True})


class TestDiscreteWaveformTriggerOrdering:
    """Verify strict trigger ordering: osc.arm() -> awg.output(on=True) -> awg.output_trigger()."""

    def test_strict_trigger_sequence(self, tmp_path):
        awg = Mock()
        awg.channel = [1, 2]
        awg.idn.return_value = "Mock AWG"
        osc = Mock()
        osc.idn.return_value = "Mock Scope"
        osc.get_data.return_value = pd.DataFrame({"time": [0.0, 1e-6], "voltage": [0.0, 1.0]})

        call_log = []
        osc.arm.side_effect = lambda: call_log.append("osc_arm")
        awg.output.side_effect = lambda *args, **kwargs: call_log.append(f"awg_output_{kwargs.get('on')}")
        awg.output_trigger.side_effect = lambda: call_log.append("awg_trigger")

        dw = DiscreteWaveform(awg, osc, length=0.0001, output_dir=tmp_path)
        dw.run_experiment(save=False)

        # First awg_output_False during _configure_instruments
        assert call_log[0] == "awg_output_False"

        # In _capture_data, the order must strictly be: osc_arm -> awg_output_True -> awg_trigger
        capture_events = [e for e in call_log if e in ("osc_arm", "awg_output_True", "awg_trigger")]
        assert capture_events == ["osc_arm", "awg_output_True", "awg_trigger"], (
            f"Incorrect trigger sequence: {capture_events}"
        )

        # On exit, output must be turned off
        assert call_log[-1] == "awg_output_False"


class TestDiscreteWaveformLifecycleAndSession:
    """Test standardized lifecycle, sessions, and persistence."""

    def test_standalone_configure_and_capture(self, tmp_path):
        awg, osc = create_instrument_pair()
        dw = DiscreteWaveform(awg, osc, v_div=0.05, length=0.001, output_dir=tmp_path)

        # Standalone configure
        dw.configure_instruments()
        assert awg.state["load_impedance"][1] == 50.0
        assert str(awg.state["trigger_source"][1]).upper() == "MAN"

        # Standalone capture
        data = dw.capture_data()
        assert isinstance(data, pd.DataFrame)
        assert list(data.columns) == ["time", "voltage"]
        assert len(data) == 70

    def test_piecewise_session(self, tmp_path):
        awg, osc = create_instrument_pair()
        dw = DiscreteWaveform(awg, osc, output_dir=tmp_path)

        with dw.session(save=False) as sess:
            assert sess.run_state == RunState.STARTING
            sess.configure_instruments()
            data = sess.capture_data()
            assert list(data.columns) == ["time", "voltage"]

            # Double capture within single session is illegal
            with pytest.raises(RuntimeError, match="at most one capture operation"):
                sess.capture_data()

        assert dw.run_state == RunState.COMPLETED
        assert dw.safety_status == SafetyStatus.SAFE

    def test_run_experiment_save_true_and_false(self, tmp_path):
        awg, osc = create_instrument_pair()
        dw = DiscreteWaveform(awg, osc, output_dir=tmp_path)

        # Save = False
        df_nosave = dw.run_experiment(save=False)
        assert isinstance(df_nosave, pd.DataFrame)
        assert dw.filename is None

        # Save = True
        df_save = dw.run_experiment(save=True)
        assert isinstance(df_save, pd.DataFrame)
        assert dw.filename is not None
        assert Path(dw.filename).is_file()
        assert Path(dw.filename).name.endswith("_discrete_waveform.csv")

        # Verify CSV content via persistence reader
        meta, data, units = read_measurement_csv(dw.filename)
        assert meta["measurement_schema"] == "discrete_waveform"
        assert int(meta["measurement_schema_version"]) == 1
        assert units == {"time": "s", "voltage": "V"}
        assert list(data.columns) == ["time", "voltage"]
        assert len(data) == 70


class TestDiscreteWaveformCancellationAndFaults:
    """Test cooperative cancellation and fault handling."""

    def test_stop_before_start(self, tmp_path):
        awg, osc = create_instrument_pair()
        dw = DiscreteWaveform(awg, osc, output_dir=tmp_path)
        token = dw._reserve()
        dw.request_stop()

        df = dw.run_experiment(token=token, save=False)
        assert df.empty
        assert dw.run_state == RunState.ABORTED
        assert dw.safety_status == SafetyStatus.NOT_NEEDED

    def test_cancellation_during_dwell(self, tmp_path):
        awg, osc = create_instrument_pair()
        dw = DiscreteWaveform(awg, osc, length=0.5, output_dir=tmp_path)

        # Stop immediately when capture starts
        def arm_and_stop():
            dw.request_stop()

        osc.arm = Mock(side_effect=arm_and_stop)
        df = dw.run_experiment(save=False)

        assert dw.run_state == RunState.ABORTED
        assert dw.safety_status == SafetyStatus.SAFE

    def test_callback_fault_does_not_prevent_safing(self, tmp_path):
        awg, osc = create_instrument_pair()
        dw = DiscreteWaveform(awg, osc, output_dir=tmp_path)

        def exploding_callback(snap):
            raise RuntimeError("UI explosion")

        with pytest.raises(RuntimeError, match="UI explosion"):
            dw.run_experiment(on_update=exploding_callback)

        assert dw.run_state == RunState.FAILED
        assert dw.safety_status == SafetyStatus.SAFE
        assert awg.state["output"][1] is False


class TestDiscreteWaveformAttemptAllSafing:
    """Test guaranteed attempt-all output safing."""

    def test_attempt_all_safing_with_partial_fault(self, tmp_path):
        awg = Mock()
        awg.channel = [1, 2]
        awg.idn.return_value = "Mock AWG"
        osc = Mock()
        osc.idn.return_value = "Mock Scope"
        osc.get_data.return_value = pd.DataFrame({"time": [0.0], "voltage": [0.0]})

        # Action 1 (channel 1 disable) fails
        def output_fault(channel, on):
            if channel == 1 and not on:
                raise OSError("Channel 1 relay failure")

        awg.output.side_effect = output_fault

        dw = DiscreteWaveform(awg, osc, voltage_channel="1", output_dir=tmp_path)
        # Initial disable is a configuration failure and remains the primary error,
        # even when the required shutdown retry fails as well.
        with pytest.raises(OSError, match="Channel 1 relay failure"):
            dw.run_experiment(save=False)

        assert dw.run_state == RunState.FAILED
        assert dw.safety_status == SafetyStatus.UNSAFE
        osc.arm.assert_not_called()
        awg.output_trigger.assert_not_called()
        # Channel 2 disable MUST still have been attempted!
        assert call(channel=2, on=False) in awg.output.call_args_list
        # Zero amplitude MUST still have been attempted!
        awg.set_amplitude.assert_called_with(channel=1, amplitude=0.0)


class TestDiscreteWaveformRunnerIntegration:
    """Test execution through MeasurementRunner."""

    def test_runner_execution_and_events(self, tmp_path):
        awg, osc = create_instrument_pair()
        dw = DiscreteWaveform(awg, osc, output_dir=tmp_path)
        runner = MeasurementRunner(dw)
        token = runner.start(save=True)

        while runner.is_worker_alive:
            time.sleep(0.02)

        assert runner.run_state == RunState.COMPLETED
        assert runner.safety_status == SafetyStatus.SAFE
        assert dw.filename is not None
        assert Path(dw.filename).is_file()

        # Check terminal queue for TerminalEvent
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
        assert term_event.filename == dw.filename

        # Check display queue for snapshots
        snap = None
        while True:
            try:
                snap = runner.display_queue.get_nowait()
            except queue.Empty:
                break

        assert snap is not None
        assert "raw" in snap.views
        assert list(snap.views["raw"].columns) == ["time", "voltage"]

@pytest.mark.parametrize('error_type', [AttributeError, NotImplementedError, OSError])
def test_waveform_configuration_error_aborts_before_capture(error_type):
    awg, osc = create_instrument_pair()
    awg.output = Mock(wraps=awg.output)
    awg.output_trigger = Mock()
    osc.arm = Mock()
    dw = DiscreteWaveform(awg, osc)
    dw.configure_awg = Mock(side_effect=error_type('setup failed'))
    with pytest.raises(error_type, match='setup failed'):
        dw.run_experiment(save=False)
    assert dw.run_state == RunState.FAILED
    osc.arm.assert_not_called()
    awg.output_trigger.assert_not_called()
    assert not any(c.kwargs.get('on') is True for c in awg.output.call_args_list)
    assert any(c.kwargs.get('on') is False for c in awg.output.call_args_list)


def test_initial_disable_failure_aborts_and_retries_safing():
    awg, osc = create_instrument_pair()
    original = awg.output
    attempts = []
    def output(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise OSError('initial disable failed')
        return original(**kwargs)
    awg.output = output
    awg.initialize = Mock()
    osc.arm = Mock()
    dw = DiscreteWaveform(awg, osc)
    with pytest.raises(OSError, match='initial disable failed'):
        dw.run_experiment(save=False)
    assert dw.run_state == RunState.FAILED
    assert dw.safety_status == SafetyStatus.SAFE
    awg.initialize.assert_not_called()
    osc.arm.assert_not_called()
    assert len(attempts) >= 3
    assert all(c['on'] is False for c in attempts)


@pytest.mark.parametrize('stop_phase', ['arm', 'enable'])
def test_stop_between_capture_commands_prevents_trigger(stop_phase):
    awg, osc = create_instrument_pair()
    dw = DiscreteWaveform(awg, osc)
    original = awg.output
    def output(**kwargs):
        result = original(**kwargs)
        if kwargs.get('on') and stop_phase == 'enable':
            dw.request_stop()
        return result
    awg.output = Mock(side_effect=output)
    awg.output_trigger = Mock()
    if stop_phase == 'arm':
        osc.arm = Mock(side_effect=dw.request_stop)
    dw.run_experiment(save=False)
    assert dw.run_state == RunState.ABORTED
    assert dw.safety_status == SafetyStatus.SAFE
    awg.output_trigger.assert_not_called()
    if stop_phase == 'arm':
        assert not any(c.kwargs.get('on') for c in awg.output.call_args_list)
    assert awg.state['output'][1] is False


def test_migrated_base_has_no_legacy_capture_save_or_directory_alias(tmp_path):
    awg, osc = create_instrument_pair()
    with pytest.raises(TypeError, match='save_dir'):
        DiscreteWaveform(awg, osc, save_dir=tmp_path)
    dw = DiscreteWaveform(awg, osc, output_dir=tmp_path)
    for name in ('save_dir', 'apply_and_capture_waveform', 'save_waveform', '_legacy_capture', '_legacy_save'):
        assert not hasattr(dw, name)
