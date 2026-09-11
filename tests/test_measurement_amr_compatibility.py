"""
Characterization and regression tests for MagnetoTransport and AMR legacy public behavior.

Stage 0 Checkpoint 2d: AMR scientific fixtures, golden regression, and consumer inventory.
"""

from collections.abc import Sequence
import json
import math
from pathlib import Path
import tempfile
from unittest.mock import Mock, call, patch

import numpy as np
import pandas as pd
import pytest

from piec.analysis.utilities import metadata_and_data_to_csv, standard_csv_to_metadata_and_data
from piec.measurement.amr import (
    AMR,
    MagnetoTransport,
    convert_angle_to_steps,
    convert_field_to_voltage,
    convert_steps_to_angle,
)
from tests.fixtures.measurement_compatibility import (
    assert_data_columns_match,
    assert_golden_csv_matches,
    assert_numerical_data_matches_reference,
    assert_piec_csv_layout,
    load_manifest,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "measurement_compatibility"
AMR_GOLDEN_PATH = FIXTURES_DIR / "amr_golden.csv"
AMR_OBSERVED_PATH = FIXTURES_DIR / "amr_legacy_observed.csv"
# 0.1 nV: far below the fixture's 2 uV X and 0.2 uV Y contrast.
AMR_SIGNAL_ATOL = 1e-10
REPO_ROOT = Path(__file__).parent.parent


def create_mock_amr_instruments(
    resistance_baseline: float = 100.0,
    amr_delta: float = 2.0,
    field: float = 100.0,
    voltage_calibration: float = 10000.0,
):
    """
    Create a coordinated set of mock instruments simulating the AMR hardware setup.

    - DMM: Reads hall sensor voltage (field / voltage_calibration).
    - Calibrator: Sets output voltage to magnet power supply.
    - Arduino: Stepper motor with tracking of current mechanical angle.
    - Lockin: Measures in-phase X following cos^2(theta) AMR and quadrature Y.
    """
    current_angle = [0.0]

    def mock_step(steps: int, direction: int):
        delta = steps * 360.0 / 200.0
        if direction == 1:
            current_angle[0] += delta
        else:
            current_angle[0] -= delta

    def mock_get_xy():
        theta_rad = math.radians(current_angle[0])
        x = (resistance_baseline + amr_delta * (math.cos(theta_rad) ** 2)) * 1e-6
        y = 0.1 * x
        return x, y

    dmm = Mock()
    dmm.idn.return_value = "TEST_DMM"
    dmm.get_voltage.return_value = field / voltage_calibration

    calibrator = Mock()
    calibrator.idn.return_value = "TEST_CALIBRATOR"
    calibrator.__str__ = lambda self: "TEST_CALIBRATOR"

    arduino = Mock()
    arduino.idn.return_value = "TEST_STEPPER"
    arduino.step.side_effect = mock_step

    lockin = Mock()
    lockin.idn.return_value = "TEST_LOCKIN"
    lockin.get_X_Y.side_effect = mock_get_xy

    return {
        "dmm": dmm,
        "calibrator": calibrator,
        "arduino": arduino,
        "lockin": lockin,
        "current_angle": current_angle,
    }


from piec.measurement.magneto_transport import _LegacyMagnetoTransport


class TestMagnetoTransportCompatibility:
    """Characterize legacy MagnetoTransport base class behavior and hardware interactions."""

    def test_magneto_transport_constructor_and_attributes(self, tmp_path):
        mocks = create_mock_amr_instruments()
        mt = _LegacyMagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=500.0,
            save_dir=str(tmp_path),
            voltage_calibration=10000,
            live_plot=False,
        )

        assert mt.dmm is mocks["dmm"]
        assert mt.calibrator is mocks["calibrator"]
        assert mt.stepper is mocks["arduino"]
        assert mt.arduino is mocks["arduino"]
        assert mt.lockin is mocks["lockin"]
        assert mt.field == 500.0
        assert mt.save_dir == str(tmp_path)
        assert mt.voltage_calibration == 10000
        assert mt.voltage_callibration == 10000
        assert mt.data is None
        assert mt.filename is None
        assert mt.abort_requested is False
        assert mt.pause_requested is False
        assert mt.live_plot is False
        assert mt.plot_config == {"x": "angle", "y": "X"}

        # Legacy observation: base class constructor performs NO hardware communication
        assert mocks["dmm"].idn.call_count == 0
        assert mocks["calibrator"].idn.call_count == 0
        assert mocks["arduino"].idn.call_count == 0
        assert mocks["lockin"].idn.call_count == 0

    def test_magneto_transport_initialize_and_idn_queries(self):
        mocks = create_mock_amr_instruments(field=200.0)
        mt = _LegacyMagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=200.0,
            live_plot=False,
        )

        with patch("time.sleep", return_value=None):
            mt.initialize()

        mocks["dmm"].idn.assert_called_once()
        mocks["calibrator"].idn.assert_called_once()
        mocks["arduino"].idn.assert_called_once()
        mocks["lockin"].idn.assert_called_once()
        mocks["calibrator"].set_output.assert_called_with(200.0 / 10000.0)

    def test_magneto_transport_initialize_tolerates_communication_error(self, capsys):
        mocks = create_mock_amr_instruments()
        mocks["dmm"].idn.side_effect = RuntimeError("Connection timed out")
        mt = _LegacyMagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            live_plot=False,
        )

        with patch("time.sleep", return_value=None):
            mt.initialize()

        captured = capsys.readouterr().out
        assert "Error communicating with instruments" in captured

    def test_magneto_transport_set_field_feedback_loop_within_tolerance(self, capsys):
        mocks = create_mock_amr_instruments(field=1000.0, voltage_calibration=10000.0)
        # Expected voltage: 1000 / 10000 = 0.1V. DMM reads 0.1V -> actual field 1000 Oe
        mocks["dmm"].get_voltage.return_value = 0.100

        mt = _LegacyMagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=1000.0,
            voltage_calibration=10000,
            live_plot=False,
        )

        with patch("time.sleep", return_value=None):
            mt.set_field()

        mocks["calibrator"].set_output.assert_called_once_with(0.1)
        mocks["dmm"].get_voltage.assert_called_once()
        captured = capsys.readouterr().out
        assert "Set field to 1000.0 Oe and checked it is at 1000.0 Oe" in captured
        assert "Warning" not in captured

    def test_magneto_transport_set_field_feedback_loop_out_of_tolerance_warning(self, capsys):
        mocks = create_mock_amr_instruments(field=1000.0, voltage_calibration=10000.0)
        # DMM reads 0.15V -> actual field 1500 Oe, 50% deviation (> 10% tolerance)
        mocks["dmm"].get_voltage.return_value = 0.150

        mt = _LegacyMagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=1000.0,
            voltage_calibration=10000,
            live_plot=False,
        )

        with patch("time.sleep", return_value=None):
            mt.set_field()

        captured = capsys.readouterr().out
        assert "Warning: Field set to 1000.0 Oe, but actual field is 1500.0 Oe" in captured

    def test_magneto_transport_shut_off_safing(self):
        mocks = create_mock_amr_instruments()
        mt = _LegacyMagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            live_plot=False,
        )

        mt.shut_off()
        mocks["calibrator"].set_output.assert_called_once_with(0)

    def test_magneto_transport_not_implemented_methods_raise(self):
        mocks = create_mock_amr_instruments()
        mt = _LegacyMagnetoTransport(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            live_plot=False,
        )

        with pytest.raises(AttributeError, match="configure_lockin\\(\\) must be defined"):
            mt.configure_lockin()

        with pytest.raises(AttributeError, match="capture_data\\(\\) must be defined"):
            mt.capture_data()

    def test_angle_step_conversion_helpers(self):
        # Default: 200 steps/rev -> 1.8 deg/step
        assert convert_angle_to_steps(0) == 0
        assert convert_angle_to_steps(1.8) == 1
        assert convert_angle_to_steps(45.0) == 25
        assert convert_angle_to_steps(90.0) == 50
        assert convert_angle_to_steps(180.0) == 100
        assert convert_angle_to_steps(360.0) == 200

        assert convert_steps_to_angle(0) == pytest.approx(0.0)
        assert convert_steps_to_angle(1) == pytest.approx(1.8)
        assert convert_steps_to_angle(25) == pytest.approx(45.0)
        assert convert_steps_to_angle(50) == pytest.approx(90.0)
        assert convert_steps_to_angle(100) == pytest.approx(180.0)
        assert convert_steps_to_angle(200) == pytest.approx(360.0)

        # Custom steps_per_revolution
        assert convert_angle_to_steps(90.0, steps_per_revolution=400) == 100
        assert convert_steps_to_angle(100, steps_per_revolution=400) == pytest.approx(90.0)

    def test_convert_field_to_voltage_matches_documented_calibration(self):
        assert convert_field_to_voltage(100.0) == pytest.approx(0.01)
        assert convert_field_to_voltage(0.0) == pytest.approx(0.0)
        assert convert_field_to_voltage(500.0) == pytest.approx(0.05)


