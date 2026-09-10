"""Direct-output calibration, material memory, and the source/DMM workflow."""

import json
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from piec.analysis.field_calibration import FieldCalibration
from piec.analysis.utilities import standard_csv_to_metadata_and_data
from piec.drivers.dmm.dmm import DMM
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.measurement import HardwareSafetyError
from piec.measurement.moke import MokeMeasurement
from piec.simulation.hysteretic_magnetic_material import HystereticMagneticMaterial


def calibration():
    return FieldCalibration([(-5, -500), (0, 0), (1, 100), (5, 500)], name="example")


def measurement(**kwargs):
    source = VirtualSourcemeter()
    material = HystereticMagneticMaterial()
    detector = Mock(spec=DMM)
    detector.idn.return_value = "test voltage reader"

    # Test-only wiring. Neither instrument nor measurement knows about MOKE
    # simulation. Keep the simulated plant calibration separate from the input
    # calibration under test so a measurement-conversion bug cannot cancel out.
    def read_detector():
        state = source.get_state()
        command = state["source_voltage"] if state["output_on"] else 0.0
        return 0.5 + 0.02 * material.apply_field(100.0 * command)

    detector.get_voltage.side_effect = read_detector
    options = dict(
        calibration=calibration(), output_values=[-5, 0, 5, 0, -5],
        compliance=0.01, max_output_step=1.0, dwell_time=0,
        ramp_delay=0, n_cycles=2,
    )
    options.update(kwargs)
    return MokeMeasurement(source, detector, **options)


def test_calibration_uses_direct_output_without_another_gain():
    curve = calibration()
    assert curve.field_at_output(5) == 500
    assert curve.field_at_output(0.5) == 50
    assert curve.output_at_field(500) == 5
    assert curve.output_at_field([-250, 100]) == pytest.approx([-2.5, 1])


def test_nonlinear_and_reversed_calibration():
    curve = FieldCalibration([(5, -600), (0, 0), (1, -80)])
    assert curve.field_at_output(3) == -340
    assert curve.output_at_field(-340) == 3


@pytest.mark.parametrize("points", [[], [(1, 100)], [(1, 100), (1, 110)], [(0, 0), (1, np.nan)]])
def test_invalid_calibration_points_are_rejected(points):
    with pytest.raises(ValueError):
        FieldCalibration(points)


def test_no_extrapolation_and_no_ambiguous_inverse():
    with pytest.raises(ValueError, match="outside"):
        calibration().field_at_output(5.01)
    with pytest.raises(ValueError, match="outside"):
        calibration().output_at_field(501)
    curve = FieldCalibration([(0, 0), (1, 2), (2, 1)])
    assert curve.field_at_output(1.5) == 1.5
    with pytest.raises(ValueError, match="monotonic"):
        curve.output_at_field(1)


def test_calibration_csv_round_trip_and_no_overwrite(tmp_path):
    path = tmp_path / "calibration.csv"
    curve = calibration()
    curve.save_csv(path)
    loaded = FieldCalibration.load_csv(path)
    assert loaded.to_dict() == curve.to_dict()
    with pytest.raises(FileExistsError):
        curve.save_csv(path)


def test_calibration_points_are_not_mutable_through_accessor():
    curve = calibration()
    points = curve.points
    points[:, 1] = 999
    assert curve.field_at_output(5) == 500


def test_material_retains_opposite_remanence_at_the_same_field():
    material = HystereticMagneticMaterial()
    assert material.response([-500, 0, 500, 0, -500]).tolist() == [-1, -1, 1, 1, -1]
    assert material.apply_field(0) == -1


def test_material_repeated_read_and_partial_reversal_preserve_memory():
    material = HystereticMagneticMaterial()
    partial = material.apply_field(50)
    assert -1 < partial < 1
    assert material.apply_field(0) == partial
    assert material.apply_field(0) == partial
    material.reset(polarity=1)
    assert material.apply_field(0) == 1


def test_constructor_does_not_enable_or_measure_instruments():
    run = measurement()
    assert not run.sourcemeter.state["output_on"]
    run.dmm.get_voltage.assert_not_called()
    assert run.data is None
    assert run.filename is None


