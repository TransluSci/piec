"""
Unit, schema, and numerical equivalence tests for in-memory hysteresis processing.

Stage Checkpoint 18: In-memory hysteresis processing.
"""

from pathlib import Path
import tempfile
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from piec.analysis.hysteresis import (
    STANDARD_HYSTERESIS_COLUMNS,
    STANDARD_HYSTERESIS_UNITS,
    HysteresisAnalysisResult,
    plot_hysteresis_iv,
    plot_hysteresis_pv,
    plot_hysteresis_traces,
    process_hysteresis,
    _process_raw_hyst_file,
)
from piec.analysis.utilities import standard_csv_to_metadata_and_data
from tests.fixtures.measurement_compatibility import assert_piec_csv_layout


GOLDEN_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "measurement_compatibility"
    / "hysteresis_loop_golden.csv"
)


@pytest.fixture
def sample_hysteresis_data():
    """Create deterministic in-memory synthetic hysteresis raw data."""
    n_points = 100
    t = np.linspace(0, 0.002, n_points)
    # Triangular excitation voltage waveform
    freq = 1000.0
    v = 2.0 * np.sin(2 * np.pi * freq * t)
    return pd.DataFrame({"time": t, "voltage": v})


@pytest.fixture
def sample_metadata():
    return {
        "frequency": 1000.0,
        "amplitude": 2.0,
        "area": 1e-5,
        "n_cycles": 2,
        "time_offset": 1e-8,
    }


