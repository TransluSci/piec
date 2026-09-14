"""
Contract tests for WaveformReader setup adapter.

Fulfills Checkpoint 7 of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Plain time/voltage arrays with units;
- Finite, equal-length validation;
- Multi-dialect column and channel mapping across oscilloscope drivers.
"""

from unittest.mock import Mock, create_autospec
import numpy as np
import pandas as pd
import pytest

from piec.measurement.adapters import WaveformReader, WaveformRecord
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope


# ============================================================================
# 1. Constructor and Interface Contract Tests
# ============================================================================

class TestWaveformReaderConstructor:
    """Verify WaveformReader initialization, parameter validation, and properties."""

    def test_default_initialization(self):
        scope = Mock()
        scope.get_data = Mock(return_value=pd.DataFrame({"Time": [0.0, 1.0], "Voltage": [2.0, 3.0]}))
        reader = WaveformReader(scope)

        assert reader.oscilloscope is scope
        assert reader.default_channel == 1
        assert reader.time_unit == "s"
        assert reader.voltage_unit == "V"
        assert reader.units == {"time": "s", "voltage": "V"}

    def test_custom_units_and_channel(self):
        scope = Mock()
        reader = WaveformReader(
            scope,
            default_channel=2,
            time_unit="ms",
            voltage_unit="mV",
        )
        assert reader.default_channel == 2
        assert reader.time_unit == "ms"
        assert reader.voltage_unit == "mV"
        assert reader.units == {"time": "ms", "voltage": "mV"}

    def test_none_oscilloscope_rejected(self):
        with pytest.raises(ValueError, match="oscilloscope must not be None"):
            WaveformReader(None)

    @pytest.mark.parametrize("invalid_ch", [0, -1, -5, "1", 1.0, True, False, None])
    def test_invalid_default_channel_rejected(self, invalid_ch):
        scope = Mock()
        with pytest.raises(ValueError, match="default_channel must be a positive integer"):
            WaveformReader(scope, default_channel=invalid_ch)


# ============================================================================
# 2. Return Type and Structure Contracts
# ============================================================================

class TestWaveformReaderReturnContract:
    """Verify DataFrame, tuple array, and WaveformRecord outputs."""

    @pytest.fixture
    def standard_scope(self):
        scope = Mock()
        t = np.array([0.0, 1e-6, 2e-6, 3e-6, 4e-6])
        v = np.array([0.1, 0.5, 1.0, 0.5, 0.1])
        scope.get_data = Mock(return_value=pd.DataFrame({"Time": t, "Voltage": v}))
        return scope

    def test_read_returns_standard_dataframe(self, standard_scope):
        reader = WaveformReader(standard_scope)
        df = reader.read()

        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["time", "voltage"]
        assert len(df) == 5
        assert np.allclose(df["time"], [0.0, 1e-6, 2e-6, 3e-6, 4e-6])
        assert np.allclose(df["voltage"], [0.1, 0.5, 1.0, 0.5, 0.1])

        # Attached attributes
        assert df.attrs["units"] == {"time": "s", "voltage": "V"}
        assert df.attrs["channel"] == 1
        assert df.attrs["sample_count"] == 5

    def test_read_arrays_returns_numpy_floats(self, standard_scope):
        reader = WaveformReader(standard_scope)
        t_arr, v_arr = reader.read_arrays()

        assert isinstance(t_arr, np.ndarray)
        assert isinstance(v_arr, np.ndarray)
        assert t_arr.dtype == np.float64
        assert v_arr.dtype == np.float64
        assert t_arr.ndim == 1
        assert v_arr.ndim == 1
        assert len(t_arr) == 5
        assert len(v_arr) == 5

    def test_read_record_returns_immutable_waveform_record(self, standard_scope):
        reader = WaveformReader(standard_scope)
        record = reader.read_record()

        assert isinstance(record, WaveformRecord)
        assert isinstance(record.data, pd.DataFrame)
        assert list(record.data.columns) == ["time", "voltage"]
        assert record.channel == 1
        assert record.sample_count == 5
        assert record.units == {"time": "s", "voltage": "V"}
        assert np.allclose(record.time, [0.0, 1e-6, 2e-6, 3e-6, 4e-6])
        assert np.allclose(record.voltage, [0.1, 0.5, 1.0, 0.5, 0.1])

        # Subscript access
        assert np.array_equal(record["time"], record.time)
        assert np.array_equal(record["voltage"], record.voltage)
        with pytest.raises(KeyError, match="has no array field"):
            _ = record["invalid"]

        # Metadata dictionary
        meta = record.metadata
        assert meta["channel"] == 1
        assert meta["sample_count"] == 5
        assert meta["time_start"] == pytest.approx(0.0)
        assert meta["time_end"] == pytest.approx(4e-6)
        assert meta["time_step"] == pytest.approx(1e-6)
        assert meta["voltage_min"] == pytest.approx(0.1)
        assert meta["voltage_max"] == pytest.approx(1.0)
        assert meta["voltage_mean"] == pytest.approx(0.44)
        assert meta["voltage_rms"] == pytest.approx(np.sqrt(np.mean(record.voltage**2)))


