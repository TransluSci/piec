"""
Unit, schema, and numerical equivalence tests for in-memory PUND processing.

Stage Checkpoint 19: In-memory PUND processing.
"""

from pathlib import Path
import tempfile
import json

import matplotlib
matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from piec.analysis.pund import (
    STANDARD_PUND_COLUMNS,
    STANDARD_PUND_UNITS,
    PundAnalysisResult,
    plot_pund_components,
    plot_pund_delta_p,
    plot_pund_traces,
    process_pund,
)
from piec.analysis.utilities import standard_csv_to_metadata_and_data, metadata_and_data_to_csv


@pytest.fixture
def sample_pund_data(sample_metadata):
    """Create deterministic in-memory synthetic PUND raw data."""
    t = np.linspace(0, 0.007, 701)
    v = np.zeros_like(t)
    v[(t >= 0.001) & (t < 0.002)] = -sample_metadata["reset_amp"]
    v[(t >= 0.003) & (t < 0.004)] = sample_metadata["p_u_amp"]
    v[(t >= 0.005) & (t <= 0.006)] = sample_metadata["p_u_amp"]
    return pd.DataFrame({
        "time": t,
        "voltage": v,
    })


@pytest.fixture
def sample_metadata():
    return {
        "reset_amp": 1.0,
        "reset_width": 0.001,
        "reset_delay": 0.001,
        "p_u_amp": 1.0,
        "p_u_width": 0.001,
        "p_u_delay": 0.001,
        "offset": 0.0,
        "area": 1e-5,
        "time_offset": 1e-8,
        "length": 0.006,
    }


