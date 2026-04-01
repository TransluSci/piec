"""
Integration tests covering the full virtual-driver, measurement, CSV pipeline.

Run with pytest tests/test_measurement_pipeline.py
"""

import os
import shutil
import tempfile

import pandas as pd
import pytest

from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.measurement.discrete_waveform import HysteresisLoop
from piec.analysis.utilities import standard_csv_to_metadata_and_data


class TestVirtualDriverInit:
    """Verify that virtual AWG and oscilloscope initialize correctly."""

    def setup_method(self):
        self.awg = VirtualAwg()
        self.scope = VirtualScope()

    def test_virtual_awg_creates_without_error(self):
        assert self.awg is not None

    def test_virtual_awg_idn_returns_nonempty_string(self):
        result = self.awg.idn()
        assert isinstance(result, str) and len(result) > 0

    def test_virtual_awg_has_state_dict(self):
        # State dict must exist and contain sub-dicts.
        assert hasattr(self.awg, 'state')
        assert 'output' in self.awg.state
        assert 'waveform' in self.awg.state

    def test_virtual_awg_default_waveform_is_sin(self):
        # Channel 1 starts in SIN mode
        assert self.awg.state['waveform'][1] == 'SIN'

    def test_virtual_scope_creates_without_error(self):
        assert self.scope is not None

    def test_virtual_scope_idn_returns_nonempty_string(self):
        result = self.scope.idn()
        assert isinstance(result, str) and len(result) > 0

    def test_virtual_scope_starts_unarmed(self):
        assert self.scope.state['armed'] is False

    def test_virtual_scope_arm_sets_flag(self):
        self.scope.arm()
        assert self.scope.state['armed'] is True