def test_single_measurement_uses_voltage_source_and_dmm_with_raw_cycles():
    run = measurement()
    snapshots = []
    data = run.run_experiment(on_update=snapshots.append, save=False)
    assert len(data) == 10
    assert len(snapshots) == 10
    assert run.completed_cycles == 2
    assert data["source_output"].tolist() == [-5, 0, 5, 0, -5] * 2
    assert data["field_calibrated"].tolist() == [-500, 0, 500, 0, -500] * 2
    assert data["detector_voltage"].tolist() == pytest.approx([0.48, 0.48, 0.52, 0.52, 0.48] * 2)
    assert run.cycle_average["detector_voltage"].tolist() == pytest.approx([0.48, 0.48, 0.52, 0.52, 0.48])
    assert run.cycle_average["cycles_averaged"].tolist() == [2] * 5
    run.dmm.set_sense_function.assert_called_once_with(sense_func="VOLT")
    run.dmm.set_measurement_coupling.assert_called_once_with(coupling="DC")
    assert not run.sourcemeter.state["output_on"]
    assert run.sourcemeter.state["source_voltage"] == 0
    assert len(run.run_records) == 1
    assert "field_measured" not in data


def test_current_output_calibration_selects_current_source():
    run = measurement(
        calibration=FieldCalibration([(-0.5, -500), (0.5, 500)], output_unit="A"),
        output_values=[-0.5, 0.5, -0.5], compliance=10,
    )
    run.dmm.get_voltage.side_effect = lambda: 0.123
    run.run_experiment(save=False)
    assert run.sourcemeter.state["source_func"] == "CURR"
    assert run.sourcemeter.state["voltage_compliance"] == 10
    assert run.data["field_calibrated"].tolist() == [-500, 500, -500] * 2
    assert run.sourcemeter.state["source_current"] == 0


def test_partial_cycle_on_stop_is_not_averaged():
    run = measurement()
    def stop_after_seven(snapshot):
        if len(snapshot.raw) == 7:
            run.request_stop()
    run.run_experiment(on_update=stop_after_seven, save=False)
    assert len(run.data) == 7
    assert run.completed_cycles == 1
    assert len(run.last_cycle) == 5
    assert run.cycle_average["cycles_averaged"].tolist() == [1] * 5
    assert not run.sourcemeter.state["output_on"]


def test_failure_preserves_partial_data_and_turns_source_off():
    run = measurement()
    run.dmm.get_voltage.side_effect = [0.5, RuntimeError("read failed")]
    with pytest.raises(RuntimeError, match="read failed"):
        run.run_experiment(save=False)
    assert len(run.data) == 1
    assert not run.sourcemeter.state["output_on"]
    assert run.sourcemeter.state["source_voltage"] == 0


def test_configuration_failure_does_not_leave_output_enabled():
    run = measurement()
    run.dmm.set_sense_function.side_effect = RuntimeError("configure failed")
    with pytest.raises(RuntimeError, match="configure failed"):
        run.run_experiment(save=False)
    assert not run.sourcemeter.state["output_on"]


def test_setup_can_supply_its_own_shutdown_procedure():
    shutdown = Mock(side_effect=lambda source: source.output(channel=1, on=False))
    run = measurement(shutdown_handler=shutdown)
    run.run_experiment(save=False)
    shutdown.assert_called_once_with(run.sourcemeter)


def test_saved_data_includes_original_calibration_and_units(tmp_path):
    run = measurement(output_dir=str(tmp_path))
    run.run_experiment()
    metadata, data = standard_csv_to_metadata_and_data(run.filename)
    assert json.loads(metadata.loc[0, "calibration"]) == calibration().to_dict()
    assert metadata.loc[0, "output_unit"] == "V"
    assert metadata.loc[0, "field_unit"] == "Oe"
    assert metadata.loc[0, "measurement_schema"] == "moke"
    assert int(metadata.loc[0, "measurement_schema_version"]) == 1
    assert json.loads(metadata.loc[0, "column_units_json"]) == run.column_units
    assert bool(metadata.loc[0, "processed"])
    pd.testing.assert_frame_equal(data, run.data, check_dtype=False)


@pytest.mark.parametrize("options", [
    {"output_values": [-6, 6, -6]}, {"output_values": [0, 1, 2]},
    {"n_cycles": 1.5}, {"max_output_step": 0}, {"dwell_time": -1},
])
def test_invalid_run_settings_fail_before_output(options):
    with pytest.raises(ValueError):
        measurement(**options)


