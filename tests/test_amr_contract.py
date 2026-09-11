"""
Contract and regression tests for AMR setup-role adapters and field-angle conversions.

Checkpoint 21: AMR driver and field-angle contract.
Verifies:
- Field-to-voltage and voltage-to-field conversions (linear, positive, zero, negative, finite validation).
- Angle-to-steps and steps-to-angle conversions (positive, negative, fractional, finite validation).
- FieldSource setup adapter (linear calibration, FieldCalibration table, native mode, limits, safing).
- FieldReader setup adapter (linear, table, native, tolerance verification across signs, warn vs raise).
- TransportReadout setup adapter (preserve mode zero writes, configure mode, internal/external excitation, averaging, safing).
- OrientationController setup adapter (step calculation, direction, angle tracking, limits, zeroing).
- AMRSetupProfile composite orchestration (unique instruments, attempt-all safe shutdown).
- Real integration with virtual drivers (VirtualCalibrator, VirtualDMM, VirtualLockin, VirtualStepper).
"""

from __future__ import annotations

import math
import time
from unittest.mock import MagicMock, Mock, call, patch
import warnings

import numpy as np
import pytest

from piec.analysis.field_calibration import FieldCalibration
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
from piec.measurement.amr import (
    convert_angle_to_steps,
    convert_field_to_voltage,
    convert_steps_to_angle,
    convert_voltage_to_field,
)


# ============================================================================
# 1. Conversion Functions Contract
# ============================================================================

class TestConversionContracts:
    """Test field-voltage and angle-step conversion contracts."""

    def test_convert_field_to_voltage_linear(self):
        # Default 10000 Oe/V
        assert convert_field_to_voltage(0.0) == pytest.approx(0.0)
        assert convert_field_to_voltage(100.0) == pytest.approx(0.01)
        assert convert_field_to_voltage(1000.0) == pytest.approx(0.1)
        assert convert_field_to_voltage(-500.0) == pytest.approx(-0.05)
        # Custom calibration factor
        assert convert_field_to_voltage(500.0, voltage_calibration=5000.0) == pytest.approx(0.1)

    def test_convert_field_to_voltage_validation(self):
        with pytest.raises(ValueError, match="field must be a finite number"):
            convert_field_to_voltage(float("nan"))
        with pytest.raises(ValueError, match="field must be a finite number"):
            convert_field_to_voltage(float("inf"))
        with pytest.raises(ValueError, match="voltage_calibration must be a positive finite number"):
            convert_field_to_voltage(100.0, voltage_calibration=0.0)
        with pytest.raises(ValueError, match="voltage_calibration must be a positive finite number"):
            convert_field_to_voltage(100.0, voltage_calibration=-1000.0)
        with pytest.raises(ValueError, match="voltage_calibration must be a positive finite number"):
            convert_field_to_voltage(100.0, voltage_calibration=float("nan"))

    def test_convert_voltage_to_field_linear(self):
        # Default 10000 Oe/V
        assert convert_voltage_to_field(0.0) == pytest.approx(0.0)
        assert convert_voltage_to_field(0.01) == pytest.approx(100.0)
        assert convert_voltage_to_field(0.1) == pytest.approx(1000.0)
        assert convert_voltage_to_field(-0.05) == pytest.approx(-500.0)
        # Custom calibration factor
        assert convert_voltage_to_field(0.1, voltage_calibration=5000.0) == pytest.approx(500.0)

    def test_convert_voltage_to_field_validation(self):
        with pytest.raises(ValueError, match="voltage must be a finite number"):
            convert_voltage_to_field(float("nan"))
        with pytest.raises(ValueError, match="voltage must be a finite number"):
            convert_voltage_to_field(float("inf"))
        with pytest.raises(ValueError, match="voltage_calibration must be a positive finite number"):
            convert_voltage_to_field(0.01, voltage_calibration=0.0)
        with pytest.raises(ValueError, match="voltage_calibration must be a positive finite number"):
            convert_voltage_to_field(0.01, voltage_calibration=-100.0)

    def test_field_voltage_roundtrip(self):
        for field in (-1500.0, -100.0, 0.0, 50.0, 1000.0, 5000.0):
            cal = 10000.0
            v = convert_field_to_voltage(field, cal)
            h_back = convert_voltage_to_field(v, cal)
            assert h_back == pytest.approx(field)

    def test_convert_angle_to_steps_cardinal_and_fractional(self):
        # 200 steps/rev -> 1.8 deg/step
        assert convert_angle_to_steps(0.0) == 0
        assert convert_angle_to_steps(1.8) == 1
        assert convert_angle_to_steps(45.0) == 25
        assert convert_angle_to_steps(90.0) == 50
        assert convert_angle_to_steps(180.0) == 100
        assert convert_angle_to_steps(270.0) == 150
        assert convert_angle_to_steps(360.0) == 200
        assert convert_angle_to_steps(-90.0) == -50
        assert convert_angle_to_steps(-180.0) == -100
        # Custom steps per rev
        assert convert_angle_to_steps(90.0, steps_per_revolution=400) == 100

    def test_convert_angle_to_steps_validation(self):
        with pytest.raises(ValueError, match="angle must be a finite number"):
            convert_angle_to_steps(float("nan"))
        with pytest.raises(ValueError, match="steps_per_revolution must be a positive integer"):
            convert_angle_to_steps(90.0, steps_per_revolution=0)
        with pytest.raises(ValueError, match="steps_per_revolution must be a positive integer"):
            convert_angle_to_steps(90.0, steps_per_revolution=-200)

    def test_convert_steps_to_angle_cardinal_and_fractional(self):
        assert convert_steps_to_angle(0) == pytest.approx(0.0)
        assert convert_steps_to_angle(1) == pytest.approx(1.8)
        assert convert_steps_to_angle(50) == pytest.approx(90.0)
        assert convert_steps_to_angle(100) == pytest.approx(180.0)
        assert convert_steps_to_angle(-50) == pytest.approx(-90.0)
        assert convert_steps_to_angle(100, steps_per_revolution=400) == pytest.approx(90.0)

    def test_convert_steps_to_angle_validation(self):
        with pytest.raises(ValueError, match="steps_per_revolution must be a positive integer"):
            convert_steps_to_angle(50, steps_per_revolution=0)
        with pytest.raises(ValueError, match="steps_per_revolution must be a positive integer"):
            convert_steps_to_angle(50, steps_per_revolution=-10)


