"""
Characterization and regression tests for AMR measurement and MagnetoTransport base.

Updated for Checkpoint 24b:
- Standardized AMR inheriting MagnetoTransport and BaseMeasurement;
- Scientific golden regression with exact target CSV layout and plain columns ('angle', 'field', 'x', 'y');
- Repaired AMR-ANGLE-001: motor endpoint matches commanded angle, zero extra step;
- Preserved manual lock-in settings by default;
- Mandatory excitation shutdown before energizing;
- Attempt-all safe shutdown;
- Modernized consumer inventory.
"""

from collections.abc import Sequence
import json
import math
from pathlib import Path
import queue
import tempfile
import threading
import time
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
    convert_voltage_to_field,
)
from piec.measurement.contracts import (
    HardwareSafetyError,
    RunRequest,
    RunState,
    SafetyStatus,
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


class TestConversionHelpers:
    """Verify conversion helper functions."""

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
    """Standardized AMR measurement behavior, lifecycle, and golden regression."""

    def test_amr_constructor_and_attributes(self, tmp_path):
        mocks = create_mock_amr_instruments()
        shutdown = Mock()
        amr = AMR(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            angle_step=15.0,
            total_angle=360.0,
            amplitude=1.0,
            frequency=10,
            measure_time=1.0,
            sensitivity="50uv/pa",
            output_dir=tmp_path,
            voltage_calibration=10000,
            live_plot=False,
            shutdown_handler=shutdown,
        )

        assert amr.mtype == "amr"
        assert amr.measurement_schema == "amr"
        assert amr.measurement_schema_version == 1
        assert amr.field == 100.0
        assert amr.angle_step == 15.0
        assert amr.total_angle == 360.0
        assert amr.amplitude == 1.0
        assert amr.frequency == 10.0
        assert amr.measure_time == 1.0
        assert amr.sensitivity == "50uv/pa"
        assert amr.data is None
        assert amr.filename is None

        # Zero constructor I/O
        assert mocks["lockin"].idn.call_count == 0
        assert mocks["dmm"].idn.call_count == 0
        assert mocks["arduino"].idn.call_count == 0
        assert mocks["calibrator"].idn.call_count == 0

        # Metadata dictionary layout and fields
        assert isinstance(amr.metadata, dict)
        assert amr.metadata["field"] == 100.0
        assert amr.metadata["field_unit"] == "Oe"
        assert amr.metadata["angle_step"] == 15.0
        assert amr.metadata["total_angle"] == 360.0
        assert amr.metadata["amplitude"] == 1.0
        assert amr.metadata["frequency"] == 10.0

    def test_amr_requires_excitation_shutdown_before_energizing(self, tmp_path):
        mocks = create_mock_amr_instruments()
        amr = AMR(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            output_dir=tmp_path,
            shutdown_handler=None,
        )

        with pytest.raises(HardwareSafetyError, match="Excitation shutdown handler required before energizing"):
            amr.run_experiment(save=False)

    def test_amr_configure_lockin_via_options(self, tmp_path):
        mocks = create_mock_amr_instruments()
        shutdown = Mock()
        amr = AMR(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            amplitude=0.5,
            frequency=13,
            sensitivity="100uv/pa",
            output_dir=tmp_path,
            live_plot=False,
            shutdown_handler=shutdown,
        )

        with patch("time.sleep", return_value=None):
            with amr.session(options={"configure_lockin": True}) as sess:
                sess.configure_instruments()

        mocks["lockin"].configure_reference.assert_called_once_with(source="internal", voltage=0.5, frequency=13)
        mocks["lockin"].configure_input.assert_called_once_with(input_configuration="a-b")
        mocks["lockin"].configure_gain_filters.assert_called_once_with(sensitivity="100uv/pa")

    def test_amr_full_run_matches_scientific_golden(self, tmp_path):
        """Verify full standardized AMR execution produces exact scientific golden results."""
        mocks = create_mock_amr_instruments(
            resistance_baseline=100.0,
            amr_delta=2.0,
            field=100.0,
            voltage_calibration=10000.0,
        )
        shutdown = Mock()

        with patch("time.sleep", return_value=None):
            amr = AMR(
                dmm=mocks["dmm"],
                calibrator=mocks["calibrator"],
                stepper=mocks["arduino"],
                lockin=mocks["lockin"],
                field=100.0,
                angle_step=45.0,
                total_angle=180.0,
                amplitude=1.0,
                frequency=10,
                measure_time=0.01,
                settling_time=0.0,
                sensitivity="50uv/pa",
                output_dir=tmp_path,
                live_plot=False,
                shutdown_handler=shutdown,
            )
            df = amr.run_experiment(save=True)

        assert amr.filename is not None
        assert Path(amr.filename).is_file()

        # 1. Match scientific golden CSV
        assert_golden_csv_matches(amr.filename, AMR_GOLDEN_PATH, float_tolerance=AMR_SIGNAL_ATOL)

        # 2. Layout validation
        meta, data = assert_piec_csv_layout(amr.filename)
        assert len(meta) == 1
        assert len(data) == 5
        assert_data_columns_match(data, ["angle", "field", "x", "y"], exact_order=True)

        # 3. Numerical data equivalence against reference
        _, golden_data = assert_piec_csv_layout(AMR_GOLDEN_PATH)
        assert_numerical_data_matches_reference(data, golden_data, "AMR", float_tolerance=AMR_SIGNAL_ATOL)

        # 4. Safing was performed at experiment completion
        assert shutdown.call_count == 1
        mocks["calibrator"].set_output.assert_has_calls([call(0.01, mode="voltage"), call(0.0, mode="voltage")])

    def test_amr_interior_cos2_theta_behavior(self, tmp_path):
        """
        Verify physical AMR angular dependence:
        R(theta) = R_perp + delta_R * cos^2(theta).
        Signal x is maximal at theta = 0, 180 deg and minimal at theta = 90 deg.
        """
        mocks = create_mock_amr_instruments(
            resistance_baseline=100.0,
            amr_delta=10.0,  # 10 uV AMR contrast
            field=500.0,
        )
        shutdown = Mock()

        with patch("time.sleep", return_value=None):
            amr = AMR(
                dmm=mocks["dmm"],
                calibrator=mocks["calibrator"],
                stepper=mocks["arduino"],
                lockin=mocks["lockin"],
                field=500.0,
                angle_step=18.0,
                total_angle=180.0,
                amplitude=1.0,
                frequency=10,
                measure_time=0.01,
                settling_time=0.0,
                sensitivity="50uv/pa",
                output_dir=tmp_path,
                live_plot=False,
                shutdown_handler=shutdown,
            )
            amr.run_experiment(save=False)

        data = amr.data
        assert data is not None
        assert len(data) == 11

        # In-phase signal x at 0 deg must equal maximum (R_parallel)
        x_at_0 = data.loc[data["angle"] == 0.0, "x"].iloc[0]
        assert x_at_0 == pytest.approx(110.0e-6, rel=1e-3)

        # In-phase signal x at 90 deg must equal minimum (R_perp)
        x_at_90 = data.loc[data["angle"] == 90.0, "x"].iloc[0]
        assert x_at_90 == pytest.approx(100.0e-6, rel=1e-3)

        # Delta R must be positive
        delta_r = x_at_0 - x_at_90
        assert delta_r > 0.0
        assert delta_r == pytest.approx(10.0e-6, rel=1e-3)

        # Cos^2 correlation
        angles_rad = np.radians(data["angle"].to_numpy())
        cos2 = np.cos(angles_rad) ** 2
        x_vals = data["x"].to_numpy()
        correlation = np.corrcoef(cos2, x_vals)[0, 1]
        assert correlation > 0.999

    def test_amr_scientific_golden_matches_analytic_model_at_every_angle(self):
        _, golden = assert_piec_csv_layout(AMR_GOLDEN_PATH)
        expected_x = (100.0 + 2.0 * np.cos(np.radians(golden["angle"])) ** 2) * 1e-6
        np.testing.assert_allclose(golden["x"], expected_x, atol=AMR_SIGNAL_ATOL, rtol=1e-7)
        np.testing.assert_allclose(golden["y"], 0.1 * expected_x, atol=AMR_SIGNAL_ATOL, rtol=1e-7)
        assert golden.iloc[-1]["x"] == pytest.approx(102e-6, abs=AMR_SIGNAL_ATOL, rel=1e-7)

    def test_amr_endpoint_matches_commanded_angle_and_scientific_golden(self, tmp_path):
        """
        Verify AMR-ANGLE-001 defect is repaired:
        Motor endpoint matches commanded angle (180.0 deg) exactly without an extra step.
        """
        mocks = create_mock_amr_instruments()
        shutdown = Mock()
        with patch("time.sleep", return_value=None):
            amr = AMR(
                dmm=mocks["dmm"],
                calibrator=mocks["calibrator"],
                stepper=mocks["arduino"],
                lockin=mocks["lockin"],
                field=100.0,
                angle_step=45.0,
                total_angle=180.0,
                measure_time=0.01,
                settling_time=0.0,
                output_dir=tmp_path,
                live_plot=False,
                shutdown_handler=shutdown,
            )
            amr.run_experiment(save=True)

        _, expected = assert_piec_csv_layout(AMR_GOLDEN_PATH)
        # Motor position ends at exactly 180.0 degrees (no extra step)
        assert mocks["current_angle"][0] == pytest.approx(180.0)
        actual_endpoint = [mocks["current_angle"][0], amr.data.iloc[-1]["x"], amr.data.iloc[-1]["y"]]
        expected_endpoint = expected.iloc[-1][["angle", "x", "y"]].to_numpy()
        np.testing.assert_allclose(actual_endpoint, expected_endpoint, atol=AMR_SIGNAL_ATOL, rtol=1e-7)

    @pytest.mark.parametrize("helper", ["csv", "numerical"])
    @pytest.mark.parametrize("column", ["x", "y"])
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
        """Verify that request_pause pauses acquisition cooperatively until unpaused."""
        mocks = create_mock_amr_instruments()
        shutdown = Mock()
        amr = AMR(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            angle_step=45.0,
            total_angle=90.0,
            measure_time=0.01,
            settling_time=0.0,
            output_dir=tmp_path,
            live_plot=False,
            shutdown_handler=shutdown,
        )

        paused_observed = [False]

        def handle_update(snapshot):
            if snapshot.completed_steps == 1 and not paused_observed[0]:
                amr.request_pause(True)
                paused_observed[0] = True
                # Resume after a short delay
                threading.Timer(0.05, lambda: amr.request_pause(False)).start()

        with patch("time.sleep", return_value=None):
            amr.run_experiment(on_update=handle_update, save=False)

        assert paused_observed[0] is True
        assert amr.data is not None
        assert len(amr.data) == 3  # 0, 45, 90 deg

    def test_amr_abort_control(self, tmp_path):
        """Verify that request_stop terminates measurement early and preserves collected data."""
        mocks = create_mock_amr_instruments()
        shutdown = Mock()
        amr = AMR(
            dmm=mocks["dmm"],
            calibrator=mocks["calibrator"],
            stepper=mocks["arduino"],
            lockin=mocks["lockin"],
            field=100.0,
            angle_step=45.0,
            total_angle=180.0,
            measure_time=0.01,
            settling_time=0.0,
            output_dir=tmp_path,
            live_plot=False,
            shutdown_handler=shutdown,
        )

        def handle_update(snapshot):
            if snapshot.completed_steps == 2:
                amr.request_stop()

        with patch("time.sleep", return_value=None):
            amr.run_experiment(on_update=handle_update, save=True)

        assert amr.run_state == RunState.ABORTED
        assert amr.data is not None
        assert len(amr.data) == 2  # Aborted after 2 steps

        # Partial CSV published on disk
        assert amr.partial_filename is not None
        assert Path(amr.partial_filename).is_file()
        meta, data = assert_piec_csv_layout(amr.partial_filename)
        assert len(data) == 2

    def test_amr_module_reexport(self):
        """Verify that piec.measurement.amr re-exports expected classes and helpers."""
        import piec.measurement.amr as amr_module

        assert hasattr(amr_module, "MagnetoTransport")
        assert hasattr(amr_module, "AMR")
        assert hasattr(amr_module, "convert_angle_to_steps")
        assert hasattr(amr_module, "convert_steps_to_angle")
        assert hasattr(amr_module, "convert_field_to_voltage")
        assert hasattr(amr_module, "convert_voltage_to_field")

        assert amr_module.AMR is AMR
        assert amr_module.MagnetoTransport is MagnetoTransport
        assert amr_module.convert_angle_to_steps is convert_angle_to_steps
        assert amr_module.convert_steps_to_angle is convert_steps_to_angle
        assert amr_module.convert_field_to_voltage is convert_field_to_voltage
        assert amr_module.convert_voltage_to_field is convert_voltage_to_field


class TestAMRConsumerInventory:
    """Verify repository consumers of AMR and MagnetoTransport against manifest documentation."""

    def test_manifest_consumer_inventory_presence_and_structure(self):
        manifest = load_manifest()
        for family_name in ("MagnetoTransport", "AMR"):
            spec = manifest["families"][family_name]
            assert "consumer_inventory" in spec, f"Missing consumer_inventory in {family_name}"
            inv = spec["consumer_inventory"]

            assert "consumers" in inv
            assert len(inv["consumers"]) >= 3
            categories = {c["category"] for c in inv["consumers"]}
            assert {"gui", "notebook", "documentation"} <= categories

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
            "dmm", "calibrator", "stepper", "lockin", "field",
            "angle_step", "total_angle", "amplitude", "frequency",
            "measure_time", "sensitivity", "save_dir", "shutdown_handler"
        ):
            assert f"{arg}=" in content, f"Missing {arg} in GUI AMR instantiation"

        # Background execution
        assert "threading.Thread" in content
        assert "target=self.experiment.run_experiment" in content

        # Controls
        assert "request_pause" in content
        assert "request_stop" in content

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