class TestPundProcessing:
    """Tests for in-memory process_pund."""

    def test_process_pund_with_plain_columns(self, sample_pund_data, sample_metadata):
        result = process_pund(sample_pund_data, sample_metadata)
        assert isinstance(result, PundAnalysisResult)

        # Output columns must exactly match the standard plain schema
        assert tuple(result.data.columns) == STANDARD_PUND_COLUMNS
        assert len(result.data) == len(sample_pund_data)

        # Output metadata must conform to target schema v1
        assert result.metadata["measurement_schema"] == "three_pulse_pund"
        assert result.metadata["measurement_schema_version"] == 1
        assert result.metadata["column_units"] == STANDARD_PUND_UNITS
        assert result.metadata["processed"] is True
        assert result.metadata["reset_amp"] == 1.0
        assert result.metadata["reset_width"] == 0.001
        assert result.metadata["reset_delay"] == 0.001
        assert result.metadata["p_u_amp"] == 1.0
        assert result.metadata["p_u_width"] == 0.001
        assert result.metadata["p_u_delay"] == 0.001
        assert result.metadata["area"] == 1e-5
        assert result.metadata["length"] == 0.006
        assert result.metadata["r_shunt"] == 50.0
        assert result.time_offset > 0

    def test_process_pund_rejects_legacy_columns(self, sample_metadata):
        t = np.linspace(0, 0.006, 50)
        v = np.zeros_like(t)
        legacy_df = pd.DataFrame({"time (s)": t, "voltage (V)": v})

        with pytest.raises(KeyError, match="time"):
            process_pund(legacy_df, sample_metadata)

    def test_process_pund_with_explicit_kwargs_overrides_metadata(self, sample_pund_data):
        meta = {
            "reset_amp": 1.0,
            "reset_width": 0.001,
            "reset_delay": 0.001,
            "p_u_amp": 1.0,
            "p_u_width": 0.001,
            "p_u_delay": 0.001,
            "area": 1e-5,
            "length": 0.006,
            "time_offset": 0.0,
        }
        # Explicit kwargs override metadata dict
        result = process_pund(
            sample_pund_data,
            meta,
            reset_amp=2.0,
            p_u_amp=1.5,
            r_shunt=100.0,
            area=2e-5,
        )
        assert result.metadata["reset_amp"] == 2.0
        assert result.metadata["p_u_amp"] == 1.5
        assert result.metadata["r_shunt"] == 100.0
        assert result.metadata["area"] == 2e-5

    def test_process_pund_numerical_consistency(self, sample_pund_data, sample_metadata):
        """Verify internal consistency of in-memory PUND processing."""
        result = process_pund(sample_pund_data, sample_metadata)
        assert len(result.data) == len(sample_pund_data)
        assert set(STANDARD_PUND_COLUMNS).issubset(result.data.columns)
        assert np.all(np.isfinite(result.data["polarization"]))
        assert np.isfinite(result.time_offset)
        assert result.time_offset >= 0.0

    def test_result_tuple_unpacking_and_protocol(self, sample_pund_data, sample_metadata):
        result = process_pund(sample_pund_data, sample_metadata)

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

    def test_input_data_immutability(self, sample_pund_data, sample_metadata):
        orig_cols = list(sample_pund_data.columns)
        orig_t = sample_pund_data["time"].copy()

        _ = process_pund(sample_pund_data, sample_metadata)

        # Original dataframe is not mutated
        assert list(sample_pund_data.columns) == orig_cols
        assert np.array_equal(sample_pund_data["time"], orig_t)

    def test_validation_missing_parameters(self, sample_pund_data):
        valid = {
            "reset_amp": 1.0,
            "reset_width": 0.001,
            "reset_delay": 0.001,
            "p_u_amp": 1.0,
            "p_u_width": 0.001,
            "p_u_delay": 0.001,
            "area": 1e-5,
        }
        for key in valid:
            params = dict(valid)
            del params[key]
            with pytest.raises(ValueError, match=f"Missing required parameter '{key}'"):
                process_pund(sample_pund_data, **params)

    def test_validation_invalid_parameter_values(self, sample_pund_data, sample_metadata):
        with pytest.raises(ValueError, match="reset_width must be positive"):
            process_pund(sample_pund_data, sample_metadata, reset_width=0.0)

        with pytest.raises(ValueError, match="reset_delay must be positive"):
            process_pund(sample_pund_data, sample_metadata, reset_delay=-0.001)

        with pytest.raises(ValueError, match="p_u_width must be positive"):
            process_pund(sample_pund_data, sample_metadata, p_u_width=0.0)

        with pytest.raises(ValueError, match="p_u_delay must be positive"):
            process_pund(sample_pund_data, sample_metadata, p_u_delay=-0.001)

        with pytest.raises(ValueError, match="area must be positive"):
            process_pund(sample_pund_data, sample_metadata, area=-1e-5)

        with pytest.raises(ValueError, match="r_shunt must be positive"):
            process_pund(sample_pund_data, sample_metadata, r_shunt=0.0)

        with pytest.raises(ValueError, match="Amplitudes and offset must be finite"):
            process_pund(sample_pund_data, sample_metadata, reset_amp=np.nan)

        with pytest.raises(ValueError, match="Amplitudes and offset must be finite"):
            process_pund(sample_pund_data, sample_metadata, p_u_amp=np.inf)

    def test_validation_data_errors(self, sample_metadata):
        # Empty data
        with pytest.raises(ValueError, match="Data must have at least 2 rows"):
            process_pund(pd.DataFrame({"time": [0.0], "voltage": [1.0]}), sample_metadata)

        # Missing columns
        with pytest.raises(KeyError, match="Missing required time column"):
            process_pund(pd.DataFrame({"not_time": [0.0, 1.0], "voltage": [1.0, 2.0]}), sample_metadata)

        with pytest.raises(KeyError, match="Missing required voltage column"):
            process_pund(pd.DataFrame({"time": [0.0, 1.0], "not_voltage": [1.0, 2.0]}), sample_metadata)

        # Non-finite data
        with pytest.raises(ValueError, match="Input data contains non-finite values"):
            process_pund(pd.DataFrame({"time": [0.0, 1.0], "voltage": [1.0, np.nan]}), sample_metadata)

        # Invalid type
        with pytest.raises(TypeError, match="Data must be a DataFrame or Mapping"):
            process_pund([1, 2, 3], sample_metadata)

    def test_auto_timeshift(self, sample_pund_data, sample_metadata):
        res_auto = process_pund(sample_pund_data, sample_metadata, auto_timeshift=True)
        res_manual = process_pund(sample_pund_data, sample_metadata, auto_timeshift=False, time_offset=1e-8)
        assert res_auto.time_offset > res_manual.time_offset

    def test_negative_time_offset_rejected(self, sample_pund_data, sample_metadata):
        with pytest.raises(ValueError, match="Negative time_offset"):
            process_pund(sample_pund_data, sample_metadata, time_offset=-0.001, auto_timeshift=False)

    def test_insufficient_pulse_points_rejected(self, sample_metadata):
        # Waveform only covers 0.0005 s, whereas PUND requires > 0.004 s
        t = np.linspace(0, 0.0005, 10)
        v = np.zeros_like(t)
        df = pd.DataFrame({"time": t, "voltage": v})
        with pytest.raises(ValueError, match="Captured waveform does not contain sufficient points"):
            process_pund(df, sample_metadata, auto_timeshift=False)