# ============================================================================
# 2. FieldSource Adapter Contract
# ============================================================================

class TestFieldSourceAdapter:
    """Test FieldSource setup adapter behaviors, modes, bounds, and safing."""

    def test_field_source_init_validation(self):
        with pytest.raises(ValueError, match="instrument must not be None"):
            FieldSource(None)

        mock_inst = Mock()
        with pytest.raises(ValueError, match="calibration factor must be a positive finite float"):
            FieldSource(mock_inst, calibration=-100.0)
        with pytest.raises(ValueError, match="calibration factor must be a positive finite float"):
            FieldSource(mock_inst, calibration=0.0)
        with pytest.raises(TypeError, match="calibration must be a positive float"):
            FieldSource(mock_inst, calibration=[1, 2, 3])

        with pytest.raises(ValueError, match="field_range must be"):
            FieldSource(mock_inst, field_range=(500, -500))
        with pytest.raises(ValueError, match="output_range must be"):
            FieldSource(mock_inst, output_range=(10, 0))

    def test_field_source_linear_mode(self):
        inst = Mock()
        source = FieldSource(inst, calibration=10000.0)
        assert source.mode == "linear"
        assert source.field_unit == "Oe"
        assert source.output_unit == "V"

        # Set positive field
        res = source.set_field(500.0)
        assert res == 500.0
        assert source.commanded_field == 500.0
        assert source.current_output == pytest.approx(0.05)
        inst.set_output.assert_called_once_with(pytest.approx(0.05), mode="voltage")

        # Set negative field
        inst.reset_mock()
        source.set_field(-200.0)
        assert source.commanded_field == -200.0
        assert source.current_output == pytest.approx(-0.02)
        inst.set_output.assert_called_once_with(pytest.approx(-0.02), mode="voltage")

        # Set zero field
        inst.reset_mock()
        source.set_field(0.0)
        assert source.commanded_field == 0.0
        assert source.current_output == pytest.approx(0.0)
        inst.set_output.assert_called_once_with(0.0, mode="voltage")

    def test_field_source_table_mode(self):
        cal = FieldCalibration([(-0.1, -1000.0), (0.0, 0.0), (0.1, 1000.0)], output_unit="V", field_unit="Oe")
        inst = Mock()
        source = FieldSource(inst, calibration=cal)
        assert source.mode == "table"

        source.set_field(500.0)
        assert source.commanded_field == 500.0
        assert source.current_output == pytest.approx(0.05)
        inst.set_output.assert_called_with(pytest.approx(0.05), mode="voltage")

        # Outside calibration range raises ValueError
        with pytest.raises(ValueError, match="outside the calibrated range"):
            source.set_field(1500.0)

    def test_field_source_native_mode(self):
        inst = Mock()
        source = FieldSource(inst, calibration="native")
        assert source.mode == "native"

        source.set_field(300.0)
        assert source.commanded_field == 300.0
        assert source.current_output == 300.0
        # If instrument has set_field, it is called
        inst.set_field.assert_called_once_with(300.0)

    def test_field_source_limits_enforcement(self):
        inst = Mock()
        source = FieldSource(
            inst,
            calibration=10000.0,
            field_range=(-1000.0, 1000.0),
            output_range=(-0.1, 0.1),
        )

        # In range works
        source.set_field(1000.0)
        assert source.commanded_field == 1000.0

        # Field exceeds field_range
        with pytest.raises(ValueError, match="outside field_range"):
            source.set_field(1100.0)
        with pytest.raises(ValueError, match="outside field_range"):
            source.set_field(-1100.0)

        # Output exceeds output_range (e.g. if field_range were larger than output_range)
        source.field_range = (-2000.0, 2000.0)
        with pytest.raises(ValueError, match="outside output_range"):
            source.set_field(1500.0)  # 0.15 V > 0.1 V

    def test_field_source_safe_shutdown(self):
        inst = Mock()
        source = FieldSource(inst, calibration=10000.0)
        source.set_field(500.0)

        source.safe_shutdown()
        assert source.commanded_field is None
        assert source.current_output == 0.0
        inst.set_output.assert_called_with(0.0, mode="voltage")
        inst.output.assert_called_once_with(on=False)
        # Connection NOT closed
        assert not hasattr(inst, "close") or inst.close.call_count == 0


