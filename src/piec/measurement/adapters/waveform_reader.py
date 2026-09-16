"""
WaveformReader setup adapter for standardizing oscilloscope reads.

Normalizes diverse oscilloscope driver output formats (DataFrame, dict, tuple of arrays)
into plain 'time' and 'voltage' arrays with explicit unit metadata, finite numeric validation,
and channel mapping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
import inspect
from typing import Any, Dict, Optional, Set, Tuple, Union

import numpy as np
import pandas as pd

from piec.drivers.oscilloscope.oscilloscope import Oscilloscope

# Pattern matching channel-specific column headers:
# e.g., 'Channel 1', 'Channel_1', 'CH1', 'CH 1', 'Voltage_CH1', 'Voltage (CH1)', 'C1', 'CHAN1', 'Ch. 1'
_CHANNEL_COLUMN_PATTERN = re.compile(
    r"^(?:voltage[_\s\-:\.]*)?(?:[\(\[])?(?:channel|chan|ch|c)[_\s\-:\.]*(\d+)(?:[\)\]])?(?:\s*[\(\[].*?[\)\]])?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WaveformRecord:
    """
    Immutable representation of an acquired waveform.

    Attributes:
        data: DataFrame containing exactly 'time' and 'voltage' columns.
        time: 1D numpy array of sample timestamps.
        voltage: 1D numpy array of measured voltages.
        units: Dictionary mapping column names to units (e.g. {'time': 's', 'voltage': 'V'}).
        channel: Physical or logical oscilloscope channel number.
        sample_count: Number of points in the waveform.
        metadata: Acquisition metrics (timing step, extrema, rms).
    """

    data: pd.DataFrame
    time: np.ndarray
    voltage: np.ndarray
    units: Dict[str, str]
    channel: int
    sample_count: int
    metadata: Dict[str, Any]

    def __getitem__(self, key: str) -> np.ndarray:
        """Allow subscript access to 'time' or 'voltage' arrays."""
        if key == "time":
            return self.time
        elif key == "voltage":
            return self.voltage
        raise KeyError(f"WaveformRecord has no array field {key!r}; use 'time' or 'voltage'")


class WaveformReader:
    """
    Setup adapter that encapsulates an oscilloscope driver and standardizes waveform retrieval.

    In accordance with Section 9.4 of MEASUREMENT_STANDARDIZATION_PLAN.md:
    - Returns exactly 'time' and 'voltage' for a requested channel.
    - Maps driver-specific 'Time', 'Voltage', 'Voltage_CH{channel}', or 'Channel {channel}' fields.
    - Validates finite, numeric, equal-length arrays.
    - Records actual channel, units, and sample metadata.
    """

    def __init__(
        self,
        oscilloscope: Oscilloscope,
        default_channel: int = 1,
        time_unit: str = "s",
        voltage_unit: str = "V",
    ):
        """
        Initializes the WaveformReader adapter.

        Args:
            oscilloscope: An oscilloscope driver or emulator instance implementing get_data().
            default_channel: Default channel to acquire if not explicitly specified.
            time_unit: Declared physical unit for time axis (default 's').
            voltage_unit: Declared physical unit for voltage axis (default 'V').
        """
        if oscilloscope is None:
            raise ValueError("oscilloscope must not be None")
        if not isinstance(default_channel, int) or isinstance(default_channel, bool) or default_channel <= 0:
            raise ValueError(f"default_channel must be a positive integer, got {default_channel!r}")

        self.oscilloscope = oscilloscope
        self.default_channel = int(default_channel)
        self.time_unit = str(time_unit)
        self.voltage_unit = str(voltage_unit)

        # Inspect get_data signature once during initialization, completely
        # separate from acquisition execution to avoid catch-and-retry hazards.
        self._get_data_takes_channel = self._inspect_get_data_signature()

    @property
    def units(self) -> Dict[str, str]:
        """Declared units dictionary mapping 'time' and 'voltage' to physical units."""
        return {"time": self.time_unit, "voltage": self.voltage_unit}

    def _validate_channel(self, channel: Optional[int]) -> int:
        if channel is None:
            return self.default_channel
        if not isinstance(channel, int) or isinstance(channel, bool) or channel <= 0:
            raise ValueError(f"channel must be a positive integer, got {channel!r}")
        return int(channel)

    def _inspect_get_data_signature(self) -> bool:
        """Inspects whether oscilloscope.get_data accepts a 'channel' keyword argument."""
        get_data = getattr(self.oscilloscope, "get_data", None)
        if not callable(get_data):
            raise AttributeError(
                f"Oscilloscope {self.oscilloscope!r} does not have a callable get_data method"
            )
        try:
            sig = inspect.signature(get_data)
            return "channel" in sig.parameters
        except (ValueError, TypeError):
            # Built-in or C-level callable without inspectable signature
            return False

    def _fetch_raw_data(self, channel: int) -> Any:
        """Configures channel on scope if supported, then retrieves raw data in exactly one call."""
        # 1. Setup channel on oscilloscope if supported
        set_channel = getattr(self.oscilloscope, "set_acquisition_channel", None)
        if callable(set_channel):
            set_channel(channel)

        # 2. Exactly one read call; acquisition exceptions propagate directly
        if self._get_data_takes_channel:
            return self.oscilloscope.get_data(channel=channel)
        return self.oscilloscope.get_data()

    @staticmethod
    def _find_time_column(columns: list[str]) -> Optional[str]:
        """Identifies time column name from list of available columns."""
        col_map = {c.strip().lower(): c for c in columns}
        # Exact priorities
        for candidate in ("time", "t", "time (s)", "time(s)", "times"):
            if candidate in col_map:
                return col_map[candidate]
        # Partial match
        for key, orig in col_map.items():
            if key.startswith("time") or key.startswith("t_"):
                return orig
        return None

    @classmethod
    def _find_voltage_column(cls, columns: list[str], channel: int, time_col: Optional[str]) -> Optional[str]:
        """
        Identifies voltage column name for requested channel from list of available columns.

        Enforces strict channel isolation:
        - Columns matching the requested channel are selected.
        - Tables containing columns for conflicting channels (e.g. 'Channel 2' when channel 1
          was requested) reject wrong-channel selection and will not fall back to generic names
          or arbitrary remaining columns.
        """
        # 1. First, search for columns that explicitly match the requested channel
        for col in columns:
            if col == time_col:
                continue
            match = _CHANNEL_COLUMN_PATTERN.match(col.strip())
            if match and int(match.group(1)) == channel:
                return col

        # 2. Detect if any column explicitly declares a conflicting channel
        conflicting_channels: Set[int] = set()
        for col in columns:
            if col == time_col:
                continue
            match = _CHANNEL_COLUMN_PATTERN.match(col.strip())
            if match:
                ch_num = int(match.group(1))
                if ch_num != channel:
                    conflicting_channels.add(ch_num)

        # If columns for other channels exist, this table has explicit channel labeling.
        # Since requested channel was not found, do NOT fall back to generic or remaining columns.
        if conflicting_channels:
            return None

        # 3. Generic voltage candidates (only valid when no conflicting channel columns exist)
        col_map = {c.strip().lower(): c for c in columns if c != time_col}
        generic_patterns = [
            "voltage",
            "v",
            "volt",
            "voltages",
            "voltage (v)",
            "voltage(v)",
        ]
        for pat in generic_patterns:
            if pat in col_map:
                return col_map[pat]

        # 4. Two-column fallback: if exactly 2 columns and one is time, the other is voltage
        remaining = [c for c in columns if c != time_col]
        if len(remaining) == 1:
            return remaining[0]

        return None

    def _normalize_raw_data(self, raw_data: Any, channel: int) -> Tuple[np.ndarray, np.ndarray]:
        """
        Extracts and converts raw scope output into numpy float64 (time, voltage) arrays.
        """
        if raw_data is None:
            raise ValueError("Oscilloscope get_data() returned None")

        time_data = None
        voltage_data = None

        # Case 1: DataFrame or Mapping
        if isinstance(raw_data, (pd.DataFrame, dict)) or hasattr(raw_data, "keys"):
            if isinstance(raw_data, pd.DataFrame):
                cols = list(raw_data.columns)
            else:
                cols = list(raw_data.keys())

            if len(cols) == 0:
                raise ValueError("Waveform table returned by oscilloscope is empty (no columns)")

            time_col = self._find_time_column(cols)
            if time_col is None:
                raise ValueError(
                    f"Unable to locate a time column in oscilloscope data. Available columns: {cols}"
                )

            voltage_col = self._find_voltage_column(cols, channel, time_col)
            if voltage_col is None:
                raise ValueError(
                    f"Unable to locate a voltage column for channel {channel} in oscilloscope data. "
                    f"Available columns: {cols}"
                )

            time_data = raw_data[time_col]
            voltage_data = raw_data[voltage_col]

        # Case 2: Tuple or List of 2 items (e.g. (times, voltages))
        elif isinstance(raw_data, (tuple, list)) and len(raw_data) == 2:
            time_data, voltage_data = raw_data

        else:
            raise TypeError(
                f"Unsupported oscilloscope get_data() return type {type(raw_data).__name__}; "
                "expected DataFrame, dict, or (time, voltage) pair."
            )

        # Convert to numpy arrays of float64
        try:
            time_arr = np.asarray(time_data, dtype=np.float64)
        except (ValueError, TypeError) as exc:
            raise TypeError(f"Failed to convert waveform time data to numeric float array: {exc}") from exc

        try:
            voltage_arr = np.asarray(voltage_data, dtype=np.float64)
        except (ValueError, TypeError) as exc:
            raise TypeError(f"Failed to convert waveform voltage data to numeric float array: {exc}") from exc

        # Dimensionality check: must be 1D
        if time_arr.ndim != 1:
            raise ValueError(f"Waveform time array must be 1-dimensional, got shape {time_arr.shape}")
        if voltage_arr.ndim != 1:
            raise ValueError(f"Waveform voltage array must be 1-dimensional, got shape {voltage_arr.shape}")

        # Length validation
        if len(time_arr) == 0:
            raise ValueError("Waveform data is empty (0 samples)")
        if len(time_arr) != len(voltage_arr):
            raise ValueError(
                f"Waveform array lengths do not match: time has {len(time_arr)} samples, "
                f"voltage has {len(voltage_arr)} samples"
            )

        # Finite validation
        if not np.all(np.isfinite(time_arr)):
            raise ValueError("Waveform time array contains non-finite values (NaN, Inf, or -Inf)")
        if not np.all(np.isfinite(voltage_arr)):
            raise ValueError("Waveform voltage array contains non-finite values (NaN, Inf, or -Inf)")

        return time_arr, voltage_arr

    def read_arrays(self, channel: Optional[int] = None) -> Tuple[np.ndarray, np.ndarray]:
        """
        Acquires and returns the validated 1D float arrays (time, voltage) for the channel.

        Args:
            channel: Target oscilloscope channel (defaults to self.default_channel).

        Returns:
            Tuple[np.ndarray, np.ndarray]: (time_array, voltage_array) in float64.
        """
        ch = self._validate_channel(channel)
        raw = self._fetch_raw_data(ch)
        return self._normalize_raw_data(raw, ch)

    def read(self, channel: Optional[int] = None) -> pd.DataFrame:
        """
        Acquires and returns a standardized pandas DataFrame with 'time' and 'voltage' columns.

        The returned DataFrame contains:
        - Exact column names: 'time', 'voltage'
        - Attribute df.attrs['units'] = {'time': time_unit, 'voltage': voltage_unit}
        - Attribute df.attrs['channel'] = channel
        - Attribute df.attrs['sample_count'] = len(df)

        Args:
            channel: Target oscilloscope channel (defaults to self.default_channel).

        Returns:
            pd.DataFrame: Standardized 2-column DataFrame.
        """
        ch = self._validate_channel(channel)
        time_arr, voltage_arr = self.read_arrays(ch)

        df = pd.DataFrame({"time": time_arr, "voltage": voltage_arr})
        df.attrs["units"] = self.units.copy()
        df.attrs["channel"] = ch
        df.attrs["sample_count"] = len(time_arr)
        return df

    def read_record(self, channel: Optional[int] = None) -> WaveformRecord:
        """
        Acquires and returns an immutable WaveformRecord dataclass containing data, arrays,
        and acquisition metrics.

        Args:
            channel: Target oscilloscope channel (defaults to self.default_channel).

        Returns:
            WaveformRecord: Immutable record with data, arrays, units, and metadata.
        """
        ch = self._validate_channel(channel)
        time_arr, voltage_arr = self.read_arrays(ch)

        df = pd.DataFrame({"time": time_arr, "voltage": voltage_arr})
        df.attrs["units"] = self.units.copy()
        df.attrs["channel"] = ch
        df.attrs["sample_count"] = len(time_arr)

        n = len(time_arr)
        dt = float((time_arr[-1] - time_arr[0]) / (n - 1)) if n > 1 else 0.0
        v_rms = float(np.sqrt(np.mean(voltage_arr**2)))

        meta = {
            "channel": ch,
            "sample_count": n,
            "time_start": float(time_arr[0]),
            "time_end": float(time_arr[-1]),
            "time_step": dt,
            "voltage_min": float(np.min(voltage_arr)),
            "voltage_max": float(np.max(voltage_arr)),
            "voltage_mean": float(np.mean(voltage_arr)),
            "voltage_rms": v_rms,
        }

        return WaveformRecord(
            data=df,
            time=time_arr,
            voltage=voltage_arr,
            units=self.units.copy(),
            channel=ch,
            sample_count=n,
            metadata=meta,
        )