# ============================================================================
# 3. Channel Selection and Scope Delegation
# ============================================================================

class TestWaveformReaderChannelDelegation:
    """Verify channel configuration on scope and delegation behavior."""

    def test_calls_set_acquisition_channel_if_available(self):
        scope = Mock()
        scope.set_acquisition_channel = Mock()
        scope.get_data = Mock(return_value=pd.DataFrame({"Time": [0, 1], "Voltage": [0, 0]}))

        reader = WaveformReader(scope, default_channel=2)
        reader.read(channel=3)

        scope.set_acquisition_channel.assert_called_once_with(3)

    def test_uses_default_channel_when_channel_is_none(self):
        scope = Mock()
        scope.set_acquisition_channel = Mock()
        scope.get_data = Mock(return_value=pd.DataFrame({"Time": [0, 1], "Voltage": [0, 0]}))

        reader = WaveformReader(scope, default_channel=2)
        df = reader.read()

        scope.set_acquisition_channel.assert_called_once_with(2)
        assert df.attrs["channel"] == 2

    def test_passes_channel_to_get_data_if_supported(self):
        scope = Mock()
        # Create function with explicit channel parameter (e.g. LeCroy SDA6020)
        def mock_get_data(channel=1):
            return pd.DataFrame({"Time": [0, 1], "Voltage": [channel * 10, channel * 10]})

        scope.get_data = mock_get_data
        reader = WaveformReader(scope)
        df = reader.read(channel=4)
        assert np.allclose(df["voltage"], [40, 40])

    @pytest.mark.parametrize("invalid_ch", [0, -1, "1", 2.5, False, True])
    def test_read_rejects_invalid_channel(self, invalid_ch):
        scope = Mock()
        reader = WaveformReader(scope)
        with pytest.raises(ValueError, match="channel must be a positive integer"):
            reader.read(channel=invalid_ch)


# ============================================================================
# 4. Multi-Dialect Column Normalization
# ============================================================================