# ============================================================================
# 3. FieldReader Adapter Contract
# ============================================================================

class TestFieldReaderAdapter:
    """Test FieldReader sensor acquisition, tolerance verification across signs, and policy."""

    def test_field_reader_init_validation(self):
        with pytest.raises(ValueError, match="instrument must not be None"):
            FieldReader(None)

        inst = Mock()
        with pytest.raises(ValueError, match="absolute_tolerance must be finite"):
            FieldReader(inst, absolute_tolerance=-1.0)
        with pytest.raises(ValueError, match="relative_tolerance must be finite"):
            FieldReader(inst, relative_tolerance=-0.1)
        with pytest.raises(ValueError, match="mismatch_policy must be"):
            FieldReader(inst, mismatch_policy="ignore")

    def test_field_reader_linear_read(self):
        inst = Mock()
        inst.get_voltage.return_value = 0.05  # 0.05 V * 10000 = 500 Oe
        reader = FieldReader(inst, calibration=10000.0)

        field, t = reader.read_field()
        assert field == pytest.approx(500.0)
        assert t > 0
        assert reader.last_measured_field == pytest.approx(500.0)

    def test_field_reader_non_finite_rejected(self):
        inst = Mock()
        reader = FieldReader(inst)

        inst.get_voltage.return_value = float("nan")
        with pytest.raises(ValueError, match="non-finite"):
            reader.read_field()

        inst.get_voltage.return_value = float("inf")
        with pytest.raises(ValueError, match="non-finite"):
            reader.read_field()

    def test_field_reader_verify_tolerance_positive_zero_negative(self):
        inst = Mock()
        reader = FieldReader(
            inst,
            absolute_tolerance=2.0,
            relative_tolerance=0.05,  # 5%
            mismatch_policy="raise",
        )

        # Positive target 100 Oe: tol = 2 + 0.05 * 100 = 7 Oe
        assert reader.verify_field(100.0, 105.0) is True
        assert reader.verify_field(100.0, 94.0) is True
        with pytest.raises(RuntimeError, match="Field mismatch"):
            reader.verify_field(100.0, 108.0)

        # Zero target: tol = 2 + 0 = 2 Oe
        assert reader.verify_field(0.0, 1.5) is True
        assert reader.verify_field(0.0, -1.8) is True
        with pytest.raises(RuntimeError, match="Field mismatch"):
            reader.verify_field(0.0, 2.5)

        # Negative target -200 Oe: tol = 2 + 0.05 * 200 = 12 Oe
        assert reader.verify_field(-200.0, -208.0) is True
        assert reader.verify_field(-200.0, -192.0) is True
        with pytest.raises(RuntimeError, match="Field mismatch"):
            reader.verify_field(-200.0, -215.0)

    def test_field_reader_warn_policy(self):
        inst = Mock()
        reader = FieldReader(
            inst,
            absolute_tolerance=1.0,
            relative_tolerance=0.01,
            mismatch_policy="warn",
        )

        # Target 100, actual 120 -> difference 20 > tol (2)
        with pytest.warns(UserWarning, match="Field mismatch"):
            res = reader.verify_field(100.0, 120.0)
            assert res is False