class TestAMRCompatibility:
    """Characterize legacy AMR measurement behavior and verify golden regression."""

    def test_amr_constructor_and_attributes(self, tmp_path):
        mocks = create_mock_amr_instruments()
        amr = AMR(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            arduino=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            angle_step=15.0,
            total_angle=360.0,
            amplitude=1.0,
            frequency=10,
            measure_time=1.0,
            sensitivity="50uv/pa",
            save_dir=str(tmp_path),
            voltage_callibration=10000,
            live_plot=False,
        )

        assert amr.mtype == "amr"
        assert amr.field == 100.0
        assert amr.angle_step == 15.0
        assert amr.total_angle == 360.0
        assert amr.amplitude == 1.0
        assert amr.frequency == 10
        assert amr.measure_time == 1.0
        assert amr.sensitivity == "50uv/pa"
        assert amr.notes == "1p0V_10Hz"
        assert amr.data is None
        assert amr.filename is not None
        assert "0_amr_1p0V_10Hz.csv" in Path(amr.filename).name

        # Verify constructor instrument identity queries
        mocks["lockin"].idn.assert_called_once()
        mocks["dmm"].idn.assert_called_once()
        mocks["arduino"].idn.assert_called_once()

        # Metadata DataFrame layout and fields
        assert isinstance(amr.metadata, pd.DataFrame)
        assert len(amr.metadata) == 1
        assert amr.metadata.loc[0, "mtype"] == "amr"
        assert amr.metadata.loc[0, "lockin"] == "TEST_LOCKIN"
        assert amr.metadata.loc[0, "dmm"] == "TEST_DMM"
        assert amr.metadata.loc[0, "arduino"] == "TEST_STEPPER"
        assert amr.metadata.loc[0, "field"] == 100.0
        assert amr.metadata.loc[0, "angle_step"] == 15.0
        assert amr.metadata.loc[0, "total_angle"] == 360.0
        assert amr.metadata.loc[0, "amplitude"] == 1.0
        assert amr.metadata.loc[0, "frequency"] == 10
        assert amr.metadata.loc[0, "measure_time"] == 1.0
        assert amr.metadata.loc[0, "sensitivity"] == "50uv/pa"
        assert amr.metadata.loc[0, "voltage_callibration"] == 10000
        assert bool(amr.metadata.loc[0, "processed"]) is False

    def test_amr_configure_lockin(self, tmp_path):
        mocks = create_mock_amr_instruments()
        amr = AMR(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            arduino=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            amplitude=0.5,
            frequency=13,
            sensitivity="100uv/pa",
            save_dir=str(tmp_path),
            live_plot=False,
        )

        with patch("time.sleep", return_value=None):
            amr.configure_lockin()

        mocks["lockin"].initialize.assert_called_once()
        mocks["lockin"].configure_reference.assert_called_once_with(voltage=0.5, frequency=13)
        mocks["lockin"].configure_input.assert_called_once_with(input_configuration="a-b")
        mocks["lockin"].configure_gain_filters.assert_called_once_with(sensitivity="100uv/pa")

    def test_amr_full_run_matches_documented_legacy_observation(self, tmp_path):
        """Characterize old output, including AMR-ANGLE-001; this is not the scientific target."""
        mocks = create_mock_amr_instruments(
            resistance_baseline=100.0,
            amr_delta=2.0,
            field=100.0,
            voltage_calibration=10000.0,
        )

        with patch("time.sleep", return_value=None), patch("matplotlib.pyplot.show"):
            amr = AMR(
                dmm=mocks["dmm"],
                calibrator=mocks["calibrator"],
                arduino=mocks["arduino"],
                lockin=mocks["lockin"],
                field=100.0,
                angle_step=45.0,
                total_angle=180.0,
                amplitude=1.0,
                frequency=10,
                measure_time=0.01,
                sensitivity="50uv/pa",
                save_dir=str(tmp_path),
                live_plot=False,
            )
            amr.run_experiment(configure_lockin=False)

        assert amr.filename is not None
        assert Path(amr.filename).is_file()

        # 1. Transitional observation only. Remove this assertion when AMR-ANGLE-001
        # is repaired; the intended scientific fixture is AMR_GOLDEN_PATH.
        assert_golden_csv_matches(amr.filename, AMR_OBSERVED_PATH, float_tolerance=AMR_SIGNAL_ATOL)

        # 2. Layout validation
        meta, data = assert_piec_csv_layout(amr.filename)
        assert len(meta) == 1
        assert len(data) == 5
        assert_data_columns_match(data, ["angle", "field", "X", "Y"], exact_order=True)

        # 3. Numerical data equivalence against reference
        _, observed_data = assert_piec_csv_layout(AMR_OBSERVED_PATH)
        assert_numerical_data_matches_reference(data, observed_data, "AMR", float_tolerance=AMR_SIGNAL_ATOL)

        # 4. Safing was performed at experiment completion
        mocks["calibrator"].set_output.assert_has_calls([call(0.01), call(0)])

    def test_amr_interior_cos2_theta_behavior(self, tmp_path):
        """
        Verify physical AMR angular dependence:
        R(theta) = R_perp + delta_R * cos^2(theta).
        Signal X is maximal at theta = 0, 180 deg and minimal at theta = 90 deg.
        """
        mocks = create_mock_amr_instruments(
            resistance_baseline=100.0,
            amr_delta=10.0,  # 10 uV AMR contrast
            field=500.0,
        )

        with patch("time.sleep", return_value=None), patch("matplotlib.pyplot.show"):
            amr = AMR(
                dmm=mocks["dmm"],
                calibrator=mocks["calibrator"],
                arduino=mocks["arduino"],
                lockin=mocks["lockin"],
                field=500.0,
                angle_step=18.0,
                total_angle=180.0,
                amplitude=1.0,
                frequency=10,
                measure_time=0.01,
                sensitivity="50uv/pa",
                save_dir=str(tmp_path),
                live_plot=False,
            )
            amr.run_experiment(configure_lockin=False)

        data = amr.data
        assert data is not None
        assert len(data) == 11

        # In-phase signal X at 0 deg must equal maximum (R_parallel)
        x_at_0 = data.loc[data["angle"] == 0.0, "X"].iloc[0]
        assert x_at_0 == pytest.approx(110.0e-6, rel=1e-3)

        # In-phase signal X at 90 deg must equal minimum (R_perp)
        x_at_90 = data.loc[data["angle"] == 90.0, "X"].iloc[0]
        assert x_at_90 == pytest.approx(100.0e-6, rel=1e-3)

        # Delta R must be positive
        delta_r = x_at_0 - x_at_90
        assert delta_r > 0.0
        assert delta_r == pytest.approx(10.0e-6, rel=1e-3)

        # This passing test covers the regular interior only. The endpoint has
        # its own strict expected-failure test for AMR-ANGLE-001 below.
        loop_data = data.iloc[:-1]
        angles_rad = np.radians(loop_data["angle"].to_numpy())
        cos2 = np.cos(angles_rad) ** 2
        x_vals = loop_data["X"].to_numpy()
        correlation = np.corrcoef(cos2, x_vals)[0, 1]
        assert correlation > 0.999

    def test_amr_scientific_golden_matches_analytic_model_at_every_angle(self):
        _, golden = assert_piec_csv_layout(AMR_GOLDEN_PATH)
        expected_x = (100.0 + 2.0 * np.cos(np.radians(golden["angle"])) ** 2) * 1e-6
        np.testing.assert_allclose(golden["X"], expected_x, atol=AMR_SIGNAL_ATOL, rtol=1e-7)
        np.testing.assert_allclose(golden["Y"], 0.1 * expected_x, atol=AMR_SIGNAL_ATOL, rtol=1e-7)
        assert golden.iloc[-1]["X"] == pytest.approx(102e-6, abs=AMR_SIGNAL_ATOL, rel=1e-7)

    @pytest.mark.xfail(
        strict=True, raises=AssertionError,
        reason="AMR-ANGLE-001: endpoint is read after an extra motor step; repair checkpoint 24b",
    )
    def test_amr_endpoint_matches_commanded_angle_and_scientific_golden(self, tmp_path):
        mocks = create_mock_amr_instruments()
        with patch("time.sleep", return_value=None), patch("matplotlib.pyplot.show"):
            amr = AMR(
                dmm=mocks["dmm"], calibrator=mocks["calibrator"], arduino=mocks["arduino"],
                lockin=mocks["lockin"], field=100.0, angle_step=45.0, total_angle=180.0,
                measure_time=0.01, save_dir=str(tmp_path), live_plot=False,
            )
            amr.run_experiment(configure_lockin=False)
        _, expected = assert_piec_csv_layout(AMR_GOLDEN_PATH)
        # No clipping of the final row: verify the physical position and both signals.
        actual_endpoint = [mocks["current_angle"][0], amr.data.iloc[-1]["X"], amr.data.iloc[-1]["Y"]]
        expected_endpoint = expected.iloc[-1][["angle", "X", "Y"]].to_numpy()
        np.testing.assert_allclose(actual_endpoint, expected_endpoint, atol=AMR_SIGNAL_ATOL, rtol=1e-7)

    @pytest.mark.parametrize("helper", ["csv", "numerical"])
    @pytest.mark.parametrize("column", ["X", "Y"])
    def test_amr_golden_checks_reject_flat_signal(self, tmp_path, helper, column):
        metadata, expected = assert_piec_csv_layout(AMR_GOLDEN_PATH)
        actual = expected.copy()
        actual[column] = actual[column].min()
        if helper == "csv":
            path = tmp_path / "flat.csv"
            metadata_and_data_to_csv(metadata, actual, path)
            with pytest.raises(AssertionError, match="Data mismatch"):
                assert_golden_csv_matches(path, AMR_GOLDEN_PATH, float_tolerance=AMR_SIGNAL_ATOL)
        else:
            with pytest.raises(AssertionError, match="Numerical mismatch"):
                assert_numerical_data_matches_reference(actual, expected, "AMR", float_tolerance=AMR_SIGNAL_ATOL)

    def test_amr_pause_control(self, tmp_path):
        """Verify that setting pause_requested pauses acquisition until unpaused."""
        mocks = create_mock_amr_instruments()
        amr = AMR(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            arduino=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            angle_step=45.0,
            total_angle=90.0,
            measure_time=0.01,
            save_dir=str(tmp_path),
            live_plot=False,
        )

        pause_checks = []

        def mock_sleep_with_unpause(duration):
            if amr.pause_requested:
                pause_checks.append(True)
                # Unpause on the second pause sleep check
                if len(pause_checks) >= 2:
                    amr.pause_requested = False

        amr.pause_requested = True
        with patch("time.sleep", side_effect=mock_sleep_with_unpause), patch("matplotlib.pyplot.show"):
            amr.run_experiment(configure_lockin=False)

        assert len(pause_checks) >= 2
        assert amr.pause_requested is False
        assert amr.data is not None
        assert len(amr.data) == 3  # 0, 45, 90 deg

    def test_amr_abort_control(self, tmp_path):
        """Verify that setting abort_requested terminates measurement early and preserves collected data."""
        mocks = create_mock_amr_instruments()
        amr = AMR(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            arduino=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            angle_step=45.0,
            total_angle=180.0,
            measure_time=0.01,
            save_dir=str(tmp_path),
            live_plot=False,
        )

        call_count = [0]

        def mock_sleep_with_abort(duration):
            call_count[0] += 1
            # Abort after first angle data point is captured
            if len(amr.data) >= 1 if amr.data is not None else False:
                amr.abort_requested = True

        with patch("time.sleep", side_effect=mock_sleep_with_abort), patch("matplotlib.pyplot.show"):
            amr.run_experiment(configure_lockin=False)

        assert amr.abort_requested is True
        assert amr.data is not None
        # Aborted early: fewer points than full sweep (5 points)
        assert len(amr.data) < 5
        assert len(amr.data) >= 1

        # Partial CSV exists on disk
        assert Path(amr.filename).is_file()
        meta, data = assert_piec_csv_layout(amr.filename)
        assert len(data) == len(amr.data)

    def test_amr_incremental_saving(self, tmp_path):
        """Verify that legacy AMR saves to CSV after every data point."""
        mocks = create_mock_amr_instruments()
        amr = AMR(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            arduino=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            angle_step=90.0,
            total_angle=180.0,
            measure_time=0.01,
            save_dir=str(tmp_path),
            live_plot=False,
        )

        rows_at_each_save = []
        original_save = amr.save_data_point

        def record_save():
            original_save()
            if amr.filename and Path(amr.filename).is_file():
                _, df = standard_csv_to_metadata_and_data(amr.filename)
                rows_at_each_save.append(len(df))

        amr.save_data_point = record_save

        with patch("time.sleep", return_value=None), patch("matplotlib.pyplot.show"):
            amr.run_experiment(configure_lockin=False)

        # File was saved progressively: 1 row, 2 rows, 3 rows
        assert rows_at_each_save == [1, 2, 3]

    def test_amr_module_reexport(self):
        """Verify that piec.measurement.amr re-exports expected classes and helpers."""
        import piec.measurement.amr as amr_module

        assert hasattr(amr_module, "MagnetoTransport")
        assert hasattr(amr_module, "AMR")
        assert hasattr(amr_module, "convert_angle_to_steps")
        assert hasattr(amr_module, "convert_steps_to_angle")
        assert hasattr(amr_module, "convert_field_to_voltage")

        assert amr_module.AMR is AMR
        assert amr_module.MagnetoTransport is MagnetoTransport
        assert amr_module.convert_angle_to_steps is convert_angle_to_steps
        assert amr_module.convert_steps_to_angle is convert_steps_to_angle
        assert amr_module.convert_field_to_voltage is convert_field_to_voltage