class TestWaveformReaderDialectNormalization:
    """Verify normalization across various oscilloscope driver output formats."""

    def test_standard_titlecase_time_voltage(self):
        scope = Mock()
        scope.get_data = Mock(return_value=pd.DataFrame({"Time": [0.0, 1.0], "Voltage": [5.0, 6.0]}))
        df = WaveformReader(scope).read()
        assert list(df.columns) == ["time", "voltage"]
        assert np.allclose(df["voltage"], [5.0, 6.0])

    def test_daq_emulator_channel_name(self):
        # daq_to_oscilloscope format: {"Time": ..., f"Channel {ch}": ...}
        scope = Mock()
        scope.get_data = Mock(
            return_value=pd.DataFrame({
                "Time": [0.0, 1.0, 2.0],
                "Channel 1": [1.1, 1.2, 1.3],
                "Channel 2": [2.1, 2.2, 2.3],
            })
        )
        reader = WaveformReader(scope)

        df1 = reader.read(channel=1)
        assert np.allclose(df1["voltage"], [1.1, 1.2, 1.3])

        df2 = reader.read(channel=2)
        assert np.allclose(df2["voltage"], [2.1, 2.2, 2.3])

    def test_voltage_ch_format(self):
        scope = Mock()
        scope.get_data = Mock(
            return_value=pd.DataFrame({
                "time": [0.0, 1.0],
                "Voltage_CH1": [10.0, 20.0],
                "Voltage_CH2": [30.0, 40.0],
            })
        )
        reader = WaveformReader(scope)
        df = reader.read(channel=2)
        assert np.allclose(df["voltage"], [30.0, 40.0])

    def test_two_column_fallback_with_arbitrary_voltage_name(self):
        # Two columns: one recognized as time, other fallback to voltage
        scope = Mock()
        scope.get_data = Mock(return_value=pd.DataFrame({"Time": [0.0, 1.0], "Signal_ADC": [100.0, 200.0]}))
        df = WaveformReader(scope).read()
        assert list(df.columns) == ["time", "voltage"]
        assert np.allclose(df["voltage"], [100.0, 200.0])

    def test_dictionary_input(self):
        scope = Mock()
        scope.get_data = Mock(return_value={"time": [0.0, 0.5], "voltage": [1.5, 2.5]})
        df = WaveformReader(scope).read()
        assert list(df.columns) == ["time", "voltage"]
        assert np.allclose(df["time"], [0.0, 0.5])
        assert np.allclose(df["voltage"], [1.5, 2.5])

    def test_tuple_pair_input(self):
        scope = Mock()
        t = np.array([0.0, 0.1, 0.2])
        v = np.array([3.0, 4.0, 5.0])
        scope.get_data = Mock(return_value=(t, v))
        df = WaveformReader(scope).read()
        assert list(df.columns) == ["time", "voltage"]
        assert np.allclose(df["time"], t)
        assert np.allclose(df["voltage"], v)


# ============================================================================
# 5. Validation and Fault Rejection Tests
# ============================================================================