def test_manual_field_setting_uses_calibration_inverse():
    run = measurement()
    run.configure_instruments()
    try:
        run.set_field(250)
        assert run.sourcemeter.state["source_voltage"] == 2.5
        assert not run.sourcemeter.state["output_on"]
    finally:
        run.safe_shutdown()


def test_csv_loader_accepts_manual_table_without_name(tmp_path):
    path = tmp_path / "manual.csv"
    pd.DataFrame({
        "source_output": [0, 1, 5], "field": [0, 98, 505],
        "output_unit": ["V"] * 3, "field_unit": ["Oe"] * 3,
    }).to_csv(path, index=False)
    curve = FieldCalibration.load_csv(path)
    assert curve.field_at_output(1) == 98
    assert curve.name == ""


def test_csv_loader_rejects_mixed_units(tmp_path):
    path = tmp_path / "mixed.csv"
    pd.DataFrame({
        "source_output": [0, 1], "field": [0, 100],
        "output_unit": ["V", "A"], "field_unit": ["Oe", "Oe"],
    }).to_csv(path, index=False)
    with pytest.raises(ValueError, match="consistent output_unit"):
        FieldCalibration.load_csv(path)


def test_material_history_can_be_supplied_in_chunks():
    whole = HystereticMagneticMaterial()
    chunked = HystereticMagneticMaterial()
    fields = np.r_[np.linspace(-100, 100, 51), np.linspace(100, -100, 51)]
    assert np.r_[chunked.response(fields[:40]), chunked.response(fields[40:])] == pytest.approx(
        whole.response(fields)
    )


def test_source_limits_are_checked_even_when_driver_checking_is_disabled():
    with pytest.raises(ValueError, match="compliance exceeds"):
        measurement(compliance=2)
    with pytest.raises(ValueError, match="driver's voltage limit"):
        measurement(
            calibration=FieldCalibration([(-300, -3000), (300, 3000)]),
            output_values=[-300, 300, -300],
        )


def test_source_ramp_increments_and_shutdown_are_bounded():
    run = measurement(max_output_step=0.25)
    original = run.sourcemeter.set_source_voltage
    programmed = [0.0]

    def record(channel=1, voltage=None):
        result = original(channel=channel, voltage=voltage)
        programmed.append(float(voltage))
        return result

    run.sourcemeter.set_source_voltage = record
    run.run_experiment(save=False)
    assert np.max(np.abs(np.diff(programmed))) <= 0.25
    assert programmed[-1] == 0


def test_shutdown_still_disables_output_if_zero_ramp_fails():
    run = measurement()
    run.configure_instruments()
    run.sourcemeter.output(channel=1, on=True)
    run.set_output(-5)
    run.sourcemeter.set_source_voltage = Mock(side_effect=RuntimeError("ramp failed"))
    with pytest.raises(HardwareSafetyError, match="ramp failed"):
        run.safe_shutdown()
    assert not run.sourcemeter.state["output_on"]


def test_snapshot_mutation_does_not_change_saved_measurement():
    run = measurement(raw_window_points=2)
    run.run_experiment(save=False)
    snapshot = run.snapshot()
    assert len(snapshot.raw) == 2
    view = snapshot.last_cycle
    view.loc[:, "detector_voltage"] = 999
    assert run.last_cycle["detector_voltage"].max() < 1


def test_without_gaussmeter_plot_axis_remains_calibrated_field():
    run = measurement()
    run.run_experiment(save=False)
    assert run.field_column == "field_calibrated"
    assert run.snapshot().field_column == run.field_column
    assert run.measured_field_column not in run.data
    assert run.metadata.loc[0, "plot_field_column"] == run.field_column


