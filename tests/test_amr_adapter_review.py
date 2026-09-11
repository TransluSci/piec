"""Regression tests for adapter faults hidden by the initial happy-path suite."""
from unittest.mock import Mock
import pytest

from piec.analysis.field_calibration import FieldCalibration
from piec.measurement.adapters.amr import (
    FieldSource, FieldReader, TransportReadout, OrientationController, AMRSetupProfile,
)


def test_shutdown_failures_reach_profile_and_all_roles_are_attempted():
    source, lockin, motor, shutdown = Mock(), Mock(), Mock(), Mock()
    source.set_output.side_effect = RuntimeError("source failed")
    shutdown.side_effect = RuntimeError("excitation failed")
    motor.halt.side_effect = RuntimeError("motor failed")
    profile = AMRSetupProfile.from_instruments(
        calibrator=source, lockin=lockin, arduino=motor, shutdown_handler=shutdown,
    )
    results = profile.safe_shutdown()
    assert all(value.startswith("error:") for value in results.values())
    source.output.assert_called_once_with(on=False)
    shutdown.assert_called_once_with()
    motor.halt.assert_called_once_with()
    assert profile.field_source.current_output is None
    for instrument in (source, lockin, motor):
        instrument.close.assert_not_called()


@pytest.mark.parametrize("policy", ["preserve", "configure"])
def test_missing_excitation_shutdown_never_reports_safe(policy):
    profile = AMRSetupProfile.from_instruments(
        calibrator=Mock(), lockin=Mock(), arduino=Mock(), readout_configuration=policy,
    )
    assert "unconfirmed" in profile.safe_shutdown()["transport_readout"]


def test_external_source_requires_owner_and_manual_shutdown_is_unconfirmed():
    with pytest.raises(ValueError, match="external_source_owner"):
        TransportReadout(Mock(), excitation_source="external")
    lockin = Mock()
    readout = TransportReadout(lockin, excitation_source="external",
        readout_configuration="configure", external_source_owner="operator at bench")
    readout.configure()
    lockin.configure_reference.assert_called_once_with(source="external")
    lockin.initialize.assert_not_called()
    with pytest.raises(RuntimeError, match="operator at bench"):
        readout.safe_shutdown()


@pytest.mark.parametrize("limits,target", [((0, 1), 1), ((-1, 0), -1)])
def test_quantized_move_cannot_cross_limit(limits, target):
    motor = Mock()
    controller = OrientationController(motor, angle_limits=limits)
    with pytest.raises(ValueError, match="Quantized"):
        controller.move_to_angle(target)
    motor.step.assert_not_called()
    assert controller.current_angle == 0


def test_current_calibration_selects_current_for_command_and_safing():
    instrument = Mock()
    source = FieldSource(instrument, FieldCalibration([(0, 0), (.1, 100)], output_unit="A"))
    source.set_field(50)
    instrument.set_output.assert_called_with(.05, mode="current")
    source.safe_shutdown()
    instrument.set_output.assert_called_with(0, mode="current")
    instrument.output.assert_called_once_with(on=False)


def test_overflowing_calibration_cannot_send_infinite_output():
    instrument = Mock()
    source = FieldSource(instrument, calibration=1e-300)
    with pytest.raises(ValueError):
        source.set_field(1e300)
    instrument.set_output.assert_not_called()


def test_native_modes_do_not_fall_back_to_electrical_methods():
    instrument = Mock(spec=["set_output", "get_voltage"])
    with pytest.raises(AttributeError):
        FieldSource(instrument, calibration="native").set_field(1)
    with pytest.raises(AttributeError):
        FieldReader(instrument, calibration="native").read_field()
    instrument.set_output.assert_not_called()
    instrument.get_voltage.assert_not_called()
    native = Mock(spec=["set_field", "get_field"])
    with pytest.raises(AttributeError):
        FieldSource(native).set_field(1)
    with pytest.raises(AttributeError):
        FieldReader(native).read_field()
    native.set_field.assert_not_called()
    native.get_field.assert_not_called()


def test_field_units_must_match_and_analog_reader_requires_voltage():
    with pytest.raises(ValueError, match="voltage calibration"):
        FieldReader(Mock(), FieldCalibration([(0, 0), (.1, 100)], output_unit="A"))
    with pytest.raises(ValueError, match="field units must match"):
        AMRSetupProfile(FieldSource(Mock(), field_unit="Oe"), FieldReader(Mock(), field_unit="T"),
                        TransportReadout(Mock()), OrientationController(Mock()))


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("setting", ["absolute_tolerance", "relative_tolerance"])
def test_nonfinite_tolerances_are_rejected(setting, invalid):
    with pytest.raises(ValueError):
        FieldReader(Mock(), **{setting: invalid})


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_limits_and_timing_are_rejected(invalid):
    for key in ("field_range", "output_range"):
        with pytest.raises(ValueError):
            FieldSource(Mock(), **{key: (0, invalid)})
    with pytest.raises(ValueError):
        OrientationController(Mock(), angle_limits=(0, invalid))
    with pytest.raises(ValueError):
        OrientationController(Mock(), settling_time=invalid)
    for key in ("amplitude", "frequency", "measure_time", "sample_interval"):
        with pytest.raises(ValueError):
            TransportReadout(Mock(), **{key: invalid})
    with pytest.raises(ValueError):
        TransportReadout(Mock()).average_signals(measure_time=invalid)
