"""
Unit, lifecycle, fault-injection, and integration tests for standardized MagnetoTransport.

Fulfills Checkpoint 24a of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Target API and schema: schema 'amr', version 1;
- Plain lowercase columns: ['angle', 'field', 'x', 'y'] with canonical units {'angle': 'deg', 'field': 'Oe', 'x': 'V', 'y': 'V'};
- Inherits BaseMeasurement with shared lifecycle, runner, and session support;
- Zero instrument I/O in __init__;
- Setup role composition (AMRSetupProfile) and role accessors;
- Lock-in settings preservation by default (readout_configuration='preserve');
- Validation of excitation shutdown policy before energizing;
- Attempt-all safe shutdown propagating role errors and unconfirmed shutdown to SafetyStatus.UNSAFE;
- Connection retention on unsafe shutdown;
- Stop-before-start zero-I/O aborts with ABORTED state and NOT_NEEDED safety;
- Piecewise execution sessions via mt.session();
- Execution with MeasurementRunner and live snapshot delivery.
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

from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.lockin.virtual_lockin import VirtualLockin
from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
from piec.measurement.adapters.amr import (
    AMRSetupProfile,
    FieldReader,
    FieldSource,
    OrientationController,
    TransportReadout,
)
from piec.measurement.contracts import (
    ConcurrentRunError,
    HardwareSafetyError,
    MeasurementLifecycleError,
    RunRecord,
    RunRequest,
    RunState,
    SafetyReport,
    SafetyStatus,
    TerminalEvent,
)
from piec.measurement.magneto_transport import MagnetoTransport
from piec.measurement.persistence import read_measurement_csv
from piec.measurement.runner import MeasurementRunner


def create_virtual_instruments():
    """Create a complete set of virtual instruments for magneto-transport testing."""
    cal = VirtualCalibrator()
    cal._last_set_voltage = 0.0
    orig_set_output = cal.set_output

    def set_output_wrapper(val, *args, **kwargs):
        cal._last_set_voltage = val
        return orig_set_output(val, *args, **kwargs)

    cal.set_output = set_output_wrapper

    dmm = VirtualDMM()
    dmm.set_voltage_reader(lambda: getattr(cal, "_last_set_voltage", 0.0))
    stepper = VirtualStepper()
    lockin = VirtualLockin()
    return {"calibrator": cal, "dmm": dmm, "arduino": stepper, "lockin": lockin}


def create_mock_instruments():
    """Create mock instruments for precise call and fault tracking."""
    cal = Mock()
    cal.idn.return_value = "MOCK_CALIBRATOR"
    cal.set_output = Mock()
    cal.output = Mock()

    dmm = Mock()
    dmm.idn.return_value = "MOCK_DMM"
    dmm.get_voltage.side_effect = lambda: (
        cal.set_output.call_args[0][0] if cal.set_output.call_args else 0.01
    )

    stepper = Mock()
    stepper.idn.return_value = "MOCK_STEPPER"
    stepper.step = Mock()
    stepper.halt = Mock()

    lockin = Mock()
    lockin.idn.return_value = "MOCK_LOCKIN"
    lockin.get_X_Y.return_value = (102e-6, 10.2e-6)
    lockin.initialize = Mock()
    lockin.configure_reference = Mock()
    lockin.configure_input = Mock()
    lockin.configure_gain_filters = Mock()

    return {"calibrator": cal, "dmm": dmm, "arduino": stepper, "lockin": lockin}


# ============================================================================
# 1. Constructor and Parameter Validation
# ============================================================================

class TestMagnetoTransportConstructorAndValidation:
    """Test constructor zero-I/O guarantee, parameter validation, and role properties."""

    def test_constructor_zero_io(self):
        mocks = create_mock_instruments()
        mt = MagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=500.0,
        )

        assert mocks["dmm"].idn.call_count == 0
        assert mocks["calibrator"].idn.call_count == 0
        assert mocks["calibrator"].set_output.call_count == 0
        assert mocks["arduino"].idn.call_count == 0
        assert mocks["arduino"].step.call_count == 0
        assert mocks["lockin"].idn.call_count == 0
        assert mocks["lockin"].initialize.call_count == 0

    def test_constructor_attributes_and_profile_wiring(self, tmp_path):
        mocks = create_mock_instruments()
        mt = MagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=250.0,
            output_dir=tmp_path,
            voltage_calibration=5000.0,
        )

        assert mt.field == 250.0
        assert mt.voltage_calibration == 5000.0
        assert mt.voltage_callibration == 5000.0
        assert mt.output_dir == tmp_path
        assert mt.profile is not None
        assert isinstance(mt.field_source, FieldSource)
        assert isinstance(mt.field_reader, FieldReader)
        assert isinstance(mt.transport_readout, TransportReadout)
        assert isinstance(mt.orientation_controller, OrientationController)
        assert mt.field_source.instrument is mocks["calibrator"]
        assert mt.field_reader.instrument is mocks["dmm"]
        assert mt.transport_readout.instrument is mocks["lockin"]
        assert mt.orientation_controller.instrument is mocks["arduino"]
        assert mt.stepper is mocks["arduino"]
        assert mt.arduino is mocks["arduino"]

    def test_constructor_with_explicit_profile(self):
        v = create_virtual_instruments()
        profile = AMRSetupProfile.from_instruments(
            dmm=v["dmm"],
            calibrator=v["calibrator"],
            arduino=v["arduino"],
            lockin=v["lockin"],
            field_calibration=10000.0,
            readout_configuration="preserve",
        )
        mt = MagnetoTransport(profile=profile, field=100.0)

        assert mt.profile is profile
        assert mt.dmm is v["dmm"]
        assert mt.calibrator is v["calibrator"]
        assert mt.stepper is v["arduino"]
        assert mt.arduino is v["arduino"]
        assert mt.lockin is v["lockin"]

    def test_constructor_rejects_non_finite_field(self):
        mocks = create_mock_instruments()
        with pytest.raises(ValueError, match="field must be a finite number"):
            MagnetoTransport(
                dmm=mocks["dmm"],
                calibrator=mocks["calibrator"],
                stepper=mocks["arduino"],
                lockin=mocks["lockin"],
                field=float("nan"),
            )

    def test_option_validation(self, tmp_path):
        mocks = create_mock_instruments()
        mt = MagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            output_dir=tmp_path,
        )

        with pytest.raises(ValueError, match="Unknown option: bad_option"):
            mt.run_experiment(options={"bad_option": 123})

        with pytest.raises(ValueError, match="readout_configuration must be 'preserve' or 'configure'"):
            mt.run_experiment(options={"readout_configuration": "invalid_mode"})


# ============================================================================
# 2. Lock-In Settings Preservation Contract
# ============================================================================

class TestLockInPreservationContract:
    """Test manual lock-in settings preservation vs explicit automated configuration."""

    def test_preserve_mode_sends_zero_writes_to_lockin(self, tmp_path):
        mocks = create_mock_instruments()
        shutdown = Mock()
        mt = MagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            output_dir=tmp_path,
            readout_configuration="preserve",
            shutdown_handler=shutdown,
        )

        df = mt.run_experiment(save=False)
        assert len(df) == 1
        assert mocks["lockin"].initialize.call_count == 0
        assert mocks["lockin"].configure_reference.call_count == 0
        assert mocks["lockin"].configure_input.call_count == 0
        assert mocks["lockin"].configure_gain_filters.call_count == 0
        assert shutdown.call_count == 1

    def test_configure_mode_sends_validated_writes(self, tmp_path):
        mocks = create_mock_instruments()
        shutdown = Mock()
        mt = MagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            output_dir=tmp_path,
            readout_configuration="configure",
            shutdown_handler=shutdown,
        )

        df = mt.run_experiment(save=False)
        assert len(df) == 1
        mocks["lockin"].configure_reference.assert_called_once()
        mocks["lockin"].configure_input.assert_called_once()
        mocks["lockin"].configure_gain_filters.assert_called_once()

    def test_configure_lockin_option_overrides_preserve(self, tmp_path):
        mocks = create_mock_instruments()
        shutdown = Mock()
        mt = MagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            output_dir=tmp_path,
            readout_configuration="preserve",
            shutdown_handler=shutdown,
        )

        df = mt.run_experiment(options={"configure_lockin": True}, save=False)
        assert len(df) == 1
        mocks["lockin"].configure_reference.assert_called_once()


# ============================================================================
# 3. Excitation Safing Validation Before Energizing
# ============================================================================

class TestExcitationSafingValidation:
    """Test excitation safing validation policy before hardware energization."""

    def test_missing_shutdown_handler_rejected_before_energizing_when_required(self, tmp_path):
        mocks = create_mock_instruments()
        mt = MagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=500.0,
            output_dir=tmp_path,
            require_excitation_safing=True,
            shutdown_handler=None,
        )

        with pytest.raises(HardwareSafetyError, match="Excitation shutdown handler required before energizing"):
            mt.run_experiment(save=False)

        # Field source must NEVER have been energized!
        assert mocks["calibrator"].set_output.call_count == 0

    def test_missing_handler_via_options_rejected_before_energizing(self, tmp_path):
        mocks = create_mock_instruments()
        mt = MagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=300.0,
            output_dir=tmp_path,
            require_excitation_safing=False,
            shutdown_handler=None,
        )

        with pytest.raises(HardwareSafetyError, match="Excitation shutdown handler required before energizing"):
            mt.run_experiment(options={"require_excitation_safing": True}, save=False)

        assert mocks["calibrator"].set_output.call_count == 0

    def test_external_excitation_requires_owner(self):
        v = create_virtual_instruments()
        with pytest.raises(ValueError, match="external_source_owner must name who controls and de-energizes"):
            MagnetoTransport(
                dmm=v["dmm"],
                calibrator=v["calibrator"],
                stepper=v["arduino"],
                lockin=v["lockin"],
                excitation_source="external",
                external_source_owner="",
            )


# ============================================================================
# 4. Safe Shutdown and Fault Propagation
# ============================================================================

class TestSafeShutdownAndFaultHardening:
    """Test attempt-all shutdown, UNSAFE propagation, and connection retention."""

    def test_unconfirmed_shutdown_propagates_to_unsafe_with_connections_retained(self, tmp_path):
        mocks = create_mock_instruments()
        mt = MagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            output_dir=tmp_path,
            require_excitation_safing=False,
            shutdown_handler=None,
        )

        with pytest.raises(HardwareSafetyError, match="Hardware safety could not be verified"):
            mt.run_experiment(save=False)

        assert mt.safety_status == SafetyStatus.UNSAFE
        # Attempt-all verified: field source and orientation shutdowns were still performed!
        mocks["calibrator"].set_output.assert_called_with(0.0, mode="voltage")
        mocks["arduino"].halt.assert_called_once()
        # Connection retention: close() must NOT have been called on any instrument
        assert not hasattr(mocks["calibrator"], "close") or mocks["calibrator"].close.call_count == 0
        assert not hasattr(mocks["lockin"], "close") or mocks["lockin"].close.call_count == 0

    def test_confirmed_shutdown_handler_achieves_safe_status(self, tmp_path):
        mocks = create_mock_instruments()
        shutdown = Mock()
        mt = MagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            output_dir=tmp_path,
            shutdown_handler=shutdown,
        )

        df = mt.run_experiment(save=False)
        assert len(df) == 1
        assert mt.safety_status == SafetyStatus.SAFE
        assert shutdown.call_count == 1
        mocks["calibrator"].set_output.assert_called_with(0.0, mode="voltage")
        mocks["arduino"].halt.assert_called_once()

    def test_role_failure_during_shutdown_attempts_all_and_propagates_unsafe(self, tmp_path):
        mocks = create_mock_instruments()
        mocks["calibrator"].set_output.side_effect = [None, RuntimeError("Calibrator zeroing fault")]
        shutdown = Mock()
        mt = MagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            output_dir=tmp_path,
            shutdown_handler=shutdown,
        )

        with pytest.raises(HardwareSafetyError, match="Hardware safety could not be verified"):
            mt.run_experiment(save=False)

        assert mt.safety_status == SafetyStatus.UNSAFE
        # Attempt-all: orientation controller and transport readout were still safed despite calibrator error!
        mocks["arduino"].halt.assert_called_once()
        assert shutdown.call_count == 1


# ============================================================================
# 5. Cooperative Controls (Stop-before-start, Pause)
# ============================================================================

class TestCooperativeControls:
    """Test Stop-before-start zero I/O abort and pause/resume handling."""

    def test_stop_before_start_aborts_with_zero_io(self, tmp_path):
        mocks = create_mock_instruments()
        mt = MagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=200.0,
            output_dir=tmp_path,
        )

        token = mt._reserve()
        mt.request_stop()
        df = mt.run_experiment(token=token, save=False)

        assert df.empty
        assert mt.run_state == RunState.ABORTED
        assert mt.safety_status == SafetyStatus.NOT_NEEDED
        assert mocks["calibrator"].set_output.call_count == 0
        assert mocks["arduino"].step.call_count == 0


# ============================================================================
# 6. Session Execution and Persistence
# ============================================================================

class TestSessionAndPersistence:
    """Test piecewise session execution, CSV schema, and column units."""

    def test_piecewise_session_lifecycle(self, tmp_path):
        v = create_virtual_instruments()
        shutdown = Mock()
        profile = AMRSetupProfile.from_instruments(
            dmm=v["dmm"],
            calibrator=v["calibrator"],
            arduino=v["arduino"],
            lockin=v["lockin"],
            field_calibration=10000.0,
            readout_configuration="preserve",
            shutdown_handler=shutdown,
        )
        mt = MagnetoTransport(profile=profile, field=500.0, output_dir=tmp_path)

        with mt.session(save=True) as sess:
            sess.configure_instruments()
            assert mt.field_source.current_output == pytest.approx(0.05)
            df = sess.capture_data()
            assert len(df) == 1
            assert list(df.columns) == ["angle", "field", "x", "y"]

        assert mt.safety_status == SafetyStatus.SAFE
        assert shutdown.call_count == 1
        assert mt.field_source.current_output == pytest.approx(0.0)

    def test_publication_schema_and_column_units(self, tmp_path):
        mocks = create_mock_instruments()
        shutdown = Mock()
        mt = MagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            output_dir=tmp_path,
            shutdown_handler=shutdown,
        )

        df = mt.run_experiment(save=True)
        assert len(df) == 1
        assert mt.filename is not None
        assert Path(mt.filename).is_file()

        meta, data, units = read_measurement_csv(mt.filename)
        assert meta["measurement_schema"] == "amr"
        assert meta["measurement_schema_version"] == 1
        assert list(data.columns) == ["angle", "field", "x", "y"]
        assert units == {"angle": "deg", "field": "Oe", "x": "V", "y": "V"}


# ============================================================================
# 7. Runner Integration
# ============================================================================

class TestMeasurementRunnerIntegration:
    """Test execution through MeasurementRunner with background worker and live snapshots."""

    def test_runner_execution_with_snapshots(self, tmp_path):
        v = create_virtual_instruments()
        shutdown = Mock()
        profile = AMRSetupProfile.from_instruments(
            dmm=v["dmm"],
            calibrator=v["calibrator"],
            arduino=v["arduino"],
            lockin=v["lockin"],
            field_calibration=10000.0,
            readout_configuration="preserve",
            shutdown_handler=shutdown,
        )
        mt = MagnetoTransport(profile=profile, field=100.0, output_dir=tmp_path)

        runner = MeasurementRunner(mt)
        terminal_q = queue.Queue()
        runner.add_control_listener(
            lambda ev: terminal_q.put(ev) if isinstance(ev, TerminalEvent) else None
        )

        runner.start(save=False)
        event: TerminalEvent = terminal_q.get(timeout=5.0)
        assert runner.join(timeout=5.0)

        assert event.state == RunState.COMPLETED
        assert event.safety.status == SafetyStatus.SAFE
        assert event.data is not None
        assert len(event.data) == 1
        assert list(event.data.columns) == ["angle", "field", "x", "y"]