class TestWaveformReaderValidation:
    """Verify strict validation for finite, equal-length, and numeric arrays."""

    def test_empty_waveform_rejected(self):
        scope = Mock()
        scope.get_data = Mock(return_value=pd.DataFrame({"Time": [], "Voltage": []}))
        with pytest.raises(ValueError, match="empty"):
            WaveformReader(scope).read()

    def test_mismatched_length_rejected(self):
        scope = Mock()
        scope.get_data = Mock(return_value={"time": [0.0, 1.0, 2.0], "voltage": [0.0, 1.0]})
        with pytest.raises(ValueError, match="lengths do not match"):
            WaveformReader(scope).read()

    def test_non_finite_time_rejected(self):
        scope = Mock()
        scope.get_data = Mock(return_value=pd.DataFrame({"Time": [0.0, float("nan"), 2.0], "Voltage": [1.0, 2.0, 3.0]}))
        with pytest.raises(ValueError, match="time array contains non-finite values"):
            WaveformReader(scope).read()

        scope.get_data = Mock(return_value=pd.DataFrame({"Time": [0.0, float("inf"), 2.0], "Voltage": [1.0, 2.0, 3.0]}))
        with pytest.raises(ValueError, match="time array contains non-finite values"):
            WaveformReader(scope).read()

    def test_non_finite_voltage_rejected(self):
        scope = Mock()
        scope.get_data = Mock(return_value=pd.DataFrame({"Time": [0.0, 1.0, 2.0], "Voltage": [1.0, float("nan"), 3.0]}))
        with pytest.raises(ValueError, match="voltage array contains non-finite values"):
            WaveformReader(scope).read()

        scope.get_data = Mock(return_value=pd.DataFrame({"Time": [0.0, 1.0, 2.0], "Voltage": [1.0, float("-inf"), 3.0]}))
        with pytest.raises(ValueError, match="voltage array contains non-finite values"):
            WaveformReader(scope).read()

    def test_non_numeric_data_rejected(self):
        scope = Mock()
        scope.get_data = Mock(return_value=pd.DataFrame({"Time": ["0", "1"], "Voltage": ["not_a_number", "2"]}))
        with pytest.raises(TypeError, match="Failed to convert"):
            WaveformReader(scope).read()

    def test_multidimensional_array_rejected(self):
        scope = Mock()
        t = np.array([[0.0, 1.0], [2.0, 3.0]])
        v = np.array([[0.0, 1.0], [2.0, 3.0]])
        scope.get_data = Mock(return_value=(t, v))
        with pytest.raises(ValueError, match="must be 1-dimensional"):
            WaveformReader(scope).read()

    def test_missing_time_column_rejected(self):
        scope = Mock()
        scope.get_data = Mock(return_value=pd.DataFrame({"ColA": [1, 2], "ColB": [3, 4], "ColC": [5, 6]}))
        with pytest.raises(ValueError, match="Unable to locate a time column"):
            WaveformReader(scope).read()

    def test_missing_channel_voltage_rejected(self):
        scope = Mock()
        # Multi-channel without generic fallback
        scope.get_data = Mock(
            return_value=pd.DataFrame({
                "Time": [0.0, 1.0],
                "Channel 1": [1.0, 2.0],
                "Channel 2": [3.0, 4.0],
            })
        )
        with pytest.raises(ValueError, match="Unable to locate a voltage column for channel 3"):
            WaveformReader(scope).read(channel=3)

    def test_scope_lacking_get_data_rejected(self):
        scope = object()
        with pytest.raises(AttributeError, match="does not have a callable get_data method"):
            WaveformReader(scope)

    def test_scope_returning_none_rejected(self):
        scope = Mock()
        scope.get_data = Mock(return_value=None)
        with pytest.raises(ValueError, match="returned None"):
            WaveformReader(scope).read()


# ============================================================================
# 6. Real Driver Integration
# ============================================================================

class TestWaveformReaderDriverIntegration:
    """Verify WaveformReader works cleanly with concrete drivers."""

    def test_virtual_oscilloscope_integration(self):
        v_scope = VirtualScope(simulation_points=50)
        t = np.linspace(0, 1e-3, 50)
        v = np.sin(2 * np.pi * 1000 * t)
        v_scope.sample.apply_waveform(v, t)

        reader = WaveformReader(v_scope, default_channel=1)

        df = reader.read()
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["time", "voltage"]
        assert len(df) > 0
        assert np.all(np.isfinite(df["time"]))
        assert np.all(np.isfinite(df["voltage"]))
        assert df.attrs["units"] == {"time": "s", "voltage": "V"}
        assert df.attrs["channel"] == 1

        record = reader.read_record()
        assert isinstance(record, WaveformRecord)
        assert record.sample_count == len(df)
        assert record.metadata["channel"] == 1


# ============================================================================
# 7. Regression Tests: Channel Isolation & Single-Call Exception Propagation
# ============================================================================

