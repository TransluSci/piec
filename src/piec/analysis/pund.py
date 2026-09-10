"""
Ferroelectric PUND (Positive-Up-Negative-Down) pulse analysis.

Provides in-memory scientific data processing for ferroelectric PUND measurements
following PIEC standardized schemas.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.integrate import cumulative_trapezoid
from scipy.signal import find_peaks

from piec.analysis.utilities import interpolate_sparse_to_dense

STANDARD_PUND_COLUMNS: Tuple[str, ...] = (
    "time",
    "voltage",
    "current",
    "polarization",
    "polarization_p_hat",
    "polarization_p_star",
    "polarization_p_hat_r",
    "polarization_p_star_r",
    "delta_polarization",
    "applied_voltage",
)

STANDARD_PUND_UNITS: Dict[str, str] = {
    "time": "s",
    "voltage": "V",
    "current": "A",
    "polarization": "uC/cm^2",
    "polarization_p_hat": "uC/cm^2",
    "polarization_p_star": "uC/cm^2",
    "polarization_p_hat_r": "uC/cm^2",
    "polarization_p_star_r": "uC/cm^2",
    "delta_polarization": "uC/cm^2",
    "applied_voltage": "V",
}


@dataclass(frozen=True)
class PundAnalysisResult:
    """Result of in-memory PUND pulse analysis.

    Provides the processed DataFrame with plain columns, associated metadata mapping,
    and calculated time offset. Supports tuple unpacking as (data, metadata).
    """
    data: pd.DataFrame
    metadata: Dict[str, Any]
    time_offset: float

    def __iter__(self):
        yield self.data
        yield self.metadata

    def __getitem__(self, index: int):
        if index == 0:
            return self.data
        elif index == 1:
            return self.metadata
        raise IndexError("PundAnalysisResult index out of range (expected 0 or 1)")

    def __len__(self) -> int:
        return 2


def process_pund(
    data: Union[pd.DataFrame, Mapping[str, Any]],
    metadata: Optional[Union[pd.DataFrame, Mapping[str, Any]]] = None,
    *,
    reset_amp: Optional[float] = None,
    reset_width: Optional[float] = None,
    reset_delay: Optional[float] = None,
    p_u_amp: Optional[float] = None,
    p_u_width: Optional[float] = None,
    p_u_delay: Optional[float] = None,
    area: Optional[float] = None,
    length: Optional[float] = None,
    offset: Optional[float] = None,
    time_offset: Optional[float] = None,
    auto_timeshift: Optional[bool] = None,
    r_shunt: Optional[float] = None,
) -> PundAnalysisResult:
    """In-memory analysis of raw ferroelectric PUND waveform data.

    Calculates current, total polarization, switched polarization (P^),
    non-switched polarization (P*), remnant switched (P^r), remnant non-switched
    (P*r), delta polarization (dP), and nominal applied voltage.

    Args:
        data: Input DataFrame or Mapping containing 'time' and 'voltage' columns
              in seconds and volts. Declared incompatible units are rejected.
        metadata: Optional scalar metadata Mapping or 1-row DataFrame containing
                  measurement parameters.
        reset_amp: Reset pulse magnitude in V (absolute value is used, matching AWG
                   generation; its polarity opposes p_u_amp).
        reset_width: Reset pulse duration in seconds (overrides metadata).
        reset_delay: Delay after reset pulse in seconds (overrides metadata).
        p_u_amp: Signed measurement pulse amplitude in V (overrides metadata).
                 Its sign determines sequence polarity; zero uses positive polarity.
        p_u_width: Measurement pulse duration in seconds (overrides metadata).
        p_u_delay: Inter-pulse delay in seconds (overrides metadata).
        area: Capacitor device area in m² (overrides metadata).
        length: Total excitation length in seconds (overrides metadata).
        offset: AWG DC offset in V, added to nominal applied voltage including idle
                levels (overrides metadata, default 0.0). Does not alter detector data.
        time_offset: Trigger-to-response time alignment offset in seconds (overrides metadata, default 0.0).
        auto_timeshift: Boolean; detect onset from the first pulse peak when True
                        (overrides metadata, default True). If no peak is found,
                        use the validated manual offset for both slicing and trace delay.
        r_shunt: Shunt resistance in Ohms (overrides metadata; default 50.0).

    Returns:
        PundAnalysisResult containing:
            - data: DataFrame with plain standard columns
            - metadata: Dictionary with updated metadata, units, and processing status
            - time_offset: Effective time offset in seconds

    Capture coverage must include the entire aligned pulse sequence. Trailing
    padding of derived components is a table layout convention, not permission
    to analyze an incomplete final pulse or remanent interval.
    """
    # 1. Resolve and extract metadata parameters
    meta_dict: Dict[str, Any] = {}
    if metadata is not None:
        if isinstance(metadata, pd.DataFrame):
            if len(metadata) != 1:
                raise ValueError("Metadata must contain exactly one row")
            meta_dict = metadata.iloc[0].to_dict()
        elif isinstance(metadata, Mapping):
            meta_dict = dict(metadata)
        else:
            raise TypeError("Metadata must be a Mapping or one-row DataFrame")

    def _get_param(name: str, explicit_val: Optional[Any], default_val: Any = None) -> Any:
        if explicit_val is not None:
            return explicit_val
        if name in meta_dict:
            val = meta_dict[name]
            if hasattr(val, "item") and callable(val.item):
                try:
                    return val.item()
                except (ValueError, TypeError):
                    pass
            if hasattr(val, "values") and len(val.values) > 0:
                return val.values[0]
            return val
        return default_val

    eff_reset_amp = _get_param("reset_amp", reset_amp)
    eff_reset_width = _get_param("reset_width", reset_width)
    eff_reset_delay = _get_param("reset_delay", reset_delay)
    eff_p_u_amp = _get_param("p_u_amp", p_u_amp)
    eff_p_u_width = _get_param("p_u_width", p_u_width)
    eff_p_u_delay = _get_param("p_u_delay", p_u_delay)
    eff_area = _get_param("area", area)
    eff_offset = _get_param("offset", offset, default_val=0.0)
    eff_time_offset = _get_param("time_offset", time_offset, default_val=0.0)
    eff_auto = _get_param("auto_timeshift", auto_timeshift, default_val=True)
    r_shunt = _get_param("r_shunt", r_shunt, default_val=50.0)

    if eff_reset_amp is None:
        raise ValueError("Missing required parameter 'reset_amp'.")
    if eff_reset_width is None:
        raise ValueError("Missing required parameter 'reset_width'.")
    if eff_reset_delay is None:
        raise ValueError("Missing required parameter 'reset_delay'.")
    if eff_p_u_amp is None:
        raise ValueError("Missing required parameter 'p_u_amp'.")
    if eff_p_u_width is None:
        raise ValueError("Missing required parameter 'p_u_width'.")
    if eff_p_u_delay is None:
        raise ValueError("Missing required parameter 'p_u_delay'.")
    if eff_area is None:
        raise ValueError("Missing required parameter 'area'.")

    eff_reset_amp = float(eff_reset_amp)
    eff_reset_width = float(eff_reset_width)
    eff_reset_delay = float(eff_reset_delay)
    eff_p_u_amp = float(eff_p_u_amp)
    eff_p_u_width = float(eff_p_u_width)
    eff_p_u_delay = float(eff_p_u_delay)
    eff_area = float(eff_area)
    eff_offset = float(eff_offset)
    eff_time_offset = float(eff_time_offset)
    r_shunt = float(r_shunt)
    if not isinstance(eff_auto, (bool, np.bool_)):
        raise ValueError("auto_timeshift must be a boolean")
    eff_auto_timeshift = bool(eff_auto)

    if not np.isfinite(eff_reset_amp) or not np.isfinite(eff_p_u_amp) or not np.isfinite(eff_offset):
        raise ValueError("Amplitudes and offset must be finite numbers.")
    if not np.isfinite(eff_time_offset):
        raise ValueError("time_offset must be a finite number.")
    if eff_time_offset < 0:
        raise ValueError("Negative time_offset cannot be represented by the nominal delayed waveform")

    if not np.isfinite(eff_reset_width) or eff_reset_width <= 0:
        raise ValueError(f"reset_width must be positive, got {eff_reset_width}.")
    if not np.isfinite(eff_reset_delay) or eff_reset_delay <= 0:
        raise ValueError(f"reset_delay must be positive, got {eff_reset_delay}.")
    if not np.isfinite(eff_p_u_width) or eff_p_u_width <= 0:
        raise ValueError(f"p_u_width must be positive, got {eff_p_u_width}.")
    if not np.isfinite(eff_p_u_delay) or eff_p_u_delay <= 0:
        raise ValueError(f"p_u_delay must be positive, got {eff_p_u_delay}.")
    if not np.isfinite(eff_area) or eff_area <= 0:
        raise ValueError(f"area must be positive, got {eff_area}.")
    if not np.isfinite(r_shunt) or r_shunt <= 0:
        raise ValueError(f"r_shunt must be positive, got {r_shunt}.")

    default_length = eff_reset_width + eff_reset_delay + 2.0 * eff_p_u_width + 2.0 * eff_p_u_delay
    eff_length = _get_param("length", length, default_val=default_length)
    eff_length = float(eff_length)
    if not np.isfinite(eff_length) or eff_length <= 0:
        raise ValueError(f"length must be positive, got {eff_length}.")

    units = meta_dict.get("column_units", {"time": "s", "voltage": "V"})
    if isinstance(units, str):
        units = json.loads(units)
    if not isinstance(units, Mapping) or any(units.get(k) != v for k, v in (("time", "s"), ("voltage", "V"))):
        raise ValueError("Input column_units must declare time in s and voltage in V")

    # 2. Resolve input columns from data
    if isinstance(data, pd.DataFrame):
        df_in = data
    elif isinstance(data, Mapping):
        df_in = pd.DataFrame(data)
    else:
        raise TypeError(f"Data must be a DataFrame or Mapping, got {type(data)}.")

    if len(df_in) < 2:
        raise ValueError(f"Data must have at least 2 rows for PUND analysis, got {len(df_in)}.")

    if "time" not in df_in.columns:
        raise KeyError("Missing required time column 'time'.")
    if "voltage" not in df_in.columns:
        raise KeyError("Missing required voltage column 'voltage'.")

    time_arr = np.asarray(df_in["time"], dtype=float)
    voltage_arr = np.asarray(df_in["voltage"], dtype=float)

    if not np.all(np.isfinite(time_arr)) or not np.all(np.isfinite(voltage_arr)):
        raise ValueError("Input data contains non-finite values (NaN or Inf).")
    if not np.all(np.diff(time_arr) > 0):
        raise ValueError("Time must be strictly increasing")

    time_zeroed = time_arr - time_arr[0]
    if time_zeroed[-1] <= 0:
        raise ValueError("Time span must be positive (last time point must exceed first).")
    if eff_time_offset >= time_zeroed[-1]:
        raise ValueError("time_offset must fall within the captured time range")

    timestep = time_zeroed[-1] / len(time_zeroed)
    polarity = float(np.sign(eff_p_u_amp))
    if polarity == 0.0:
        polarity = 1.0

    # Current and polarization
    current_arr = voltage_arr / r_shunt
    polarization_arr = cumulative_trapezoid(
        current_arr,
        time_zeroed,
        initial=0.0,
    ) / eff_area * 100.0

    # Auto timeshift detection
    N_t0 = int(np.searchsorted(time_zeroed, eff_time_offset))
    final_time_offset = eff_time_offset

    if eff_auto_timeshift:
        mask = time_zeroed < (eff_reset_width + eff_reset_delay)
        subset_v = voltage_arr[mask] * polarity
        threshold = float(np.std(subset_v) * 0.3) if len(subset_v) > 0 else 0.0
        distance = min(eff_reset_delay, eff_p_u_delay + eff_p_u_width) / timestep * 0.9
        distance = max(1.0, distance)
        peaks, _ = find_peaks(-polarity * voltage_arr, height=threshold, distance=distance)
        if len(peaks) > 0:
            first_peak = int(peaks[0])
            v_at_first_peak = float(-polarity * voltage_arr[first_peak])
            rc_rise = 0
            for i in range(first_peak):
                if -polarity * voltage_arr[first_peak - i] < v_at_first_peak * 0.1:
                    rc_rise = i
                    break
            N_t0 = first_peak - rc_rise
            final_time_offset = float(N_t0 * timestep)

    if final_time_offset < 0:
        raise ValueError("Negative time_offset cannot be represented by the nominal delayed waveform")

    if eff_auto_timeshift and len(peaks) > 0:
        # Preserve the established sample-based automatic onset algorithm.
        time_for_slicing = time_zeroed - time_zeroed[N_t0]
    else:
        # Manual alignment also applies when automatic peak detection finds none.
        time_for_slicing = time_zeroed - eff_time_offset

    # Segment slicing
    t_ph = eff_reset_width + eff_reset_delay
    t_phr = t_ph + eff_p_u_width
    t_ps = t_phr + eff_p_u_delay
    t_psr = t_ps + eff_p_u_width
    t_end = t_psr + eff_p_u_delay
    rounding_tolerance = np.finfo(float).eps * max(t_end, time_zeroed[-1]) * 16
    if time_for_slicing[-1] + rounding_tolerance < t_end:
        raise ValueError("Captured waveform does not contain sufficient points: full PUND sequence required")

    n_ph = int(np.searchsorted(time_for_slicing, t_ph))
    n_phr = int(np.searchsorted(time_for_slicing, t_phr))
    n_ps = int(np.searchsorted(time_for_slicing, t_ps))
    n_psr = int(np.searchsorted(time_for_slicing, t_psr))
    n_end = int(np.searchsorted(time_for_slicing, t_end))

    ph = polarization_arr[n_ph:n_phr]
    phr = polarization_arr[n_phr:n_ps]
    ps = polarization_arr[n_ps:n_psr]
    psr = polarization_arr[n_psr:n_end]

    len_p = min(len(ph), len(ps))
    len_pr = min(len(phr), len(psr))
    if len_p == 0 or len_pr == 0:
        raise ValueError("Captured waveform does not contain sufficient points for all PUND pulses.")

    ph = ph[:len_p].copy()
    ps = ps[:len_p].copy()
    phr = phr[:len_pr].copy()
    psr = psr[:len_pr].copy()

    dp = np.concatenate([ph, phr]) - np.concatenate([ps, psr])
    array_dict = {
        "polarization_p_hat": ph,
        "polarization_p_star": ps,
        "polarization_p_hat_r": phr,
        "polarization_p_star_r": psr,
        "delta_polarization": dp,
    }

    out_p_arrays = {}
    for key, arr in array_dict.items():
        zeroed = arr - arr[0]
        pad_len = len(time_zeroed) - len(zeroed)
        if pad_len > 0:
            repeat_vals = np.full(pad_len, zeroed[-1])
            out_p_arrays[key] = np.concatenate([zeroed, repeat_vals])
        else:
            out_p_arrays[key] = zeroed[:len(time_zeroed)]

    # Applied voltage waveform reconstruction
    times = [0.0, eff_reset_width, eff_reset_delay, eff_p_u_width, eff_p_u_delay, eff_p_u_width, eff_p_u_delay]
    sum_times = [sum(times[: i + 1]) for i in range(len(times))]
    sparse_t = np.array([
        sum_times[0], sum_times[1], sum_times[1], sum_times[2], sum_times[2], sum_times[3], sum_times[3],
        sum_times[4], sum_times[4], sum_times[5], sum_times[5], sum_times[6],
    ], dtype=float)
    # Match AWG generation: amplitudes are magnitudes; P/U sign sets polarity.
    sparse_v = np.array([
        -abs(eff_reset_amp), -abs(eff_reset_amp), 0.0, 0.0, abs(eff_p_u_amp), abs(eff_p_u_amp), 0.0, 0.0,
        abs(eff_p_u_amp), abs(eff_p_u_amp), 0.0, 0.0,
    ], dtype=float) * polarity

    n_points = int(eff_length / timestep)
    v_applied = interpolate_sparse_to_dense(sparse_t, sparse_v, total_points=n_points)
    initial_delay = np.zeros(int(final_time_offset // timestep))
    v_applied = np.concatenate([initial_delay, v_applied])

    if len(v_applied) < len(time_zeroed):
        v_applied = np.concatenate([v_applied, np.zeros(len(time_zeroed) - len(v_applied))])

    # The AWG applies this DC offset to the full waveform, including idle levels.
    applied_voltage_arr = v_applied[:len(time_zeroed)] + eff_offset

    # 4. Construct standard result
    processed_df = pd.DataFrame({
        "time": time_zeroed,
        "voltage": voltage_arr,
        "current": current_arr,
        "polarization": polarization_arr,
        "polarization_p_hat": out_p_arrays["polarization_p_hat"],
        "polarization_p_star": out_p_arrays["polarization_p_star"],
        "polarization_p_hat_r": out_p_arrays["polarization_p_hat_r"],
        "polarization_p_star_r": out_p_arrays["polarization_p_star_r"],
        "delta_polarization": out_p_arrays["delta_polarization"],
        "applied_voltage": applied_voltage_arr,
    })

    out_meta = dict(meta_dict)
    out_meta["measurement_schema"] = "three_pulse_pund"
    out_meta["measurement_schema_version"] = 1
    out_meta["column_units"] = dict(STANDARD_PUND_UNITS)
    out_meta["reset_amp"] = eff_reset_amp
    out_meta["reset_width"] = eff_reset_width
    out_meta["reset_delay"] = eff_reset_delay
    out_meta["p_u_amp"] = eff_p_u_amp
    out_meta["p_u_width"] = eff_p_u_width
    out_meta["p_u_delay"] = eff_p_u_delay
    out_meta["offset"] = eff_offset
    out_meta["area"] = eff_area
    out_meta["length"] = eff_length
    out_meta["r_shunt"] = r_shunt
    out_meta["time_offset"] = final_time_offset
    out_meta["auto_timeshift"] = eff_auto_timeshift
    out_meta["processed"] = True

    return PundAnalysisResult(
        data=processed_df,
        metadata=out_meta,
        time_offset=final_time_offset,
    )


def plot_pund_delta_p(
    data: pd.DataFrame,
    ax: Optional[plt.Axes] = None,
    *,
    color: str = "k",
    linewidth: float = 1.5,
    title: Optional[str] = "PUND Delta Polarization vs Time",
    **kwargs: Any,
) -> plt.Axes:
    """Plot delta polarization (dP) versus time."""
    if ax is None:
        fig, ax = plt.subplots(tight_layout=True)
    t_col = "time"
    dp_col = "delta_polarization"
    ax.plot(data[t_col], data[dp_col], color=color, linewidth=linewidth, **kwargs)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Delta Polarization (uC/cm^2)")
    if title:
        ax.set_title(title)
    return ax


def plot_pund_traces(
    data: pd.DataFrame,
    ax: Optional[plt.Axes] = None,
    *,
    i_color: str = "k",
    v_color: str = "r",
    linewidth: float = 1.5,
    title: Optional[str] = "Current & Applied Voltage vs Time",
    **kwargs: Any,
) -> Tuple[plt.Axes, plt.Axes]:
    """Plot current response and applied voltage versus time on twin y-axes."""
    if ax is None:
        fig, ax = plt.subplots(tight_layout=True)
    t_col = "time"
    i_col = "current"
    v_col = "applied_voltage"

    ax.plot(data[t_col], data[i_col], color=i_color, linewidth=linewidth, label="Current", **kwargs)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Current (A)", color=i_color)
    ax.tick_params(axis="y", labelcolor=i_color)

    ax2 = ax.twinx()
    ax2.plot(data[t_col], data[v_col], color=v_color, linewidth=linewidth, label="Applied Voltage")
    ax2.set_ylabel("Applied Voltage (V)", color=v_color)
    ax2.tick_params(axis="y", labelcolor=v_color)

    if title:
        ax.set_title(title)
    return ax, ax2


def plot_pund_components(
    data: pd.DataFrame,
    ax: Optional[plt.Axes] = None,
    *,
    linewidth: float = 1.5,
    title: Optional[str] = "PUND Polarization Components",
    **kwargs: Any,
) -> plt.Axes:
    """Plot PUND polarization components (P^, P*, P^r, P*r) versus time."""
    if ax is None:
        fig, ax = plt.subplots(tight_layout=True)
    t = data["time"]
    ax.plot(t, data["polarization_p_hat"], label="P^ (switched)", linewidth=linewidth, **kwargs)
    ax.plot(t, data["polarization_p_star"], label="P* (non-switched)", linewidth=linewidth, **kwargs)
    ax.plot(t, data["polarization_p_hat_r"], label="P^r (remnant switched)", linewidth=linewidth, **kwargs)
    ax.plot(t, data["polarization_p_star_r"], label="P*r (remnant non-switched)", linewidth=linewidth, **kwargs)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Polarization (uC/cm^2)")
    ax.legend(loc="best")
    if title:
        ax.set_title(title)
    return ax




__all__ = (
    "STANDARD_PUND_COLUMNS",
    "STANDARD_PUND_UNITS",
    "PundAnalysisResult",
    "process_pund",
    "plot_pund_delta_p",
    "plot_pund_traces",
    "plot_pund_components",
)