class TestHysteresisProcessing:
    """Tests for in-memory process_hysteresis."""

    def test_process_hysteresis_with_plain_columns(self, sample_hysteresis_data, sample_metadata):
        result = process_hysteresis(sample_hysteresis_data, sample_metadata)
        assert isinstance(result, HysteresisAnalysisResult)

        # Output columns must exactly match the standard plain schema
        assert tuple(result.data.columns) == STANDARD_HYSTERESIS_COLUMNS
        assert len(result.data) == len(sample_hysteresis_data)

        # Output metadata must conform to target schema v1
        assert result.metadata["measurement_schema"] == "hysteresis"
        assert result.metadata["measurement_schema_version"] == 1
        assert result.metadata["column_units"] == STANDARD_HYSTERESIS_UNITS
        assert result.metadata["processed"] is True
        assert result.metadata["frequency"] == 1000.0
        assert result.metadata["amplitude"] == 2.0
        assert result.metadata["area"] == 1e-5
        assert result.metadata["n_cycles"] == 2
        assert result.metadata["r_shunt"] == 50.0
        assert result.time_offset == pytest.approx(1e-8)

    def test_process_hysteresis_rejects_legacy_columns(self, sample_metadata):
        t = np.linspace(0, 0.001, 50)
        v = np.sin(2 * np.pi * 1000.0 * t)
        legacy_df = pd.DataFrame({"time (s)": t, "voltage (V)": v})

        with pytest.raises(KeyError, match="time"):
            process_hysteresis(legacy_df, sample_metadata)

    def test_process_hysteresis_with_explicit_kwargs_overrides_metadata(self, sample_hysteresis_data):
        meta = {
            "frequency": 500.0,
            "amplitude": 1.0,
            "area": 1e-5,
            "n_cycles": 1,
            "time_offset": 0.0,
        }
        # Explicit kwargs override metadata dict
        result = process_hysteresis(
            sample_hysteresis_data,
            meta,
            frequency=2000.0,
            amplitude=3.0,
            n_cycles=4,
            r_shunt=100.0,
        )
        assert result.metadata["frequency"] == 2000.0
        assert result.metadata["amplitude"] == 3.0
        assert result.metadata["n_cycles"] == 4
        assert result.metadata["r_shunt"] == 100.0

    def test_process_hysteresis_numerical_exactness_with_golden(self):
        """Compare in-memory processing against deterministic golden CSV."""
        meta_gold, data_gold = standard_csv_to_metadata_and_data(str(GOLDEN_PATH))

        # Raw input columns from golden
        raw_df = pd.DataFrame({
            "time": data_gold["time (s)"].values,
            "voltage": data_gold["voltage (V)"].values,
        })

        result = process_hysteresis(raw_df, meta_gold)

        # Numerical comparison against golden data
        np.testing.assert_allclose(result.data["time"], data_gold["time (s)"], atol=1e-12)
        np.testing.assert_allclose(result.data["voltage"], data_gold["voltage (V)"], atol=1e-12)
        np.testing.assert_allclose(result.data["current"], data_gold["current (A)"], atol=1e-12)
        np.testing.assert_allclose(result.data["polarization"], data_gold["polarization (uC/cm^2)"], atol=1e-12)
        np.testing.assert_allclose(result.data["applied_voltage"], data_gold["applied voltage (V)"], atol=1e-12)

    def test_result_tuple_unpacking_and_protocol(self, sample_hysteresis_data, sample_metadata):
        result = process_hysteresis(sample_hysteresis_data, sample_metadata)

        # Supports unpacking
        df, meta = result
        assert isinstance(df, pd.DataFrame)
        assert isinstance(meta, dict)
        assert len(result) == 2
        assert result[0] is df
        assert result[1] is meta

        with pytest.raises(IndexError):
            _ = result[2]

        # Immutable dataclass
        with pytest.raises(Exception):
            result.time_offset = 5.0

    def test_input_data_immutability(self, sample_hysteresis_data, sample_metadata):
        orig_cols = list(sample_hysteresis_data.columns)
        orig_t = sample_hysteresis_data["time"].copy()

        _ = process_hysteresis(sample_hysteresis_data, sample_metadata)

        # Original dataframe is not mutated
        assert list(sample_hysteresis_data.columns) == orig_cols
        assert np.array_equal(sample_hysteresis_data["time"], orig_t)

    def test_validation_missing_parameters(self, sample_hysteresis_data):
        with pytest.raises(ValueError, match="Missing required parameter 'frequency'"):
            process_hysteresis(sample_hysteresis_data, amplitude=1.0, area=1e-5, n_cycles=1)

        with pytest.raises(ValueError, match="Missing required parameter 'amplitude'"):
            process_hysteresis(sample_hysteresis_data, frequency=1000.0, area=1e-5, n_cycles=1)

        with pytest.raises(ValueError, match="Missing required parameter 'area'"):
            process_hysteresis(sample_hysteresis_data, frequency=1000.0, amplitude=1.0, n_cycles=1)

        with pytest.raises(ValueError, match="Missing required parameter 'n_cycles'"):
            process_hysteresis(sample_hysteresis_data, frequency=1000.0, amplitude=1.0, area=1e-5)

    def test_validation_invalid_parameter_values(self, sample_hysteresis_data, sample_metadata):
        with pytest.raises(ValueError, match="Frequency must be positive"):
            process_hysteresis(sample_hysteresis_data, sample_metadata, frequency=0.0)

        with pytest.raises(ValueError, match="Area must be positive"):
            process_hysteresis(sample_hysteresis_data, sample_metadata, area=-1e-5)

        with pytest.raises(ValueError, match="n_cycles must be >= 1"):
            process_hysteresis(sample_hysteresis_data, sample_metadata, n_cycles=0)

        with pytest.raises(ValueError, match="r_shunt must be positive"):
            process_hysteresis(sample_hysteresis_data, sample_metadata, r_shunt=0.0)

        with pytest.raises(ValueError, match="Amplitude and time_offset must be finite"):
            process_hysteresis(sample_hysteresis_data, sample_metadata, amplitude=np.nan)

    def test_validation_data_errors(self, sample_metadata):
        # Empty data
        with pytest.raises(ValueError, match="Data must have at least 2 rows"):
            process_hysteresis(pd.DataFrame({"time": [0.0], "voltage": [1.0]}), sample_metadata)

        # Missing columns
        with pytest.raises(KeyError, match="Missing required time column"):
            process_hysteresis(pd.DataFrame({"not_time": [0.0, 1.0], "voltage": [1.0, 2.0]}), sample_metadata)

        with pytest.raises(KeyError, match="Missing required voltage column"):
            process_hysteresis(pd.DataFrame({"time": [0.0, 1.0], "not_voltage": [1.0, 2.0]}), sample_metadata)

        # Non-finite data
        with pytest.raises(ValueError, match="Input data contains non-finite values"):
            process_hysteresis(pd.DataFrame({"time": [0.0, 1.0], "voltage": [1.0, np.nan]}), sample_metadata)

        # Invalid type
        with pytest.raises(TypeError, match="Data must be a DataFrame or Mapping"):
            process_hysteresis([1, 2, 3], sample_metadata)

    def test_auto_timeshift(self, sample_metadata):
        meta_gold, data_gold = standard_csv_to_metadata_and_data(str(GOLDEN_PATH))
        raw_df = pd.DataFrame({
            "time": data_gold["time (s)"].values,
            "voltage": data_gold["voltage (V)"].values,
        })

        res_manual = process_hysteresis(raw_df, meta_gold, auto_timeshift=False)
        assert res_manual.time_offset == pytest.approx(float(meta_gold["time_offset"].values[0]))

        res_auto = process_hysteresis(raw_df, meta_gold, auto_timeshift=True)
        assert res_auto.time_offset != res_manual.time_offset

    def test_negative_time_offset_warning(self, sample_metadata):
        # Time array where polarization peak occurs before nominal max voltage
        t = np.linspace(0, 0.001, 100)
        v = np.zeros_like(t)
        v[2] = 1.0  # early peak
        df = pd.DataFrame({"time": t, "voltage": v})

        with pytest.raises(ValueError, match="Negative time_offset"):
            process_hysteresis(df, sample_metadata, auto_timeshift=True)