def test_gaussmeter_selects_measured_axis_and_preserves_calibration(tmp_path):
    fields = [-490, 11, 512, 7, -501, -488, 15, 514, 9, -499]
    reader = Mock(side_effect=fields)
    run = measurement(
        field_reader=reader, field_reader_unit="Oe",
        field_reader_name="test gaussmeter", output_dir=str(tmp_path),
    )
    reader.assert_not_called()  # No field acquisition in constructor.
    snapshots = []
    run.run_experiment(on_update=snapshots.append)
    assert reader.call_count == 10
    assert run.field_column == "field_measured"
    assert run.data[run.field_column].tolist() == fields
    assert run.data[run.calibrated_field_column].tolist() == [-500, 0, 500, 0, -500] * 2
    assert run.data[run.output_column].tolist() == [-5, 0, 5, 0, -5] * 2
    assert run.last_cycle[run.field_column].tolist() == fields[-5:]
    assert run.cycle_average[run.field_column].tolist() == [-489, 13, 513, 8, -500]
    assert (run.data["field_time"] >= run.data["time"]).all()
    for snapshot in snapshots:
        assert snapshot.field_column == run.field_column
        for frame in (snapshot.raw, snapshot.last_cycle, snapshot.cycle_average):
            if not frame.empty:
                assert snapshot.field_column in frame
    metadata, data = standard_csv_to_metadata_and_data(run.filename)
    assert metadata.loc[0, "field_basis"] == "measured field"
    assert metadata.loc[0, "field_reader"] == "test gaussmeter"
    assert metadata.loc[0, "field_reader_unit"] == "Oe"
    assert metadata.loc[0, "plot_field_column"] == run.field_column
    assert json.loads(metadata.loc[0, "calibration"]) == calibration().to_dict()
    assert data[run.field_column].tolist() == fields


def test_measured_field_average_excludes_partial_cycles():
    reader = Mock(side_effect=[-490, 10, 510, 15, -485, -499, 1])
    run = measurement(field_reader=reader, field_reader_unit="Oe")
    def stop(snapshot):
        if len(snapshot.raw) == 7:
            run.request_stop()
    run.run_experiment(on_update=stop, save=False)
    assert run.completed_cycles == 1
    assert run.cycle_average[run.field_column].tolist() == [-490, 10, 510, 15, -485]
    assert len(run.data) == 7


def test_measured_field_average_uses_requested_window():
    reader = Mock(side_effect=list(range(10)))
    run = measurement(field_reader=reader, field_reader_unit="Oe", average_cycles=1)
    run.run_experiment(save=False)
    assert run.cycle_average[run.field_column].tolist() == list(range(5, 10))


@pytest.mark.parametrize("options", [
    {"field_reader": 123, "field_reader_unit": "Oe"},
    {"field_reader": lambda: 0},
    {"field_reader": lambda: 0, "field_reader_unit": "T"},
    {"field_reader_unit": "Oe"},
    {"field_reader_name": "not connected"},
])
def test_invalid_gaussmeter_configuration_is_rejected(options):
    with pytest.raises((TypeError, ValueError)):
        measurement(**options)


@pytest.mark.parametrize("value", [np.nan, np.inf, None, True, [1, 2], "invalid"])
def test_invalid_field_reading_stops_without_silent_fallback(value):
    run = measurement(field_reader=lambda: value, field_reader_unit="Oe")
    with pytest.raises(ValueError, match="field"):
        run.run_experiment(save=False)
    assert run.data.empty
    assert not run.sourcemeter.state["output_on"]
    assert run.sourcemeter.state["source_voltage"] == 0


def test_gaussmeter_failure_preserves_paired_samples_and_shuts_down():
    reader = Mock(side_effect=[-495, TimeoutError("gaussmeter timed out")])
    run = measurement(field_reader=reader, field_reader_unit="Oe")
    with pytest.raises(TimeoutError, match="gaussmeter timed out"):
        run.run_experiment(save=False)
    assert len(run.data) == 1
    assert run.data[run.field_column].tolist() == [-495]
    assert not run.sourcemeter.state["output_on"]
    assert run.sourcemeter.state["source_voltage"] == 0


def test_field_reader_can_use_other_explicit_matching_units():
    curve = FieldCalibration([(-5, -0.05), (5, 0.05)], field_unit="T")
    run = measurement(calibration=curve, field_reader=lambda: 0.012, field_reader_unit="T")
    run.run_experiment(save=False)
    assert run.field_column == "field_measured"
    assert run.data[run.field_column].tolist() == [0.012] * 10
    assert run.column_units["field_measured"] == "T"
    assert run.column_units["field_calibrated"] == "T"