# ============================================================================
# 4. TransportReadout Adapter Contract
# ============================================================================

class TestTransportReadoutAdapter:
    """Test TransportReadout preserve-vs-configure modes, acquisition, and safing."""

    def test_transport_readout_preserve_mode_sends_zero_writes(self):
        """
        Confirmed lab workflow: lockin settings are chosen manually by operator.
        Default readout_configuration='preserve' sends NO initialize, reset, or writes!
        """
        lockin = Mock()
        readout = TransportReadout(lockin, readout_configuration="preserve")
        assert readout.readout_configuration == "preserve"

        readout.configure()
        # Strictly no calls to initialize, configure_reference, configure_input, configure_gain_filters
        assert lockin.initialize.call_count == 0
        assert lockin.reset.call_count == 0
        assert lockin.configure_reference.call_count == 0
        assert lockin.configure_input.call_count == 0
        assert lockin.configure_gain_filters.call_count == 0

    def test_transport_readout_configure_mode_internal(self):
        lockin = Mock()
        readout = TransportReadout(
            lockin,
            readout_configuration="configure",
            excitation_source="internal",
            amplitude=0.5,
            frequency=13.0,
            sensitivity="100uv/pa",
            input_configuration="a-b",
        )

        readout.configure()
        lockin.initialize.assert_not_called()
        lockin.configure_reference.assert_called_once_with(source="internal", voltage=0.5, frequency=13.0)
        lockin.configure_input.assert_called_once_with(input_configuration="a-b")
        lockin.configure_gain_filters.assert_called_once_with(sensitivity="100uv/pa")

    def test_transport_readout_configure_mode_external(self):
        lockin = Mock()
        readout = TransportReadout(
            lockin,
            readout_configuration="configure",
            excitation_source="external",
            external_source_owner="bench operator",
            sensitivity="200uv/pa",
        )

        readout.configure()
        # External excitation does NOT send internal oscillator reference settings
        lockin.configure_reference.assert_called_once_with(source="external")
        lockin.configure_input.assert_called_once()
        lockin.configure_gain_filters.assert_called_once_with(sensitivity="200uv/pa")

    def test_transport_readout_read_signals(self):
        lockin = Mock()
        lockin.get_X_Y.return_value = (1.23e-5, -4.56e-6)
        readout = TransportReadout(lockin)

        sig = readout.read_signals()
        assert sig == {"x": pytest.approx(1.23e-5), "y": pytest.approx(-4.56e-6)}

    def test_transport_readout_read_signals_rejects_non_finite(self):
        lockin = Mock()
        readout = TransportReadout(lockin)

        lockin.get_X_Y.return_value = (float("nan"), 1.0)
        with pytest.raises(ValueError, match="non-finite"):
            readout.read_signals()

    def test_transport_readout_signal_averaging(self):
        lockin = Mock()
        lockin.get_X_Y.side_effect = [
            (1.0e-5, 2.0e-6),
            (1.2e-5, 2.2e-6),
            (1.4e-5, 2.4e-6),
        ]
        readout = TransportReadout(lockin, measure_time=0.02, sample_interval=0.01)

        simulated_time = [100.0]

        def mock_monotonic():
            return simulated_time[0]

        def mock_sleep(dt):
            simulated_time[0] += dt

        with patch("time.monotonic", side_effect=mock_monotonic), patch("time.sleep", side_effect=mock_sleep):
            avg = readout.average_signals()

        assert avg["x"] > 1.0e-5
        assert avg["y"] > 2.0e-6

    def test_transport_readout_safe_shutdown(self):
        lockin = Mock()
        # Safing is independent of settings preservation and propagates failure.
        shutdown = Mock()
        for policy in ("preserve", "configure"):
            readout = TransportReadout(lockin, readout_configuration=policy, shutdown_handler=shutdown)
            if policy == "preserve":
                readout.configure()
            readout.safe_shutdown()
        assert shutdown.call_count == 2
        lockin.configure_reference.assert_not_called()
        shutdown.side_effect = RuntimeError("relay failure")
        with pytest.raises(RuntimeError, match="relay failure"):
            readout.safe_shutdown()