class TestHysteresisPlotting:
    """Tests for in-memory plotting functions."""

    def test_plot_hysteresis_pv(self, sample_hysteresis_data, sample_metadata):
        res = process_hysteresis(sample_hysteresis_data, sample_metadata)
        fig, ax = plt.subplots()
        ax_ret = plot_hysteresis_pv(res.data, ax=ax)
        assert ax_ret is ax
        assert ax.get_xlabel() == "Applied Voltage (V)"
        assert ax.get_ylabel() == "Polarization (uC/cm^2)"
        assert len(ax.lines) == 1
        plt.close(fig)

    def test_plot_hysteresis_iv(self, sample_hysteresis_data, sample_metadata):
        res = process_hysteresis(sample_hysteresis_data, sample_metadata)
        fig, ax = plt.subplots()
        ax_ret = plot_hysteresis_iv(res.data, ax=ax)
        assert ax_ret is ax
        assert ax.get_xlabel() == "Applied Voltage (V)"
        assert ax.get_ylabel() == "Current (A)"
        assert len(ax.lines) == 1
        plt.close(fig)

    def test_plot_hysteresis_traces(self, sample_hysteresis_data, sample_metadata):
        res = process_hysteresis(sample_hysteresis_data, sample_metadata)
        fig, ax = plt.subplots()
        ax1, ax2 = plot_hysteresis_traces(res.data, ax=ax)
        assert ax1 is ax
        assert ax1.get_xlabel() == "Time (s)"
        assert "Polarization" in ax1.get_ylabel()
        assert "Applied Voltage" in ax2.get_ylabel()
        plt.close(fig)


class TestProcessRawHystBridge:
    """Verify legacy _process_raw_hyst_file file bridge behavior."""

    def test__process_raw_hyst_file_file_updates_and_plots(self, tmp_path):
        meta_gold, data_gold = standard_csv_to_metadata_and_data(str(GOLDEN_PATH))
        # Copy to temporary path
        from piec.analysis.utilities import metadata_and_data_to_csv
        test_csv = tmp_path / "test_raw_hyst.csv"
        raw_df = pd.DataFrame({
            "time (s)": data_gold["time (s)"].values,
            "voltage (V)": data_gold["voltage (V)"].values,
        })
        metadata_and_data_to_csv(meta_gold, raw_df, str(test_csv))

        # Run bridge with save_plots=True
        res = _process_raw_hyst_file(str(test_csv), show_plots=False, save_plots=True)
        assert isinstance(res, HysteresisAnalysisResult)

        # Verify updated CSV on disk
        updated_meta, updated_data = assert_piec_csv_layout(str(test_csv))
        assert bool(updated_meta.loc[0, "processed"]) is True
        for col in ("time (s)", "voltage (V)", "current (A)", "polarization (uC/cm^2)", "applied voltage (V)"):
            assert col in updated_data.columns

        # Verify plot files generated
        assert (tmp_path / "test_raw_hyst_PV.png").is_file()
        assert (tmp_path / "test_raw_hyst_IV.png").is_file()
        assert (tmp_path / "test_raw_hyst_trace.png").is_file()