class TestHysteresisLoopInit:
    """Verify HysteresisLoop initialises correctly when given virtual drivers."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.loop = HysteresisLoop(
            awg=VirtualAwg(),
            osc=VirtualScope(),
            frequency=1000.0,
            amplitude=1.0,
            save_dir=self.tmp_dir,
        )

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_loop_is_not_none(self):
        assert self.loop is not None

    def test_loop_mtype_is_hysteresis(self):
        assert self.loop.mtype == "hysteresis"

    def test_loop_data_is_none_before_capture(self):
        # No waveform has been captured yet, data must be None
        assert self.loop.data is None

    def test_loop_filename_is_none_before_save(self):
        # No file has been written yet
        assert self.loop.filename is None

    def test_loop_metadata_is_a_dataframe(self):
        # _update_metadata() is called in init so metadata should exist
        assert isinstance(self.loop.metadata, pd.DataFrame)

    def test_loop_metadata_has_frequency(self):
        assert 'frequency' in self.loop.metadata.columns
        assert float(self.loop.metadata['frequency'].values[0]) == pytest.approx(1000.0)

    def test_loop_metadata_has_amplitude(self):
        assert 'amplitude' in self.loop.metadata.columns
        assert float(self.loop.metadata['amplitude'].values[0]) == pytest.approx(1.0)

    def test_loop_history_starts_empty(self):
        # History is only populated after run_experiment() finishes
        assert self.loop.history == []


class TestHysteresisFullPipeline:
    """
    End-to-end test of the full measurement pipeline.
    """

    def setup_method(self):
        # Create a fresh temporary directory for each test 
        self.tmp_dir = tempfile.mkdtemp()

        # Instantiate virtual drivers
        awg = VirtualAwg()
        scope = VirtualScope()

        # Build and execute the complete measurement pipeline
        self.loop = HysteresisLoop(
            awg=awg,
            osc=scope,
            frequency=1000.0,   # 1 kHz
            amplitude=1.0,      # 1 V peak amplitude
            n_cycles=2,         # two bipolar triangle cycles
            area=1.0e-5,       
            show_plots=False,  
            save_plots=False,  
            save_dir=self.tmp_dir,
        )
        self.loop.run_experiment()

        # Store the path returned by save_waveform()
        self.csv_path = self.loop.filename

    def teardown_method(self):
        # Always remove the temporary directory tree after each test
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_csv_file_is_created(self):
        """run_experiment() must produce a CSV file at the reported path."""
        assert self.csv_path is not None
        assert os.path.isfile(self.csv_path), (
            f"Expected CSV at {self.csv_path!r} but no file was found"
        )

    def test_csv_file_has_nonzero_size(self):
        """The CSV must contain actual content and not be empty."""
        assert os.path.getsize(self.csv_path) > 0

    def test_csv_can_be_read_back(self):
        """The CSV must be parseable by the piec standard reader without error."""
        metadata, data = standard_csv_to_metadata_and_data(self.csv_path)
        assert metadata is not None
        assert data is not None

    # test metadata

    def test_metadata_contains_required_columns(self):
        """All parameters that process_raw_hyst() reads must be in the metadata."""
        metadata, _ = standard_csv_to_metadata_and_data(self.csv_path)
        for col in ('frequency', 'amplitude', 'area', 'n_cycles', 'time_offset'):
            assert col in metadata.columns, f"Metadata is missing column: '{col}'"

    def test_metadata_frequency_value_is_correct(self):
        """Frequency stored in metadata must match the value passed to the constructor."""
        metadata, _ = standard_csv_to_metadata_and_data(self.csv_path)
        assert float(metadata['frequency'].values[0]) == pytest.approx(1000.0)

    def test_metadata_amplitude_value_is_correct(self):
        """Amplitude stored in metadata must match the value passed to the constructor."""
        metadata, _ = standard_csv_to_metadata_and_data(self.csv_path)
        assert float(metadata['amplitude'].values[0]) == pytest.approx(1.0)

    def test_metadata_processed_flag_is_true_after_analysis(self):
        """analyze() must update the 'processed' flag to True in the CSV."""
        metadata, _ = standard_csv_to_metadata_and_data(self.csv_path)
        assert bool(metadata['processed'].values[0]) is True

    # Data validation

    def test_data_has_raw_capture_columns(self):
        """Columns written by apply_and_capture_waveform() must be present."""
        _, data = standard_csv_to_metadata_and_data(self.csv_path)
        for col in ('time (s)', 'voltage (V)'):
            assert col in data.columns, f"Data is missing column: '{col}'"

    def test_data_has_analysis_columns(self):
        """Columns added by process_raw_hyst() during analyze() must be present."""
        _, data = standard_csv_to_metadata_and_data(self.csv_path)
        for col in ('current (A)', 'polarization (uC/cm^2)', 'applied voltage (V)'):
            assert col in data.columns, f"Analysis column missing: '{col}'"

    def test_data_has_multiple_rows(self):
        """The captured waveform must contain actual data points, not be empty."""
        _, data = standard_csv_to_metadata_and_data(self.csv_path)
        assert len(data) > 0

    def test_data_time_column_is_numeric(self):
        """Time values must be numeric so downstream integration works correctly."""
        _, data = standard_csv_to_metadata_and_data(self.csv_path)
        assert pd.api.types.is_numeric_dtype(data['time (s)'])

    def test_data_voltage_column_is_numeric(self):
        """Voltage values must be numeric so current/polarization calculation works."""
        _, data = standard_csv_to_metadata_and_data(self.csv_path)
        assert pd.api.types.is_numeric_dtype(data['voltage (V)'])

    def test_history_has_one_entry_after_run(self):
        """_update_history() is called once at the end of run_experiment()."""
        assert len(self.loop.history) == 1

    def test_history_entry_is_a_dataframe(self):
        """Each history entry must be a DataFrame containing the measurement metadata."""
        assert isinstance(self.loop.history[0], pd.DataFrame)

    # cleanup verification

    def test_csv_can_be_explicitly_deleted(self):
        """Confirm the output CSV is a normal file that callers can remove."""
        assert os.path.isfile(self.csv_path)
        os.remove(self.csv_path)
        assert not os.path.isfile(self.csv_path)