# ============================================================================
# 5. OrientationController Adapter Contract
# ============================================================================

class TestOrientationControllerAdapter:
    """Test OrientationController angle tracking, step calculation, limits, and zeroing."""

    def test_orientation_controller_init_validation(self):
        with pytest.raises(ValueError, match="instrument must not be None"):
            OrientationController(None)

        mock_inst = Mock()
        with pytest.raises(ValueError, match="steps_per_revolution must be a positive integer"):
            OrientationController(mock_inst, steps_per_revolution=0)
        with pytest.raises(ValueError, match="angle_limits must be"):
            OrientationController(mock_inst, angle_limits=(180.0, 0.0))

    def test_orientation_controller_movement_tracking(self):
        stepper = Mock()
        ctrl = OrientationController(stepper, steps_per_revolution=200)
        assert ctrl.current_angle == 0.0

        # Move to 90 deg -> +50 steps, CW (direction=1)
        angle = ctrl.move_to_angle(90.0)
        assert angle == pytest.approx(90.0)
        assert ctrl.current_angle == pytest.approx(90.0)
        stepper.step.assert_called_once_with(50, 1)

        # Move to 45 deg -> -25 steps, CCW (direction=0)
        stepper.reset_mock()
        angle = ctrl.move_to_angle(45.0)
        assert angle == pytest.approx(45.0)
        assert ctrl.current_angle == pytest.approx(45.0)
        stepper.step.assert_called_once_with(25, 0)

        # Move to 45 deg -> 0 delta, no step call
        stepper.reset_mock()
        angle = ctrl.move_to_angle(45.0)
        assert angle == pytest.approx(45.0)
        assert stepper.step.call_count == 0

    def test_orientation_controller_relative_movement(self):
        stepper = Mock()
        ctrl = OrientationController(stepper, steps_per_revolution=200)

        ctrl.step_relative(18.0)
        assert ctrl.current_angle == pytest.approx(18.0)
        stepper.step.assert_called_with(10, 1)

    def test_orientation_controller_angle_limits(self):
        stepper = Mock()
        ctrl = OrientationController(stepper, angle_limits=(0.0, 180.0))

        # In limits
        ctrl.move_to_angle(180.0)
        assert ctrl.current_angle == pytest.approx(180.0)

        # Outside limits
        with pytest.raises(ValueError, match="outside angle_limits"):
            ctrl.move_to_angle(190.0)
        with pytest.raises(ValueError, match="outside angle_limits"):
            ctrl.move_to_angle(-10.0)

    def test_orientation_controller_set_zero(self):
        stepper = Mock()
        ctrl = OrientationController(stepper)
        ctrl.move_to_angle(90.0)
        assert ctrl.current_angle == pytest.approx(90.0)

        ctrl.set_zero(0.0)
        assert ctrl.current_angle == pytest.approx(0.0)

    def test_orientation_controller_safe_shutdown(self):
        stepper = Mock()
        ctrl = OrientationController(stepper)
        ctrl.safe_shutdown()
        # Calls halt() or stop() if available
        stepper.halt.assert_called_once()