class TestAMRConsumerInventory:
    """Verify repository consumers of AMR and MagnetoTransport against manifest documentation."""

    def test_manifest_consumer_inventory_presence_and_structure(self):
        manifest = load_manifest()
        for family_name in ("MagnetoTransport", "AMR"):
            spec = manifest["families"][family_name]
            assert "consumer_inventory" in spec, f"Missing consumer_inventory in {family_name}"
            inv = spec["consumer_inventory"]

            assert "consumers" in inv
            assert len(inv["consumers"]) >= 4
            categories = {c["category"] for c in inv["consumers"]}
            assert {"gui", "notebook", "documentation", "module_reexport"} <= categories

            assert "physical_quantities" in inv
            quantities = inv["physical_quantities"]
            assert set(quantities.keys()) == {"angle", "field", "x", "y"}
            assert quantities["angle"]["unit"] == "deg"
            assert quantities["field"]["unit"] == "Oe"
            assert quantities["x"]["unit"] == "V"
            assert quantities["y"]["unit"] == "V"

    def test_gui_consumer_contract(self):
        """Verify that Measurements/AMR/amr_GUI.py matches the documented inventory."""
        gui_path = REPO_ROOT / "Measurements" / "AMR" / "amr_GUI.py"
        assert gui_path.is_file(), f"GUI file {gui_path} not found"

        content = gui_path.read_text(encoding="utf-8")

        # Import contract
        assert "from piec.measurement.amr import AMR" in content

        # Instantiation parameters
        for arg in (
            "dmm", "calibrator", "arduino", "lockin", "field",
            "angle_step", "total_angle", "amplitude", "frequency",
            "measure_time", "sensitivity", "save_dir"
        ):
            assert f"{arg}=" in content, f"Missing {arg} in GUI AMR instantiation"

        # Background execution
        assert "threading.Thread" in content
        assert "target=self.experiment.run_experiment" in content
        assert "configure_lockin" in content

        # Controls
        assert "pause_requested" in content
        assert "abort_requested" in content

        # Data consumption
        assert "standard_csv_to_metadata_and_data" in content

    def test_notebook_consumer_contract(self):
        """Verify that Measurements/AMR/AMR_testing.ipynb matches the documented inventory."""
        nb_path = REPO_ROOT / "Measurements" / "AMR" / "AMR_testing.ipynb"
        assert nb_path.is_file(), f"Notebook file {nb_path} not found"

        content = nb_path.read_text(encoding="utf-8")
        nb = json.loads(content)

        # Find code cells
        code_cells = [cell["source"] for cell in nb["cells"] if cell["cell_type"] == "code"]
        all_code = "".join("".join(lines) for lines in code_cells)

        assert "from piec.measurement.amr import AMR" in all_code
        assert "standard_csv_to_metadata_and_data" in all_code
        assert "experiment = AMR(" in all_code
        assert "experiment.run_experiment()" in all_code
        assert "standard_csv_to_metadata_and_data(experiment.filename)" in all_code

    def test_documentation_consumer_contract(self):
        """Verify that Measurements/AMR/amr_measurement.md matches documented theory and classes."""
        doc_path = REPO_ROOT / "Measurements" / "AMR" / "amr_measurement.md"
        assert doc_path.is_file(), f"Documentation file {doc_path} not found"

        content = doc_path.read_text(encoding="utf-8")

        assert "MagnetoTransport" in content
        assert "AMR" in content
        assert "cos^2" in content or "cos^{2}" in content or "cos²" in content
        assert "Calibrator" in content
        assert "DMM" in content
        assert "feedback" in content.lower()