class TestPundPlotting:
    """Tests for in-memory plotting functions."""

    @pytest.fixture(autouse=True)
    def _force_agg(self):
        matplotlib.use("Agg", force=True)
        yield

    def test_plot_pund_delta_p(self, sample_pund_data, sample_metadata):
        res = process_pund(sample_pund_data, sample_metadata)
        fig, ax = plt.subplots()
        ax_ret = plot_pund_delta_p(res.data, ax=ax)
        assert ax_ret is ax
        assert ax.get_xlabel() == "Time (s)"
        assert "Delta Polarization" in ax.get_ylabel()
        assert len(ax.lines) == 1
        plt.close(fig)

    def test_plot_pund_traces(self, sample_pund_data, sample_metadata):
        res = process_pund(sample_pund_data, sample_metadata)
        fig, ax = plt.subplots()
        ax1, ax2 = plot_pund_traces(res.data, ax=ax)
        assert ax1 is ax
        assert ax1.get_xlabel() == "Time (s)"
        assert "Current" in ax1.get_ylabel()
        assert "Applied Voltage" in ax2.get_ylabel()
        plt.close(fig)

    def test_plot_pund_components(self, sample_pund_data, sample_metadata):
        res = process_pund(sample_pund_data, sample_metadata)
        fig, ax = plt.subplots()
        ax_ret = plot_pund_components(res.data, ax=ax)
        assert ax_ret is ax
        assert ax.get_xlabel() == "Time (s)"
        assert ax.get_ylabel() == "Polarization (uC/cm^2)"
        assert len(ax.lines) == 4
        plt.close(fig)


def test_legacy_file_bridge_retired():
    """Verify legacy _process_raw_3pp_file file bridge is fully retired."""
    import piec.analysis.pund as module
    assert not hasattr(module, "_process_raw_3pp_file")
    assert not hasattr(module, "process_raw_3pp")


@pytest.mark.parametrize("name", ["reset_width", "reset_delay", "p_u_width", "p_u_delay", "area", "r_shunt", "length"])
@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_nonfinite_physical_parameters_rejected(sample_pund_data, sample_metadata, name, value):
    with pytest.raises(ValueError):
        process_pund(sample_pund_data, sample_metadata, **{name: value})


def test_shunt_metadata_and_explicit_precedence(sample_pund_data, sample_metadata):
    default = process_pund(sample_pund_data, sample_metadata)
    meta = dict(sample_metadata, r_shunt=100.0)
    from_meta = process_pund(sample_pund_data, meta)
    override = process_pund(sample_pund_data, meta, r_shunt=50.0)
    np.testing.assert_allclose(from_meta.data["current"], default.data["current"] / 2)
    np.testing.assert_allclose(from_meta.data["polarization"], default.data["polarization"] / 2)
    pd.testing.assert_frame_equal(override.data, default.data)


@pytest.mark.parametrize("units", [{"time": "ms", "voltage": "mV"}, '{"time":"ms","voltage":"V"}', {"time": "s"}])
def test_incompatible_units_rejected(sample_pund_data, sample_metadata, units):
    with pytest.raises(ValueError, match="column_units"):
        process_pund(sample_pund_data, dict(sample_metadata, column_units=units))


def test_json_units_accepted(sample_pund_data, sample_metadata):
    result = process_pund(sample_pund_data, dict(sample_metadata, column_units='{"time":"s","voltage":"V"}'))
    assert result.metadata["column_units"] == STANDARD_PUND_UNITS