# ============================================================================
# 6. AMRSetupProfile Composite Contract
# ============================================================================

class TestAMRSetupProfileContract:
    """Test AMRSetupProfile composition, factory, unique instruments, and attempt-all safing."""

    def test_amr_setup_profile_from_instruments(self):
        dmm = Mock()
        calibrator = Mock()
        stepper = Mock()
        lockin = Mock()

        profile = AMRSetupProfile.from_instruments(
            dmm=dmm,
            calibrator=calibrator,
            arduino=stepper,
            lockin=lockin,
            field_calibration=10000.0,
            reader_calibration=10000.0,
            readout_configuration="preserve",
        )

        assert isinstance(profile.field_source, FieldSource)
        assert isinstance(profile.field_reader, FieldReader)
        assert isinstance(profile.transport_readout, TransportReadout)
        assert isinstance(profile.orientation_controller, OrientationController)
        assert profile.transport_readout.readout_configuration == "preserve"

        # Unique instruments list contains all 4 distinct objects
        unique = profile.unique_instruments()
        assert len(unique) == 4
        assert calibrator in unique
        assert dmm in unique
        assert stepper in unique
        assert lockin in unique

    def test_amr_setup_profile_from_instruments_without_reader(self):
        calibrator = Mock()
        stepper = Mock()
        lockin = Mock()

        profile = AMRSetupProfile.from_instruments(
            dmm=None,
            calibrator=calibrator,
            arduino=stepper,
            lockin=lockin,
            reader_calibration=None,
        )

        assert profile.field_reader is None
        assert len(profile.unique_instruments()) == 3

    def test_amr_setup_profile_attempt_all_safe_shutdown(self):
        calibrator = Mock()
        calibrator.set_output.side_effect = RuntimeError("Calibrator comm error")
        lockin = Mock()
        stepper = Mock()

        profile = AMRSetupProfile.from_instruments(
            calibrator=calibrator,
            arduino=stepper,
            lockin=lockin,
            readout_configuration="configure",
            shutdown_handler=Mock(),
        )

        # Safing attempts all roles even if calibrator raises error
        results = profile.safe_shutdown()
        assert "error" in results["field_source"]
        assert results["transport_readout"] == "safe"
        assert results["orientation_controller"] == "safe"


# ============================================================================
# 7. Virtual Instrument Integration
# ============================================================================

class TestVirtualDriverIntegration:
    """Test AMR setup adapters operating directly on concrete virtual drivers."""

    def test_virtual_drivers_full_workflow(self):
        cal = VirtualCalibrator()
        dmm = VirtualDMM()
        stepper = VirtualStepper()
        lockin = VirtualLockin()

        profile = AMRSetupProfile.from_instruments(
            dmm=dmm,
            calibrator=cal,
            arduino=stepper,
            lockin=lockin,
            field_calibration=10000.0,
            reader_calibration=10000.0,
            readout_configuration="preserve",
        )

        # 1. Set field via FieldSource
        profile.field_source.set_field(500.0)
        assert profile.field_source.commanded_field == 500.0
        assert profile.field_source.current_output == pytest.approx(0.05)

        # DMM linked to sample reads 0.05 V -> 500 Oe
        dmm.voltage = 0.05
        field_meas, _ = profile.field_reader.read_field()
        assert field_meas == pytest.approx(500.0)
        assert profile.field_reader.verify_field(500.0, field_meas) is True

        # 2. Rotate stage via OrientationController
        target_deg = 45.0
        actual_deg = profile.orientation_controller.move_to_angle(target_deg)
        assert actual_deg == pytest.approx(45.0)

        # 3. Read signals via TransportReadout
        profile.transport_readout.configure()  # Preserve mode: no writes
        signals = profile.transport_readout.read_signals()
        assert "x" in signals and "y" in signals
        assert math.isfinite(signals["x"])
        assert math.isfinite(signals["y"])

        # 4. Safe shutdown
        results = profile.safe_shutdown()
        assert "unconfirmed" in results["transport_readout"]
        assert profile.field_source.commanded_field is None
        assert profile.field_source.current_output == 0.0
        # VirtualCalibrator output disabled
        assert getattr(cal, "_output_enabled", None) is False
