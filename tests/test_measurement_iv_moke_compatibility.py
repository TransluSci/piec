"""
Characterization and regression tests for IVSweep and MokeMeasurement legacy public behavior.

Stage 0 Checkpoint 2b: IV and MOKE characterization fixtures and golden comparison.
"""

from pathlib import Path
import tempfile
from unittest.mock import Mock, call

import numpy as np
import pandas as pd
import pytest

from piec.analysis.field_calibration import FieldCalibration
from piec.analysis.utilities import standard_csv_to_metadata_and_data
from piec.measurement.iv_sweep import IVSweep
from piec.measurement.moke import MokeMeasurement, MokeSnapshot
from tests.fixtures.measurement_compatibility import (
    assert_data_columns_match,
    assert_golden_csv_matches,
    assert_numerical_data_matches_reference,
    assert_piec_csv_layout,
    load_manifest,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "measurement_compatibility"
IV_GOLDEN_PATH = FIXTURES_DIR / "iv_sweep_golden.csv"
MOKE_CAL_GOLDEN_PATH = FIXTURES_DIR / "moke_calibrated_golden.csv"
MOKE_MEAS_GOLDEN_PATH = FIXTURES_DIR / "moke_measured_golden.csv"


class TestIVSweepCompatibility:
    """Verify standardized IVSweep behavior and regression goldens."""

    def _create_mock_sourcemeter(self, resistance: float = 100.0) -> Mock:
        sm = Mock()
        sm.idn.return_value = "KEITHLEY INSTRUMENTS INC.,MODEL 2400,1234567,1.0"
        current_v = [0.0]

        def set_v(*args, **kwargs):
            if "voltage" in kwargs:
                v = kwargs["voltage"]
            elif len(args) == 2:
                v = args[1]
            elif len(args) == 1:
                v = args[0]
            else:
                v = 0.0
            current_v[0] = float(v)

        sm.set_source_voltage.side_effect = set_v
        sm.get_voltage.side_effect = lambda *args, **kwargs: current_v[0]
        sm.get_current.side_effect = lambda *args, **kwargs: current_v[0] / resistance
        return sm

    def test_iv_sweep_constructor_and_attributes(self, tmp_path):
        sm = self._create_mock_sourcemeter()
        iv = IVSweep(
            sourcemeter=sm,
            v_start=-1.0,
            v_stop=1.0,
            num_steps=21,
            current_compliance=0.05,
            dwell_time=0.01,
            sense_mode="4W",
            ramp_step=0.1,
            ramp_delay=0.01,
            output_dir=str(tmp_path),
        )

        assert iv.sourcemeter is sm
        assert iv.v_start == -1.0
        assert iv.v_stop == 1.0
        assert iv.num_steps == 21
        assert iv.current_compliance == 0.05
        assert iv.dwell_time == 0.01
        assert iv.sense_mode == "4W"
        assert iv.ramp_step == 0.1
        assert iv.ramp_delay == 0.01
        assert iv.output_dir == Path(tmp_path)
        assert iv.data is None
        assert iv.filename is None
        assert iv.mtype == "iv_sweep"
        assert iv.measurement_schema == "iv_sweep"
        assert iv.column_units == {"voltage": "V", "current": "A"}

        # Target contract: zero hardware I/O in __init__
        assert sm.idn.call_count == 0

    def test_iv_sweep_configure_instruments(self):
        sm = self._create_mock_sourcemeter()
        iv = IVSweep(sm, v_start=0.5, current_compliance=0.02, sense_mode="4W")
        iv.configure_instruments()

        sm.configure_voltage_source.assert_called_once_with(channel=1, voltage=0.0, current_compliance=0.02)
        sm.set_sense_mode.assert_called_once_with(channel=1, sense_mode="4W")
        # Standalone configure runs a transient configuration scope, safing (disabling output) on exit
        assert sm.output.call_args == call(channel=1, on=False)
        assert sm.output.call_count == 2

    def test_iv_sweep_sweep_execution(self):
        sm = self._create_mock_sourcemeter(resistance=50.0)
        iv = IVSweep(sm, v_start=0.0, v_stop=2.0, num_steps=5, dwell_time=0.0)
        with iv.session(save=False) as sess:
            sess.configure_instruments()
            data = sess.capture_data()

        sm.output.assert_called_with(channel=1, on=False)
        assert data is not None
        assert_data_columns_match(data, ["voltage", "current"], exact_order=True)
        assert len(data) == 5

        voltages = data["voltage"].tolist()
        assert voltages == pytest.approx([0.0, 0.5, 1.0, 1.5, 2.0])
        currents = data["current"].tolist()
        assert currents == pytest.approx([0.0, 0.01, 0.02, 0.03, 0.04])

    def test_iv_sweep_save_data(self, tmp_path):
        sm = self._create_mock_sourcemeter()
        iv = IVSweep(sm, v_start=0.0, v_stop=1.0, num_steps=3, dwell_time=0.0, output_dir=str(tmp_path))
        df = iv.run_experiment(save=True)

        assert iv.filename is not None
        assert Path(iv.filename).is_file()
        assert Path(iv.filename).name.endswith("_iv_sweep.csv")

        meta, data = assert_piec_csv_layout(iv.filename)
        assert len(meta) == 1
        assert len(data) == 3
        assert_data_columns_match(data, ["voltage", "current"], exact_order=True)

    def test_iv_sweep_run_experiment_lifecycle(self, tmp_path):
        sm = self._create_mock_sourcemeter()
        iv = IVSweep(sm, v_start=0.0, v_stop=1.0, num_steps=5, dwell_time=0.0, output_dir=str(tmp_path))

        result = iv.run_experiment()
        # Target contract: full runner returns DataFrame
        assert isinstance(result, pd.DataFrame)
        assert iv.filename is not None
        assert Path(iv.filename).is_file()
        # Output must be turned off at completion
        sm.output.assert_called_with(channel=1, on=False)

    def test_iv_sweep_golden_csv_regression(self, tmp_path):
        """Verify that deterministic execution produces exact match against golden CSV."""
        sm = self._create_mock_sourcemeter(resistance=100.0)
        iv = IVSweep(sm, v_start=0.0, v_stop=1.0, num_steps=5, dwell_time=0.0, sense_mode="2W", output_dir=str(tmp_path))
        iv.run_experiment()

        assert_golden_csv_matches(
            actual_path=iv.filename,
            golden_path=IV_GOLDEN_PATH,
            volatile_metadata_keys=["timestamp", "run_id"],
        )

    def test_iv_sweep_numerical_equivalence_with_mapping(self, tmp_path):
        """Verify numerical equivalence using the harness old_to_new_column_mapping."""
        from piec.measurement.persistence import read_measurement_csv
        sm = self._create_mock_sourcemeter(resistance=100.0)
        iv = IVSweep(sm, v_start=0.0, v_stop=1.0, num_steps=5, dwell_time=0.0, sense_mode="2W", output_dir=str(tmp_path))
        iv.run_experiment()

        _, gold_data, _ = read_measurement_csv(IV_GOLDEN_PATH)
        assert_numerical_data_matches_reference(iv.data, gold_data, "IVSweep")



class TestMokeMeasurementCompatibility:
    """Characterize legacy MokeMeasurement behavior and verify regression goldens."""

    @pytest.fixture
    def standard_calibration(self):
        return FieldCalibration([(-5.0, -500.0), (0.0, 0.0), (5.0, 500.0)], name="golden_cal")

    def _create_moke_setup(self, calibration, save_dir, field_reader=None, field_reader_unit=None):
        source = Mock()
        source.idn.return_value = "TEST_SOURCEMETER"
        source.voltage = (-100, 100)
        source.current_compliance = (0, 0.1)

        dmm = Mock()
        dmm.idn.return_value = "TEST_DMM"
        last_v = [0.0]

        def set_v(voltage):
            last_v[0] = float(voltage)

        source.set_source_voltage.side_effect = set_v
        dmm.get_voltage.side_effect = lambda: 0.5 + 0.0004 * (last_v[0] * 100.0)

        kwargs = dict(
            sourcemeter=source,
            dmm=dmm,
            calibration=calibration,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.0,
            ramp_delay=0.0,
            n_cycles=1,
            average_cycles=1,
            output_dir=str(save_dir),
        )
        if field_reader is not None:
            kwargs["field_reader"] = field_reader
            kwargs["field_reader_unit"] = field_reader_unit
            kwargs["field_reader_name"] = "test_gaussmeter"

        moke = MokeMeasurement(**kwargs)
        return moke, source, dmm

    def test_moke_constructor_and_attributes(self, standard_calibration, tmp_path):
        moke, source, dmm = self._create_moke_setup(standard_calibration, tmp_path)

        assert moke.mtype == "moke"
        assert moke.compliance == 0.01
        assert moke.max_output_step == 5.0
        assert moke.n_cycles == 1
        assert moke.data is None
        assert moke.run_records == ()
        assert moke.abort_requested is False

        # Target contract: zero hardware I/O in __init__
        assert source.idn.call_count == 0
        assert dmm.idn.call_count == 0
        assert moke.output_column == "source_output"
        assert moke.calibrated_field_column == "field_calibrated"
        assert moke.field_column == "field_calibrated"
        assert moke.measured_field_column == "field_measured"
        assert moke.column_units == {
            "time": "s",
            "cycle": None,
            "point": None,
            "direction": None,
            "source_output": "V",
            "field_calibrated": "Oe",
            "detector_voltage": "V",
        }
        import json
        assert json.loads(moke.column_units_json) == moke.column_units
        assert moke.metadata.loc[0, "measurement_schema"] == "moke"
        assert int(moke.metadata.loc[0, "measurement_schema_version"]) == 1
        assert json.loads(moke.metadata.loc[0, "column_units_json"]) == moke.column_units

    def test_moke_calibrated_mode_full_run_and_golden(self, standard_calibration, tmp_path):
        moke, source, dmm = self._create_moke_setup(standard_calibration, tmp_path)

        snapshots = []
        result = moke.run_experiment(on_update=snapshots.append)

        # Legacy contract: MOKE returns DataFrame
        assert isinstance(result, pd.DataFrame)
        assert result is moke.data
        assert moke.filename is not None
        assert Path(moke.filename).is_file()

        # Check column names
        expected_cols = [
            "time", "cycle", "point", "direction",
            "source_output", "field_calibrated", "detector_voltage",
        ]
        assert_data_columns_match(moke.data, expected_cols, exact_order=True)

        # Check snapshots received
        assert len(snapshots) > 0
        last_snap = snapshots[-1]
        assert isinstance(last_snap, MokeSnapshot)
        assert last_snap.completed_cycles == 1
        assert last_snap.field_column == "field_calibrated"

        # Compare against golden CSV
        assert_golden_csv_matches(
            actual_path=moke.filename,
            golden_path=MOKE_CAL_GOLDEN_PATH,
            time_columns=("time", "field_time"),
            volatile_metadata_keys=["timestamp", "save_dir", "filename"],
        )

    def test_moke_numerical_equivalence_with_mapping(self, standard_calibration, tmp_path):
        """Verify numerical equivalence using the harness old_to_new_column_mapping."""
        moke, source, dmm = self._create_moke_setup(standard_calibration, tmp_path)
        moke.run_experiment()

        _, gold_data = standard_csv_to_metadata_and_data(str(MOKE_CAL_GOLDEN_PATH))
        assert_numerical_data_matches_reference(moke.data, gold_data, "MokeMeasurement")


    def test_moke_measured_field_mode_full_run_and_golden(self, standard_calibration, tmp_path):
        field_reader = Mock(return_value=50.0)
        moke, source, dmm = self._create_moke_setup(
            standard_calibration, tmp_path, field_reader=field_reader, field_reader_unit="Oe",
        )

        assert moke.field_column == "field_measured"
        assert moke.column_units["field_measured"] == "Oe"
        assert moke.column_units["field_time"] == "s"
        result = moke.run_experiment()
        assert isinstance(result, pd.DataFrame)

        expected_cols = [
            "time", "cycle", "point", "direction",
            "source_output", "field_calibrated", "detector_voltage",
            "field_measured", "field_time",
        ]
        assert_data_columns_match(moke.data, expected_cols, exact_order=True)
        assert (moke.data["field_measured"] == 50.0).all()

        # Compare against golden CSV
        assert_golden_csv_matches(
            actual_path=moke.filename,
            golden_path=MOKE_MEAS_GOLDEN_PATH,
            time_columns=("time", "field_time"),
            volatile_metadata_keys=["timestamp", "save_dir", "filename"],
        )

    def test_moke_custom_safe_shutdown(self, standard_calibration, tmp_path):
        custom_shutdown = Mock()
        source = Mock()
        source.idn.return_value = "TEST_SOURCEMETER"
        source.voltage = (-100, 100)
        source.current_compliance = (0, 0.1)
        dmm = Mock()
        dmm.idn.return_value = "TEST_DMM"

        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=standard_calibration,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            shutdown_handler=custom_shutdown,
            output_dir=str(tmp_path),
        )

        moke.safe_shutdown()
        custom_shutdown.assert_called_once_with(source)

    def test_moke_default_safe_shutdown_disables_output(self, standard_calibration, tmp_path):
        moke, source, dmm = self._create_moke_setup(standard_calibration, tmp_path)
        moke.configure_instruments()
        assert moke._configured is True

        moke.safe_shutdown()
        assert moke.safety_status.value == "SAFE"
        source.output.assert_called_with(on=False)

    def test_moke_column_units_json_round_trip_and_alternative_units(self, tmp_path):
        import json
        cal_alt = FieldCalibration([(-0.5, -0.05), (0.0, 0.0), (0.5, 0.05)], output_unit="A", field_unit="T")
        source = Mock()
        source.idn.return_value = "TEST_SOURCEMETER"
        source.current = (-10, 10)
        source.voltage_compliance = (0, 100)
        dmm = Mock()
        dmm.idn.return_value = "TEST_DMM"
        dmm.get_voltage.return_value = 0.42

        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=dmm,
            calibration=cal_alt,
            output_values=[-0.5, 0.0, 0.5, 0.0, -0.5],
            compliance=10.0,
            max_output_step=0.5,
            dwell_time=0.0,
            ramp_delay=0.0,
            n_cycles=1,
            average_cycles=1,
            field_reader=Mock(return_value=0.012),
            field_reader_unit="T",
            field_reader_name="gaussmeter_T",
            output_dir=str(tmp_path),
        )

        assert moke.output_column == "source_output"
        assert moke.calibrated_field_column == "field_calibrated"
        assert moke.measured_field_column == "field_measured"
        assert moke.field_column == "field_measured"

        snapshots = []
        result = moke.run_experiment(on_update=snapshots.append)
        assert isinstance(result, pd.DataFrame)
        assert moke.filename is not None

        expected_columns = [
            "time", "cycle", "point", "direction",
            "source_output", "field_calibrated", "detector_voltage",
            "field_measured", "field_time",
        ]
        assert list(result.columns) == expected_columns

        # Verify CSV persistence and metadata round-trip
        metadata, data = standard_csv_to_metadata_and_data(moke.filename)
        assert metadata.loc[0, "measurement_schema"] == "moke"
        assert int(metadata.loc[0, "measurement_schema_version"]) == 1

        loaded_units = json.loads(metadata.loc[0, "column_units_json"])
        assert set(loaded_units.keys()) == set(data.columns)
        assert loaded_units == {
            "time": "s",
            "cycle": None,
            "point": None,
            "direction": None,
            "source_output": "A",
            "field_calibrated": "T",
            "detector_voltage": "V",
            "field_measured": "T",
            "field_time": "s",
        }
        pd.testing.assert_frame_equal(data, result, check_dtype=False)

        # Verify snapshots
        assert len(snapshots) == 5
        snap = snapshots[-1]
        assert snap.field_column == "field_measured"
        assert list(snap.raw.columns) == expected_columns
        assert list(snap.last_cycle.columns) == expected_columns
        assert "detector_voltage" in snap.cycle_average.columns
        assert "field_measured" in snap.cycle_average.columns
        assert (snap.cycle_average["field_measured"] == 0.012).all()