@pytest.mark.parametrize('name', ['frequency', 'area', 'r_shunt'])
@pytest.mark.parametrize('value', [np.nan, np.inf, -np.inf])
def test_nonfinite_physical_parameters_rejected(sample_hysteresis_data, sample_metadata, name, value):
    with pytest.raises(ValueError):
        process_hysteresis(sample_hysteresis_data, sample_metadata, **{name: value})

@pytest.mark.parametrize('value', [2.9, True, np.nan, np.inf])
def test_cycle_count_is_integer(sample_hysteresis_data, sample_metadata, value):
    with pytest.raises(ValueError):
        process_hysteresis(sample_hysteresis_data, sample_metadata, n_cycles=value)

@pytest.mark.parametrize('value', [0, -1, 2.5, True])
def test_baseline_count_is_positive_integer(sample_hysteresis_data, sample_metadata, value):
    with pytest.raises(ValueError):
        process_hysteresis(sample_hysteresis_data, sample_metadata, baseline_points=value)

def test_shunt_metadata_and_explicit_precedence(sample_hysteresis_data, sample_metadata):
    default = process_hysteresis(sample_hysteresis_data, sample_metadata)
    meta = dict(sample_metadata, r_shunt=100)
    from_meta = process_hysteresis(sample_hysteresis_data, meta)
    override = process_hysteresis(sample_hysteresis_data, meta, r_shunt=50)
    np.testing.assert_allclose(from_meta.data['current'], default.data['current'] / 2)
    np.testing.assert_allclose(from_meta.data['polarization'], default.data['polarization'] / 2)
    pd.testing.assert_frame_equal(override.data, default.data)

@pytest.mark.parametrize('units', [{'time':'ms','voltage':'mV'}, '{"time":"ms","voltage":"V"}', {'time':'s'}])
def test_incompatible_units_rejected(sample_hysteresis_data, sample_metadata, units):
    with pytest.raises(ValueError, match='column_units'):
        process_hysteresis(sample_hysteresis_data, dict(sample_metadata, column_units=units))

def test_json_units_accepted(sample_hysteresis_data, sample_metadata):
    result = process_hysteresis(sample_hysteresis_data, dict(sample_metadata, column_units='{"time":"s","voltage":"V"}'))
    assert result.metadata['column_units'] == STANDARD_HYSTERESIS_UNITS

@pytest.mark.parametrize('duplicate', [True, False])
def test_nonincreasing_time_rejected(sample_hysteresis_data, sample_metadata, duplicate):
    sample_hysteresis_data.loc[2, 'time'] = sample_hysteresis_data.loc[1 if duplicate else 0, 'time']
    with pytest.raises(ValueError, match='strictly increasing'):
        process_hysteresis(sample_hysteresis_data, sample_metadata)

def test_explicit_negative_offset_rejected(sample_hysteresis_data, sample_metadata):
    with pytest.raises(ValueError, match='Negative time_offset'):
        process_hysteresis(sample_hysteresis_data, sample_metadata, time_offset=-0.0001)

@pytest.mark.parametrize('metadata', [[], pd.DataFrame(), pd.DataFrame([{}, {}])])
def test_metadata_shape_and_type_rejected(sample_hysteresis_data, metadata):
    with pytest.raises((ValueError, TypeError), match='Metadata'):
        process_hysteresis(sample_hysteresis_data, metadata)

def test_file_bridge_is_private():
    import piec.analysis.hysteresis as module
    assert 'process_raw_hyst' not in module.__all__
    assert not hasattr(module, 'process_raw_hyst')
