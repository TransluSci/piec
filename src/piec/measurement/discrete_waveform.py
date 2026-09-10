from __future__ import annotations

import io
import math
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Optional, Sequence, Union

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from piec.analysis.hysteresis import (
    STANDARD_HYSTERESIS_COLUMNS,
    STANDARD_HYSTERESIS_UNITS,
    plot_hysteresis_iv,
    plot_hysteresis_pv,
    plot_hysteresis_traces,
    process_hysteresis,
)
from piec.analysis.pund import _process_raw_3pp_file
from piec.analysis.utilities import (
    create_measurement_filename,
    interpolate_sparse_to_dense,
    metadata_and_data_to_csv,
)

from .adapters import WaveformReader
from .base import BaseMeasurement
from .contracts import (
    RunRequest,
    SafetyReport,
    ShutdownAttemptRecorder,
)
from .persistence import (
    CandidateReservation,
    create_staging_file,
    serialize_column_units,
)


class DiscreteWaveform(BaseMeasurement):
    """
    Parent class for managing discrete waveform generation and measurement experiments.

    Standardized for Checkpoint 20a:
    - Target API and schema: schema 'discrete_waveform', version 1;
    - Plain lowercase columns: ['time', 'voltage'] with canonical units {'time': 's', 'voltage': 'V'};
    - Inherits BaseMeasurement with shared lifecycle, runner, and session support;
    - Zero instrument I/O in __init__;
    - Strict trigger ordering: arm scope -> enable AWG output -> fire AWG trigger;
    - WaveformReader adapter standardizes oscilloscope reads;
    - Guaranteed attempt-all safe shutdown disabling all active AWG channels;
    - Unmigrated subclasses use a separate private support mixin until 20b/20c.

    Attributes:
        awg: Arbitrary Waveform Generator instrument object (positional dependency).
        osc: Oscilloscope instrument object (positional dependency).
        v_div: Oscilloscope vertical sensitivity in volts/division (keyword-only).
        voltage_channel: AWG channel used for voltage output (keyword-only).
        length: Waveform duration in seconds (keyword-only).
        osc_channel: Oscilloscope channel used for reading (keyword-only).
        output_dir: Target directory for data persistence (keyword-only).
    """

    mtype = "discrete_waveform"
    supports_pause = False

    def __init__(
        self,
        awg: Any,
        osc: Any,
        *,
        v_div: float = 0.01,
        voltage_channel: Union[str, int] = "1",
        length: float = 0.001,
        osc_channel: int = 1,
        output_dir: Optional[Union[str, Path]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        measurement_schema: str = "discrete_waveform",
        column_units: Optional[Mapping[str, str]] = None,
        raw_column_units: Optional[Mapping[str, str]] = None,
    ) -> None:
        """
        Initialize discrete waveform measurement parameters without performing hardware I/O.

        Args:
            awg: AWG instrument object (positional).
            osc: Oscilloscope instrument object (positional).
            v_div: Oscilloscope vertical sensitivity in Volts/division (keyword-only).
            voltage_channel: AWG output channel, '1' or 1 (keyword-only).
            length: Waveform duration in seconds (keyword-only).
            osc_channel: Oscilloscope channel to acquire (keyword-only).
            output_dir: Destination directory for persistent files (keyword-only).
            metadata: Optional additional metadata mapping (keyword-only).
        """
        self.awg = awg
        self.osc = osc

        self.v_div = float(v_div)
        if not math.isfinite(self.v_div) or self.v_div <= 0:
            raise ValueError(f"v_div must be a positive finite number, got {v_div}")

        self.voltage_channel = str(voltage_channel)
        try:
            int(self.voltage_channel)
        except (ValueError, TypeError):
            raise ValueError(f"voltage_channel must be convertible to int, got {voltage_channel!r}")

        self.length = float(length)
        if not math.isfinite(self.length) or self.length <= 0:
            raise ValueError(f"length must be a positive finite number, got {length}")

        if not isinstance(osc_channel, int) or isinstance(osc_channel, bool) or osc_channel <= 0:
            raise ValueError(f"osc_channel must be a positive integer, got {osc_channel!r}")
        self.osc_channel = int(osc_channel)

        self.notes: Optional[str] = None
        self.history: list[pd.DataFrame] = []
        self._legacy_metadata_df: Optional[pd.DataFrame] = None

        initial_metadata: dict[str, Any] = {
            "v_div": self.v_div,
            "voltage_channel": self.voltage_channel,
            "length": self.length,
            "osc_channel": self.osc_channel,
        }
        if metadata is not None:
            initial_metadata.update(dict(metadata))

        super().__init__(
            output_dir=output_dir,
            measurement_schema=measurement_schema,
            column_units=dict(column_units) if column_units is not None else {"time": "s", "voltage": "V"},
            raw_column_units=dict(raw_column_units) if raw_column_units is not None else {"time": "s", "voltage": "V"},
            metadata=initial_metadata,
        )

    # ------------------------------------------------------------------------
    # Properties for Base / Legacy Compatibility
    # ------------------------------------------------------------------------

    @property
    def data(self) -> Optional[pd.DataFrame]:
        """Analyzed result data, or raw partial data on abort/failure."""
        return self._data

    @data.setter
    def data(self, value: Optional[pd.DataFrame]) -> None:
        self._data = value

    @property
    def filename(self) -> Optional[str]:
        """Path to successfully published completed data CSV, or None."""
        return self._filename

    @filename.setter
    def filename(self, value: Optional[str]) -> None:
        self._filename = value

    @property
    def column_units_json(self) -> str:
        """JSON-serialized mapping of column units."""
        return serialize_column_units(self.column_units)

    @property
    def metadata(self) -> pd.DataFrame:
        """1-row DataFrame representation of current metadata."""
        if self._legacy_metadata_df is not None:
            return self._legacy_metadata_df
        m = dict(self.measurement_metadata)
        m.update(
            measurement_schema=self.measurement_schema,
            measurement_schema_version=self.measurement_schema_version,
            column_units_json=self.column_units_json,
            mtype=self.mtype,
            timestamp=self.measurement_metadata.get("timestamp", 0.0),
            processed=self.measurement_metadata.get("processed", False),
        )
        if self.notes is not None:
            m["notes"] = self.notes
        return pd.DataFrame([m])

    @metadata.setter
    def metadata(self, value: Any) -> None:
        if isinstance(value, pd.DataFrame):
            if len(value) > 0:
                self.measurement_metadata.update(value.iloc[0].to_dict())
            self._legacy_metadata_df = value
        elif isinstance(value, Mapping):
            self.measurement_metadata.update(dict(value))

    # ------------------------------------------------------------------------
    # Protected Lifecycle Hooks
    # ------------------------------------------------------------------------

    def _validate_options(self, options: Optional[Mapping[str, Any]]) -> None:
        """Validate run options before reservation or hardware I/O."""
        super()._validate_options(options)
        if options is not None and type(self) is DiscreteWaveform:
            for key in options:
                raise ValueError(f"Unknown option: {key}")

    def _configure_instruments(self, request: RunRequest) -> None:
        """
        Configure AWG and oscilloscope on the worker thread.

        Executed during CONFIGURING phase with zero prior hardware queries.
        """
        # Disable potentially active AWG output
        self.awg.output(channel=int(self.voltage_channel), on=False)

        # Query instrument identities on worker thread
        try:
            awg_idn = str(self.awg.idn())
        except Exception:
            awg_idn = "UNKNOWN"
        try:
            osc_idn = str(self.osc.idn())
        except Exception:
            osc_idn = "UNKNOWN"

        self.measurement_metadata["awg"] = awg_idn
        self.measurement_metadata["osc"] = osc_idn
        self.measurement_metadata["v_div"] = float(self.v_div)
        self.measurement_metadata["voltage_channel"] = str(self.voltage_channel)
        self.measurement_metadata["length"] = float(self.length)
        self.measurement_metadata["osc_channel"] = int(self.osc_channel)
        self.measurement_metadata["timestamp"] = time.time()

        # Initialize and configure AWG
        self.initialize_awg()

        # Initialize and configure Oscilloscope
        self.configure_oscilloscope(channel=int(self.osc_channel))

        # Waveform-specific AWG configuration hook
        self._configure_waveform()

    def _cancellable_dwell(self, duration: float) -> None:
        """Dwell in small time increments checking cooperative cancellation."""
        if duration <= 0:
            return
        end_time = time.monotonic() + duration
        while time.monotonic() < end_time:
            if self._coordinator.is_stop_requested:
                break
            remaining = end_time - time.monotonic()
            time.sleep(min(0.01, max(0.0, remaining)))

    def _capture_data(
        self,
        request: RunRequest,
        on_update: Optional[Callable[[Any], None]],
    ) -> pd.DataFrame:
        """
        Execute waveform acquisition with strict trigger ordering.

        Strict trigger ordering:
        1. Arm oscilloscope (self.osc.arm())
        2. Enable AWG output (self.awg.output(channel=..., on=True))
        3. Fire AWG trigger (self.awg.output_trigger())
        """
        if self._coordinator.is_stop_requested:
            return pd.DataFrame(columns=["time", "voltage"])

        # 1. Arm oscilloscope
        self.osc.arm()
        if self._coordinator.is_stop_requested:
            return pd.DataFrame(columns=["time", "voltage"])

        # 2. Enable AWG output
        self.awg.output(channel=int(self.voltage_channel), on=True)

        # 3. Fire AWG trigger
        if self._coordinator.is_stop_requested:
            return pd.DataFrame(columns=["time", "voltage"])
        self.awg.output_trigger()

        # Wait for waveform playback to complete
        self._cancellable_dwell(self.length * 1.2)
        if self._coordinator.is_stop_requested:
            return pd.DataFrame(columns=["time", "voltage"])

        # Acquire standardized waveform via WaveformReader adapter
        reader = WaveformReader(self.osc, default_channel=int(self.osc_channel))
        raw_df = reader.read()
        raw_df = raw_df[["time", "voltage"]].copy()

        self._raw_data = raw_df
        self._data = raw_df.copy()

        # Publish bounded snapshot
        view_df = raw_df.iloc[-100:].copy() if len(raw_df) > 100 else raw_df.copy()
        snap = self.publish_snapshot(
            views={"raw": view_df},
            completed_steps=len(raw_df),
            total_steps=len(raw_df),
        )
        if on_update is not None:
            on_update(snap)

        return raw_df.copy()

    def _safe_shutdown(
        self, recorder: Optional[ShutdownAttemptRecorder] = None
    ) -> SafetyReport:
        """
        Hardware shutdown attempting all actions on all channels.

        Guarantees that all active AWG channels are disabled and zeroed.
        """
        if recorder is None:
            recorder = ShutdownAttemptRecorder()

        # Action 1: Disable output on configured channel
        def disable_primary():
            self.awg.output(channel=int(self.voltage_channel), on=False)

        recorder.record_action(
            name=f"awg_disable_output_channel_{self.voltage_channel}",
            action_fn=disable_primary,
        )

        # Action 2: Disable output on all known/active AWG channels
        channels_to_disable = set()
        if hasattr(self.awg, "channel") and isinstance(self.awg.channel, (list, tuple, set)):
            for ch in self.awg.channel:
                try:
                    channels_to_disable.add(int(ch))
                except (ValueError, TypeError):
                    pass
        for ch in sorted(channels_to_disable):
            if ch != int(self.voltage_channel):
                recorder.record_action(
                    name=f"awg_disable_output_channel_{ch}",
                    action_fn=lambda c=ch: self.awg.output(channel=c, on=False),
                )

        # Action 3: Zero amplitude on configured channel if supported
        def zero_amplitude():
            if hasattr(self.awg, "set_amplitude"):
                self.awg.set_amplitude(channel=int(self.voltage_channel), amplitude=0.0)

        recorder.record_action(
            name=f"awg_zero_amplitude_channel_{self.voltage_channel}",
            action_fn=zero_amplitude,
        )

        return recorder.build_report()

    def _analyze_data(
        self, raw_data: pd.DataFrame, request: RunRequest
    ) -> pd.DataFrame:
        """Standardized analysis for discrete waveform: return time and voltage."""
        if raw_data.empty:
            return pd.DataFrame(columns=["time", "voltage"])
        return raw_data[["time", "voltage"]].copy()

    # ------------------------------------------------------------------------
    # Waveform Configuration & Legacy Support Methods
    # ------------------------------------------------------------------------

    def _configure_waveform(self) -> None:
        """Subclasses override or define configure_awg to setup waveform."""
        self.configure_awg()

    def _update_metadata(self) -> None:
        """Update legacy metadata DataFrame for unmigrated callers."""
        try:
            awg_idn = str(self.awg.idn())
        except Exception:
            awg_idn = "UNKNOWN"
        try:
            osc_idn = str(self.osc.idn())
        except Exception:
            osc_idn = "UNKNOWN"

        self.measurement_metadata["awg"] = awg_idn
        self.measurement_metadata["osc"] = osc_idn
        self.measurement_metadata["v_div"] = self.v_div
        self.measurement_metadata["voltage_channel"] = self.voltage_channel
        self.measurement_metadata["length"] = self.length
        self.measurement_metadata["mtype"] = self.mtype
        self.measurement_metadata["timestamp"] = time.time()
        self.measurement_metadata["processed"] = False
        if self.notes is not None:
            self.measurement_metadata["notes"] = self.notes

        exclude = {
            "awg", "osc", "data", "metadata", "history", "recoverable_staging_paths",
            "column_units", "raw_column_units", "measurement_metadata", "output_dir",
            "measurement_schema", "snapshot_type", "osc_channel", "notes",
        }
        params = {
            key: value for key, value in self.__dict__.items()
            if not key.startswith("_")
            and not callable(value)
            and key not in exclude
        }
        df = pd.DataFrame(params, index=[0])
        df["mtype"] = self.mtype
        df["awg"] = awg_idn
        df["osc"] = osc_idn
        if hasattr(self, "length"):
            df["length"] = self.length
        df["timestamp"] = self.measurement_metadata["timestamp"]
        df["processed"] = False
        self._legacy_metadata_df = df

    def _update_notes(self) -> None:
        """Subclasses override to adjust notes."""
        pass

    def _update_history(self) -> None:
        """Append metadata snapshot to history for unmigrated callers."""
        self.history.append(self.metadata.copy())

    def initialize_awg(self) -> None:
        """Configure basic AWG settings: load impedance (50Ω) and manual trigger."""
        if hasattr(self.awg, "initialize"):
            self.awg.initialize()
        self.awg.set_load_impedance(channel=int(self.voltage_channel), load_impedance=50.0)
        self.awg.set_trigger_source(channel=int(self.voltage_channel), trigger_source="MAN")

    def configure_oscilloscope(self, channel: int = 1) -> None:
        """Configure oscilloscope: horizontal scale, sensitivity, EXT trigger, 50Ω."""
        if hasattr(self.osc, "initialize"):
            self.osc.initialize()
        self.osc.configure_horizontal(tdiv=self.length / 8.0, x_position=5.0 * (self.length / 10.0))
        self.osc.set_vertical_scale(channel=int(channel), vdiv=float(self.v_div))
        self.osc.set_trigger_source(trigger_source="EXT")
        self.osc.set_trigger_level(trigger_level=0.95)
        self.osc.set_trigger_sweep(trigger_sweep="NORM")
        self.osc.set_channel_impedance(int(channel), channel_impedance="50")

    def configure_awg(self) -> None:
        """Placeholder for waveform-specific AWG configuration."""
        pass


class _LegacyWaveformSupport:
    """Private support for unmigrated FE/PUND callers; remove in 20b/20c."""

    def apply_and_capture_waveform(self) -> None:
        """Legacy waveform capture method for unmigrated subclasses."""
        print(f"Capturing waveform of type {self.mtype} for {self.length} seconds...")
        self.osc.arm()
        self.awg.output(channel=int(self.voltage_channel), on=True)
        self.awg.output_trigger()
        time.sleep(self.length * 1.2)
        if hasattr(self.osc, "set_acquisition_channel"):
            self.osc.set_acquisition_channel(channel=int(self.osc_channel))
        df = self.osc.get_data()
        time_col = "Time" if "Time" in df else "time"
        volt_col = "Voltage" if "Voltage" in df else "voltage"
        self._data = pd.DataFrame({"time (s)": df[time_col], "voltage (V)": df[volt_col]})
        print("Waveform captured.")

    def save_waveform(self) -> None:
        """Legacy waveform save method for unmigrated subclasses."""
        self._update_metadata()
        self._update_notes()
        if self._data is not None:
            save_dir = self.save_dir or (str(self.output_dir) if self.output_dir else ".")
            self.filename = create_measurement_filename(save_dir, self.mtype, self.notes)
            metadata_and_data_to_csv(self.metadata, self._data, self.filename)
            print(f"Waveform data saved to {self.filename}")
        else:
            print("No data to save. Capture the waveform first.")

    def analyze(self) -> None:
        """Legacy placeholder for measurement-specific analysis."""
        if self._data is not None:
            print(f"Analysis method not defined. Not changing {self.filename}")
        else:
            print("No data to analyze. Capture the waveform first.")


# ============================================================================
# SPECIFIC WAVEFORM MEASUREMENT CLASSES (UNMIGRATED: Checkpoints 20b & 20c)
# ============================================================================

class HysteresisLoop(DiscreteWaveform):
    """
    Hysteresis loop measurement using triangular excitation waveform.

    Standardized for Checkpoint 20b:
    - Target API and schema: schema 'hysteresis', version 1;
    - Target columns: ['time', 'voltage', 'current', 'polarization', 'applied_voltage'];
    - Target units: {'time': 's', 'voltage': 'V', 'current': 'A', 'polarization': 'uC/cm^2', 'applied_voltage': 'V'};
    - Raw columns: ['time', 'voltage'] with units {'time': 's', 'voltage': 'V'};
    - In-memory analysis via process_hysteresis;
    - Multi-artifact plot publication: _PV.png, _IV.png, _trace.png;
    - Inherits BaseMeasurement via DiscreteWaveform with shared lifecycle, runner, and session;
    - Zero instrument I/O in __init__;
    - Strict trigger ordering and attempt-all safe shutdown.
    """

    mtype = "hysteresis"
    measurement_schema = "hysteresis"
    measurement_schema_version = 1

    def __init__(
        self,
        awg: Any = None,
        osc: Any = None,
        *,
        v_div: float = 0.1,
        frequency: float = 1000.0,
        amplitude: float = 1.0,
        offset: float = 0.0,
        n_cycles: int = 2,
        voltage_channel: Union[str, int] = "1",
        osc_channel: int = 1,
        area: float = 1.0e-5,
        time_offset: float = 1e-8,
        r_shunt: float = 50.0,
        baseline_points: int = 20,
        auto_timeshift: bool = False,
        show_plots: bool = False,
        save_plots: bool = True,
        output_dir: Optional[Union[str, Path]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:

        self.frequency = float(frequency)
        if not math.isfinite(self.frequency) or self.frequency <= 0:
            raise ValueError(f"frequency must be a positive finite number, got {frequency}")

        self.amplitude = float(amplitude)
        if not math.isfinite(self.amplitude):
            raise ValueError(f"amplitude must be a finite number, got {amplitude}")

        self.offset = float(offset)
        if not math.isfinite(self.offset):
            raise ValueError(f"offset must be a finite number, got {offset}")

        if isinstance(n_cycles, bool) or not isinstance(n_cycles, int) or n_cycles < 1:
            raise ValueError(f"n_cycles must be an integer >= 1, got {n_cycles!r}")
        self.n_cycles = int(n_cycles)

        self.area = float(area)
        if not math.isfinite(self.area) or self.area <= 0:
            raise ValueError(f"area must be a positive finite number, got {area}")

        self.time_offset = float(time_offset)
        if not math.isfinite(self.time_offset) or self.time_offset < 0:
            raise ValueError(f"time_offset must be a finite non-negative number, got {time_offset}")

        self.r_shunt = float(r_shunt)
        if not math.isfinite(self.r_shunt) or self.r_shunt <= 0:
            raise ValueError(f"r_shunt must be a positive finite number, got {r_shunt}")

        if isinstance(baseline_points, bool) or not isinstance(baseline_points, int) or baseline_points < 1:
            raise ValueError(f"baseline_points must be a positive integer, got {baseline_points!r}")
        self.baseline_points = int(baseline_points)

        self.auto_timeshift = bool(auto_timeshift)
        self.show_plots = bool(show_plots)
        self.save_plots = bool(save_plots)

        length = 1.0 / self.frequency
        self.notes = str(self.amplitude).replace(".", "p") + "V_" + str(int(self.frequency)) + "Hz"

        initial_metadata: dict[str, Any] = {
            "frequency": self.frequency,
            "amplitude": self.amplitude,
            "offset": self.offset,
            "n_cycles": self.n_cycles,
            "area": self.area,
            "time_offset": self.time_offset,
            "r_shunt": self.r_shunt,
            "baseline_points": self.baseline_points,
            "auto_timeshift": self.auto_timeshift,
            "show_plots": self.show_plots,
            "save_plots": self.save_plots,
            "mtype": self.mtype,
            "notes": self.notes,
        }
        if metadata is not None:
            initial_metadata.update(dict(metadata))

        super().__init__(
            awg=awg,
            osc=osc,
            v_div=v_div,
            voltage_channel=voltage_channel,
            length=length,
            osc_channel=osc_channel,
            output_dir=output_dir,
            metadata=initial_metadata,
            measurement_schema="hysteresis",
            column_units={
                "time": "s",
                "voltage": "V",
                "current": "A",
                "polarization": "uC/cm^2",
                "applied_voltage": "V",
            },
            raw_column_units={"time": "s", "voltage": "V"},
        )

    def _validate_options(self, options: Optional[Mapping[str, Any]]) -> None:
        """Validate run options before reservation or hardware I/O."""
        super()._validate_options(options)
        if options is not None:
            allowed = {"save_plots", "show_plots", "auto_timeshift"}
            for key in options:
                if key not in allowed:
                    raise ValueError(f"Unknown Hysteresis option: {key}")

    def configure_awg(self) -> None:
        """Configure arbitrary triangular excitation waveform on the AWG."""
        interp_v_array = [0, 1, 0, -1, 0] + ([1, 0, -1, 0] * (self.n_cycles - 1))
        n_points = self.awg.arb_data_range[1]
        dense = interpolate_sparse_to_dense(
            np.linspace(0, len(interp_v_array), len(interp_v_array)),
            interp_v_array,
            total_points=n_points,
        )
        self.awg.create_arb_waveform(channel=int(self.voltage_channel), name="VOLATILE", data=dense)
        invert = self.amplitude < 0
        polarity = "INV" if invert else "NORM"
        self.awg.set_arb_waveform(channel=int(self.voltage_channel), name="VOLATILE")
        self.awg.set_amplitude(channel=int(self.voltage_channel), amplitude=abs(self.amplitude) * 2)
        self.awg.set_offset(channel=int(self.voltage_channel), offset=self.offset)
        self.awg.set_frequency(channel=int(self.voltage_channel), frequency=self.frequency)
        self.awg.set_polarity(channel=int(self.voltage_channel), polarity=polarity)

    def _analyze_data(
        self, raw_data: pd.DataFrame, request: RunRequest
    ) -> pd.DataFrame:
        """In-memory scientific hysteresis processing."""
        if raw_data.empty:
            return pd.DataFrame(columns=list(STANDARD_HYSTERESIS_COLUMNS))

        eff_auto_timeshift = self.auto_timeshift
        if request.options and "auto_timeshift" in request.options:
            eff_auto_timeshift = bool(request.options["auto_timeshift"])

        result = process_hysteresis(
            data=raw_data,
            metadata=self.measurement_metadata,
            frequency=self.frequency,
            amplitude=self.amplitude,
            offset=self.offset,
            area=self.area,
            n_cycles=self.n_cycles,
            time_offset=self.time_offset,
            auto_timeshift=eff_auto_timeshift,
            r_shunt=self.r_shunt,
            baseline_points=self.baseline_points,
        )

        self.measurement_metadata.update(result.metadata)
        self.time_offset = result.time_offset
        return result.data

    def _stage_side_artifacts(
        self,
        data: pd.DataFrame,
        request: RunRequest,
        reservation: CandidateReservation,
    ) -> Sequence[Tuple[Path, Path]]:
        """Stage companion plot artifacts (_PV.png, _IV.png, _trace.png) for publication."""
        if not request.save:
            return ()

        eff_save_plots = self.save_plots
        if request.options and "save_plots" in request.options:
            eff_save_plots = bool(request.options["save_plots"])

        if not eff_save_plots or data.empty:
            return ()

        dest_dir = reservation.candidate_path.parent
        base_basename = reservation.candidate_basename
        staging_pairs: list[Tuple[Path, Path]] = []

        try:
            for suffix, plotter in (("PV", plot_hysteresis_pv),
                                    ("IV", plot_hysteresis_iv),
                                    ("trace", plot_hysteresis_traces)):
                target = dest_dir / f"{base_basename}_{suffix}.png"
                fd, staging = create_staging_file(
                    dest_dir, prefix=f".{reservation.run_id}-{suffix}-", suffix=".png"
                )
                staging_pairs.append((staging, target))
                # An explicit Agg canvas avoids Tk creation on the runner thread.
                from matplotlib.figure import Figure
                from matplotlib.backends.backend_agg import FigureCanvasAgg
                fig = None
                try:
                    with io.open(fd, "wb") as handle:
                        fig = Figure(tight_layout=True)
                        FigureCanvasAgg(fig)
                        plotter(data, ax=fig.subplots())
                        fig.savefig(handle, format="png")
                finally:
                    if fig is not None:
                        fig.clear()
                        plt.close(fig)
            return staging_pairs
        except BaseException as exc:
            remaining = []
            for staging, _ in staging_pairs:
                try:
                    staging.unlink(missing_ok=True)
                except OSError:
                    remaining.append(str(staging))
            exc.recoverable_staging_paths = tuple(remaining)
            raise



class ThreePulsePund(_LegacyWaveformSupport, DiscreteWaveform):
    """
    PUND (Positive-Up-Negative-Down) pulse measurement system.

    Unmigrated subclass pending Checkpoint 20c vertical slice.
    """

    mtype = "3pulsepund"

    def __init__(
        self,
        awg=None,
        osc=None,
        v_div=0.1,
        reset_amp=1,
        reset_width=1e-3,
        reset_delay=1e-3,
        p_u_amp=1,
        p_u_width=1e-3,
        p_u_delay=1e-3,
        offset=0,
        voltage_channel: str = "1",
        area=1e-5,
        time_offset=1e-8,
        show_plots=False,
        save_plots=True,
        auto_timeshift=True,
        save_dir=r"\\scratch",
    ):
        self.reset_amp = reset_amp
        self.reset_width = reset_width
        self.reset_delay = reset_delay
        self.p_u_amp = p_u_amp
        self.p_u_width = p_u_width
        self.p_u_delay = p_u_delay
        self.offset = offset
        self.area = area
        self.voltage_channel = voltage_channel
        self.time_offset = time_offset
        self.show_plots = show_plots
        self.save_plots = save_plots
        self.auto_timeshift = auto_timeshift
        self.length = reset_width + reset_delay + (2 * p_u_width) + (2 * p_u_delay)
        super().__init__(
            awg,
            osc,
            v_div=v_div,
            voltage_channel=voltage_channel,
            length=self.length,
            output_dir=save_dir,
        )
        self.save_dir = str(save_dir) if save_dir is not None else None
        self.notes = (
            str(self.reset_amp).replace(".", "p")
            + "Vres_"
            + str(self.p_u_amp).replace(".", "p")
            + "Vpu"
        )
        self._update_metadata()

    def _update_notes(self):
        self.notes = (
            str(self.reset_amp).replace(".", "p")
            + "Vres_"
            + str(self.p_u_amp).replace(".", "p")
            + "Vpu"
        )

    def analyze(self):
        if self._data is not None:
            _process_raw_3pp_file(
                self.filename,
                show_plots=self.show_plots,
                save_plots=self.save_plots,
                auto_timeshift=self.auto_timeshift,
            )
            print(f"Analysis succeeded, updated {self.filename}")
        else:
            print("No data to analyze. Capture the waveform first.")

    def configure_awg(self):
        times = [
            0,
            self.reset_width,
            self.reset_delay,
            self.p_u_width,
            self.p_u_delay,
            self.p_u_width,
            self.p_u_delay,
        ]
        sum_times = [sum(times[: i + 1]) for i, t in enumerate(times)]
        amplitude = abs(self.reset_amp) + abs(self.p_u_amp)
        polarity = np.sign(self.p_u_amp)

        frac_reset_amp = self.reset_amp / amplitude
        frac_p_u_amp = self.p_u_amp / amplitude

        sparse_t = np.array([
            sum_times[0],
            sum_times[1],
            sum_times[1],
            sum_times[2],
            sum_times[2],
            sum_times[3],
            sum_times[3],
            sum_times[4],
            sum_times[4],
            sum_times[5],
            sum_times[5],
            sum_times[6],
        ])
        sparse_v = (
            np.array([
                -abs(frac_reset_amp),
                -abs(frac_reset_amp),
                0,
                0,
                abs(frac_p_u_amp),
                abs(frac_p_u_amp),
                0,
                0,
                abs(frac_p_u_amp),
                abs(frac_p_u_amp),
                0,
                0,
            ])
            * polarity
        )

        n_points = self.awg.arb_data_range[1]
        dense_v = interpolate_sparse_to_dense(sparse_t, sparse_v, total_points=n_points)

        self.awg.create_arb_waveform(channel=int(self.voltage_channel), name="VOLATILE", data=dense_v)
        self.awg.set_arb_waveform(channel=int(self.voltage_channel), name="VOLATILE")
        self.awg.set_offset(channel=int(self.voltage_channel), offset=self.offset)
        self.awg.set_amplitude(channel=int(self.voltage_channel), amplitude=abs(amplitude))
        self.awg.set_frequency(channel=int(self.voltage_channel), frequency=1.0 / self.length)
        print("AWG configured for a PUND pulse.")

    def run_experiment(self, *, on_update=None, save=True, save_partial=None):
        """Unmigrated legacy execution workflow for ThreePulsePund until Checkpoint 20c."""
        print(f"Running experiment for {self.mtype} measurement...")
        self.configure_oscilloscope()
        print("Oscilloscope configured.")
        self.initialize_awg()
        print("AWG initialized.")
        self.configure_awg()
        print("AWG configured.")
        self.apply_and_capture_waveform()
        print("Waveform applied and captured.")
        self.save_waveform()
        print("Waveform saved.")
        self.analyze()
        print("Analysis complete.")
        self._update_history()
        print("Experiment complete.")
        return None