@pytest.mark.parametrize("duplicate", [True, False])
def test_nonincreasing_time_rejected(sample_pund_data, sample_metadata, duplicate):
    sample_pund_data.loc[2, "time"] = sample_pund_data.loc[1 if duplicate else 0, "time"]
    with pytest.raises(ValueError, match="strictly increasing"):
        process_pund(sample_pund_data, sample_metadata)


def test_explicit_negative_offset_rejected(sample_pund_data, sample_metadata):
    with pytest.raises(ValueError, match="Negative time_offset"):
        process_pund(sample_pund_data, sample_metadata, time_offset=-0.0001, auto_timeshift=False)


@pytest.mark.parametrize("metadata", [[], pd.DataFrame(), pd.DataFrame([{}, {}])])
def test_metadata_shape_and_type_rejected(sample_pund_data, metadata):
    with pytest.raises((ValueError, TypeError), match="Metadata"):
        process_pund(sample_pund_data, metadata)


@pytest.mark.parametrize('value', ['False', 'True', 0, 1, [], float('nan')])
def test_auto_timeshift_requires_boolean(sample_pund_data, sample_metadata, value):
    with pytest.raises(ValueError, match='boolean'):
        process_pund(sample_pund_data, sample_metadata, auto_timeshift=value)

@pytest.mark.parametrize('automatic', [False, True])
def test_offset_outside_capture_is_validation_error(sample_pund_data, sample_metadata, automatic):
    data = sample_pund_data.assign(voltage=0.0)
    with pytest.raises(ValueError, match='captured time range'):
        process_pund(data, sample_metadata, auto_timeshift=automatic, time_offset=1.0)

@pytest.mark.parametrize('automatic', [False, True])
def test_truncated_last_interval_rejected(sample_pund_data, sample_metadata, automatic):
    data = sample_pund_data[sample_pund_data.time < .0052].assign(voltage=0.0)
    with pytest.raises(ValueError, match='full PUND sequence'):
        process_pund(data, sample_metadata, auto_timeshift=automatic, time_offset=0)

def test_dc_offset_changes_only_applied_voltage(sample_pund_data, sample_metadata):
    base = process_pund(sample_pund_data, sample_metadata, offset=0)
    shifted = process_pund(sample_pund_data, sample_metadata, offset=2)
    np.testing.assert_allclose(shifted.data.applied_voltage, base.data.applied_voltage + 2)
    pd.testing.assert_frame_equal(shifted.data.drop(columns='applied_voltage'), base.data.drop(columns='applied_voltage'))
    assert shifted.metadata['offset'] == 2

def test_manual_alignment_selects_expected_polarization_windows(sample_metadata):
    # Known nonlinear integral makes incorrect window placement observable.
    t = np.linspace(0, .008, 801)
    data = pd.DataFrame({'time': t, 'voltage': t ** 2})
    delay = .001
    result = process_pund(data, sample_metadata, auto_timeshift=False, time_offset=delay)
    p = result.data.polarization.to_numpy()
    bounds = np.searchsorted(t - delay, [.002, .003, .004, .005, .006])
    ph, phr, ps, psr = [p[a:b] for a,b in zip(bounds[:-1], bounds[1:])]
    size = min(len(ph), len(ps)); rem = min(len(phr), len(psr))
    expected = np.r_[ph[:size], phr[:rem]] - np.r_[ps[:size], psr[:rem]]
    expected -= expected[0]
    np.testing.assert_allclose(result.data.delta_polarization.iloc[:len(expected)], expected)
    unshifted = process_pund(data, sample_metadata, auto_timeshift=False, time_offset=0)
    assert not np.allclose(result.data.delta_polarization, unshifted.data.delta_polarization, atol=1e-14, rtol=1e-8)

def test_no_peak_fallback_matches_manual_alignment(sample_metadata):
    t = np.linspace(0, .008, 801)
    data = pd.DataFrame({'time': t, 'voltage': t ** 2})
    manual = process_pund(data, sample_metadata, auto_timeshift=False, time_offset=.001)
    automatic = process_pund(data, sample_metadata, auto_timeshift=True, time_offset=.001)
    pd.testing.assert_frame_equal(manual.data, automatic.data)
    assert automatic.time_offset == manual.time_offset
