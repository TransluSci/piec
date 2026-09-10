"""
Ferroelectric hysteresis loop analysis.

Provides in-memory scientific data processing for ferroelectric polarization-voltage (P-V)
and current-voltage (I-V) hysteresis measurements following PIEC standardized schemas.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.integrate import cumulative_trapezoid

from piec.analysis.utilities import (
    interpolate_sparse_to_dense,
    metadata_and_data_to_csv,
    standard_csv_to_metadata_and_data,
)

STANDARD_HYSTERESIS_COLUMNS: Tuple[str, ...] = (
    "time",
    "voltage",
    "current",
    "polarization",
    "applied_voltage",
)

STANDARD_HYSTERESIS_UNITS: Dict[str, str] = {
    "time": "s",
    "voltage": "V",
    "current": "A",
    "polarization": "uC/cm^2",
    "applied_voltage": "V",
}


@dataclass(frozen=True)
class HysteresisAnalysisResult:
    """Result of in-memory hysteresis loop analysis.

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
        raise IndexError("HysteresisAnalysisResult index out of range (expected 0 or 1)")

    def __len__(self) -> int:
        return 2


def process_hysteresis(
    data: Union[pd.DataFrame, Mapping[str, Any]],
    metadata: Optional[Union[pd.DataFrame, Mapping[str, Any]]] = None,
    *,
    frequency: Optional[float] = None,
    amplitude: Optional[float] = None,
    area: Optional[float] = None,
    n_cycles: Optional[int] = None,
    time_offset: Optional[float] = None,
    auto_timeshift: bool = False,
    r_shunt: float = 50.0,
    baseline_points: int = 20,
) -> HysteresisAnalysisResult:
    """In-memory analysis of raw ferroelectric hysteresis waveform data.

    Calculates current, baseline-corrected current, polarization, and nominal
    applied voltage from captured time and response voltage.

    Args:
        data: Input DataFrame or Mapping containing 'time' and 'voltage' columns
              (or legacy 'time (s)' and 'voltage (V)').
        metadata: Optional scalar metadata Mapping or 1-row DataFrame containing
                  measurement parameters.
        frequency: Excitation frequency in Hz (overrides metadata).
        amplitude: Peak excitation amplitude in V (overrides metadata).
        area: Capacitor device area in m² (overrides metadata).
        n_cycles: Number of excitation cycles (overrides metadata).
        time_offset: Trigger-to-response time alignment offset in seconds (overrides metadata).
        auto_timeshift: If True, auto-detects time offset from first polarization peak.
        r_shunt: Shunt resistor impedance in Ohms (default 50.0).
        baseline_points: Initial points used to estimate and subtract DC current offset (default 20).

    Returns:
        HysteresisAnalysisResult containing:
            - data: DataFrame with plain columns ['time', 'voltage', 'current', 'polarization', 'applied_voltage']
            - metadata: Dictionary with updated metadata, units, and processing status
            - time_offset: Effective time offset in seconds
    """
    # 1. Resolve and extract metadata parameters
    meta_dict: Dict[str, Any] = {}
    if metadata is not None:
        if isinstance(metadata, pd.DataFrame):
            if not metadata.empty:
                meta_dict = metadata.iloc[0].to_dict()
        elif isinstance(metadata, Mapping):
            meta_dict = dict(metadata)

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

    eff_freq = _get_param("frequency", frequency)
    eff_amp = _get_param("amplitude", amplitude)
    eff_area = _get_param("area", area)
    eff_n_cycles = _get_param("n_cycles", n_cycles)
    eff_offset = _get_param("time_offset", time_offset, default_val=0.0)

    if eff_freq is None:
        raise ValueError("Missing required parameter 'frequency'.")
    if eff_amp is None:
        raise ValueError("Missing required parameter 'amplitude'.")
    if eff_area is None:
        raise ValueError("Missing required parameter 'area'.")
    if eff_n_cycles is None:
        raise ValueError("Missing required parameter 'n_cycles'.")

    eff_freq = float(eff_freq)
    eff_amp = float(eff_amp)
    eff_area = float(eff_area)
    eff_n_cycles = int(eff_n_cycles)
    eff_offset = float(eff_offset)
    r_shunt = float(r_shunt)

    if eff_freq <= 0:
        raise ValueError(f"Frequency must be positive, got {eff_freq}.")
    if eff_area <= 0:
        raise ValueError(f"Area must be positive, got {eff_area}.")
    if eff_n_cycles < 1:
        raise ValueError(f"n_cycles must be >= 1, got {eff_n_cycles}.")
    if r_shunt <= 0:
        raise ValueError(f"r_shunt must be positive, got {r_shunt}.")
    if not np.isfinite(eff_amp) or not np.isfinite(eff_offset):
        raise ValueError("Amplitude and time_offset must be finite numbers.")

    # 2. Resolve input columns from data
    if isinstance(data, pd.DataFrame):
        df_in = data
    elif isinstance(data, Mapping):
        df_in = pd.DataFrame(data)
    else:
        raise TypeError(f"Data must be a DataFrame or Mapping, got {type(data)}.")

    if len(df_in) < 2:
        raise ValueError(f"Data must have at least 2 rows for hysteresis analysis, got {len(df_in)}.")

    time_col = None
    for cand in ("time", "time (s)", "Time", "TIME"):
        if cand in df_in.columns:
            time_col = cand
            break
    if time_col is None:
        raise KeyError("Missing required time column (expected 'time' or 'time (s)').")

    volt_col = None
    for cand in ("voltage", "voltage (V)", "Voltage", "VOLTAGE"):
        if cand in df_in.columns:
            volt_col = cand
            break
    if volt_col is None:
        raise KeyError("Missing required voltage column (expected 'voltage' or 'voltage (V)').")

    time_arr = np.asarray(df_in[time_col], dtype=float)
    voltage_arr = np.asarray(df_in[volt_col], dtype=float)

    if not np.all(np.isfinite(time_arr)) or not np.all(np.isfinite(voltage_arr)):
        raise ValueError("Input data contains non-finite values (NaN or Inf).")

    # 3. Scientific mathematical processing
    time_zeroed = time_arr - time_arr[0]
    if time_zeroed[-1] <= 0:
        raise ValueError("Time span must be positive (last time point must exceed first).")

    timestep = time_zeroed[-1] / len(time_zeroed)
    length = 1.0 / eff_freq

    # Current calculation and baseline offset correction
    current_arr = voltage_arr / r_shunt
    n_baseline = min(len(current_arr), max(1, baseline_points))
    current_arr = current_arr - np.mean(current_arr[:n_baseline])

    # Polarization calculation: integral of current density (C/m^2 -> uC/cm^2 via * 100)
    polarization_arr = cumulative_trapezoid(
        current_arr / eff_area * 100.0,
        time_zeroed,
        initial=0.0,
    )

    # Auto timeshift determination if requested
    final_time_offset = eff_offset
    if auto_timeshift:
        len_first_wave = len(time_zeroed) // eff_n_cycles
        if len_first_wave > 0:
            first_pol_wave = polarization_arr[:len_first_wave]
            step_idx = int(length // (timestep * 4 * eff_n_cycles))
            step_idx = min(max(0, step_idx), len(time_zeroed) - 1)
            max_v_time = time_zeroed[step_idx]
            max_p_time = time_zeroed[int(np.argmax(first_pol_wave))]
            final_time_offset = float(max_p_time - max_v_time)
            if final_time_offset < 0:
                warnings.warn(
                    "Negative time offset detected, full waveform possibly not captured or data too noisy.",
                    UserWarning,
                    stacklevel=2,
                )

    # Reconstruct nominal applied voltage waveform
    interp_v_array = np.array(
        [0, 1, 0, -1, 0] + ([1, 0, -1, 0] * (eff_n_cycles - 1)),
        dtype=float,
    ) * eff_amp
    total_points = int(length // timestep)
    v_applied = interpolate_sparse_to_dense(
        np.linspace(0, len(interp_v_array), len(interp_v_array)),
        interp_v_array,
        total_points=total_points,
    )

    delay_points = max(0, int(final_time_offset // timestep))
    initial_delay = np.zeros(delay_points)
    v_applied = np.concatenate([initial_delay, v_applied])

    if len(v_applied) < len(time_zeroed):
        v_applied = np.concatenate([v_applied, np.zeros(len(time_zeroed) - len(v_applied))])

    applied_voltage_arr = v_applied[:len(time_zeroed)]

    # 4. Construct standard result
    processed_df = pd.DataFrame({
        "time": time_zeroed,
        "voltage": voltage_arr,
        "current": current_arr,
        "polarization": polarization_arr,
        "applied_voltage": applied_voltage_arr,
    })

    out_meta = dict(meta_dict)
    out_meta["measurement_schema"] = "hysteresis"
    out_meta["measurement_schema_version"] = 1
    out_meta["column_units"] = dict(STANDARD_HYSTERESIS_UNITS)
    out_meta["frequency"] = eff_freq
    out_meta["amplitude"] = eff_amp
    out_meta["n_cycles"] = eff_n_cycles
    out_meta["area"] = eff_area
    out_meta["r_shunt"] = r_shunt
    out_meta["time_offset"] = final_time_offset
    out_meta["auto_timeshift"] = bool(auto_timeshift)
    out_meta["processed"] = True

    return HysteresisAnalysisResult(
        data=processed_df,
        metadata=out_meta,
        time_offset=final_time_offset,
    )


def plot_hysteresis_pv(
    data: pd.DataFrame,
    ax: Optional[plt.Axes] = None,
    *,
    color: str = "k",
    linewidth: float = 1.5,
    title: Optional[str] = "P-V Hysteresis Loop",
    **kwargs: Any,
) -> plt.Axes:
    """Plot polarization versus applied voltage (P-V hysteresis loop)."""
    if ax is None:
        fig, ax = plt.subplots(tight_layout=True)
    v_col = "applied_voltage" if "applied_voltage" in data.columns else "applied voltage (V)"
    p_col = "polarization" if "polarization" in data.columns else "polarization (uC/cm^2)"
    ax.plot(data[v_col], data[p_col], color=color, linewidth=linewidth, **kwargs)
    ax.set_xlabel("Applied Voltage (V)")
    ax.set_ylabel("Polarization (uC/cm^2)")
    if title:
        ax.set_title(title)
    return ax


def plot_hysteresis_iv(
    data: pd.DataFrame,
    ax: Optional[plt.Axes] = None,
    *,
    color: str = "k",
    linewidth: float = 1.5,
    title: Optional[str] = "I-V Switching Loop",
    **kwargs: Any,
) -> plt.Axes:
    """Plot switching current versus applied voltage (I-V loop)."""
    if ax is None:
        fig, ax = plt.subplots(tight_layout=True)
    v_col = "applied_voltage" if "applied_voltage" in data.columns else "applied voltage (V)"
    i_col = "current" if "current" in data.columns else "current (A)"
    ax.plot(data[v_col], data[i_col], color=color, linewidth=linewidth, **kwargs)
    ax.set_xlabel("Applied Voltage (V)")
    ax.set_ylabel("Current (A)")
    if title:
        ax.set_title(title)
    return ax


def plot_hysteresis_traces(
    data: pd.DataFrame,
    ax: Optional[plt.Axes] = None,
    *,
    p_color: str = "k",
    v_color: str = "r",
    linewidth: float = 1.5,
    title: Optional[str] = "Polarization & Applied Voltage vs Time",
    **kwargs: Any,
) -> Tuple[plt.Axes, plt.Axes]:
    """Plot polarization and applied voltage versus time on twin y-axes."""
    if ax is None:
        fig, ax = plt.subplots(tight_layout=True)
    t_col = "time" if "time" in data.columns else "time (s)"
    p_col = "polarization" if "polarization" in data.columns else "polarization (uC/cm^2)"
    v_col = "applied_voltage" if "applied_voltage" in data.columns else "applied voltage (V)"

    ax.plot(data[t_col], data[p_col], color=p_color, linewidth=linewidth, label="Polarization", **kwargs)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Polarization (uC/cm^2)", color=p_color)
    ax.tick_params(axis="y", labelcolor=p_color)

    ax2 = ax.twinx()
    ax2.plot(data[t_col], data[v_col], color=v_color, linewidth=linewidth, label="Applied Voltage")
    ax2.set_ylabel("Applied Voltage (V)", color=v_color)
    ax2.tick_params(axis="y", labelcolor=v_color)

    if title:
        ax.set_title(title)
    return ax, ax2


def process_raw_hyst(
    path: str,
    show_plots: bool = False,
    save_plots: bool = False,
    auto_timeshift: bool = False,
) -> HysteresisAnalysisResult:
    """Legacy file-path-oriented wrapper around in-memory process_hysteresis.

    Maintained as a temporary bridge for unmigrated callers until Checkpoint 20b.
    Reads the CSV at `path`, performs analysis via `process_hysteresis`, generates
    optional plots, and updates the CSV on disk with processed columns.
    """
    metadata, raw_df = standard_csv_to_metadata_and_data(path)
    result = process_hysteresis(raw_df, metadata, auto_timeshift=auto_timeshift)

    # Map back to legacy column headers for backward compatibility with unmigrated CSV consumers
    legacy_df = pd.DataFrame({
        "time (s)": result.data["time"],
        "voltage (V)": result.data["voltage"],
        "current (A)": result.data["current"],
        "polarization (uC/cm^2)": result.data["polarization"],
        "applied voltage (V)": result.data["applied_voltage"],
    })

    if show_plots or save_plots:
        base_path = path[:-4] if path.lower().endswith(".csv") else path

        # PV Loop plot
        fig, ax = plt.subplots(tight_layout=True)
        ax.plot(result.data["applied_voltage"], result.data["polarization"], color="k")
        ax.set_xlabel("applied voltage (V)")
        ax.set_ylabel("polarization (uC/cm^2)")
        if save_plots:
            fig.savefig(f"{base_path}_PV.png")
        if show_plots:
            plt.show()
        plt.close(fig)

        # IV Loop plot
        fig, ax = plt.subplots(tight_layout=True)
        ax.plot(result.data["applied_voltage"], result.data["current"], color="k")
        ax.set_xlabel("applied voltage (V)")
        ax.set_ylabel("current (A)")
        if save_plots:
            fig.savefig(f"{base_path}_IV.png")
        if show_plots:
            plt.show()
        plt.close(fig)

        # Polarization vs applied current/voltage trace plot
        fig, ax = plt.subplots(tight_layout=True)
        ax.plot(result.data["time"], result.data["polarization"], color="k")
        ax.set_xlabel("time (s)")
        ax.set_ylabel("polarization (uC/cm^2)")
        ax1 = ax.twinx()
        ax1.plot(result.data["time"], result.data["applied_voltage"], color="r")
        ax1.set_ylabel("applied voltage (V)")
        if save_plots:
            fig.savefig(f"{base_path}_trace.png")
        if show_plots:
            plt.show()
        plt.close(fig)

    updated_metadata = metadata.copy()
    updated_metadata["time_offset"] = result.time_offset
    updated_metadata["processed"] = True

    metadata_and_data_to_csv(updated_metadata, legacy_df, path)
    return result


__all__ = (
    "STANDARD_HYSTERESIS_COLUMNS",
    "STANDARD_HYSTERESIS_UNITS",
    "HysteresisAnalysisResult",
    "process_hysteresis",
    "process_raw_hyst",
    "plot_hysteresis_pv",
    "plot_hysteresis_iv",
    "plot_hysteresis_traces",
)