class TestWaveformReaderRegressions:
    """
    Regression tests verifying:
    1. Strict channel isolation: tables with conflicting channel columns reject wrong-channel
       reads and never fall back to generic voltage or leftover columns.
    2. Exact exception propagation: scope errors (TypeError, ValueError, RuntimeError)
       propagate directly after exactly one call, without catch-and-retry masking.
    """

    @pytest.mark.parametrize(
        "table_data,requested_channel",
        [
            (pd.DataFrame({"Time": [0.0, 1.0], "Channel 2": [10.0, 20.0]}), 1),
            (pd.DataFrame({"Time": [0.0, 1.0], "Voltage_CH2": [10.0, 20.0]}), 1),
            (pd.DataFrame({"Time": [0.0, 1.0], "CH2": [10.0, 20.0]}), 1),
            (pd.DataFrame({"Time": [0.0, 1.0], "C2": [10.0, 20.0]}), 1),
            (pd.DataFrame({"Time": [0.0, 1.0], "Voltage (CH2)": [10.0, 20.0]}), 1),
            (pd.DataFrame({"Time": [0.0, 1.0], "CH 2 [V]": [10.0, 20.0]}), 1),
            (pd.DataFrame({"Time": [0.0, 1.0], "Voltage": [5.0, 6.0], "Channel 2": [10.0, 20.0]}), 1),
            (pd.DataFrame({"Time": [0.0, 1.0], "Channel 1": [1.0, 2.0], "Channel 2": [3.0, 4.0]}), 3),
            ({"Time": [0.0, 1.0], "chan 2": [10.0, 20.0]}, 1),
        ],
    )
    def test_wrong_channel_table_rejected(self, table_data, requested_channel):
        scope = Mock()
        scope.get_data = Mock(return_value=table_data)
        reader = WaveformReader(scope, default_channel=requested_channel)

        with pytest.raises(ValueError, match=f"Unable to locate a voltage column for channel {requested_channel}"):
            reader.read(channel=requested_channel)

    def test_correct_channel_selected_when_multiple_channels_present(self):
        df = pd.DataFrame({
            "Time": [0.0, 1.0],
            "Channel 1": [1.0, 2.0],
            "Channel 2": [3.0, 4.0],
        })
        scope = Mock()
        scope.get_data = Mock(return_value=df)
        reader = WaveformReader(scope)

        df1 = reader.read(channel=1)
        assert np.allclose(df1["voltage"], [1.0, 2.0])

        df2 = reader.read(channel=2)
        assert np.allclose(df2["voltage"], [3.0, 4.0])

    @pytest.mark.parametrize(
        "exc_factory",
        [
            lambda: TypeError("transport serialization type error"),
            lambda: ValueError("acquisition timeout or malformed header"),
            lambda: RuntimeError("visa comm hardware timeout"),
        ],
    )
    def test_acquisition_exception_propagates_after_single_read_with_channel_param(self, exc_factory):
        # Scope whose get_data has a 'channel' parameter (e.g. LeCroy SDA6020 style)
        mock_fn = Mock(side_effect=exc_factory())
        def mock_get_data(channel=1):
            return mock_fn(channel=channel)

        scope = Mock()
        scope.get_data = mock_get_data

        reader = WaveformReader(scope, default_channel=1)

        with pytest.raises(Exception) as exc_info:
            reader.read(channel=1)

        assert isinstance(exc_info.value, (TypeError, ValueError, RuntimeError))
        assert mock_fn.call_count == 1

    @pytest.mark.parametrize(
        "exc_factory",
        [
            lambda: TypeError("low level byte decode error"),
            lambda: ValueError("unexpected packet length"),
            lambda: ConnectionError("device disconnected"),
        ],
    )
    def test_acquisition_exception_propagates_after_single_read_without_channel_param(self, exc_factory):
        # Scope whose get_data does not have a 'channel' parameter (standard SCPI scope style)
        mock_fn = Mock(side_effect=exc_factory())
        def mock_get_data():
            return mock_fn()

        scope = Mock()
        scope.get_data = mock_get_data

        reader = WaveformReader(scope, default_channel=1)

        with pytest.raises(Exception) as exc_info:
            reader.read(channel=1)

        assert isinstance(exc_info.value, (TypeError, ValueError, ConnectionError))
        assert mock_fn.call_count == 1
