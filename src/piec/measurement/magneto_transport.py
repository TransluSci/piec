"""
Parent class for managing magneto-transport measurements.

Standardized for Checkpoint 24a of MEASUREMENT_STANDARDIZATION_PLAN.md:
- Inherits BaseMeasurement with shared lifecycle, runner, and session support;
- Target API and schema: schema 'amr', version 1;
- Plain lowercase columns: ['angle', 'field', 'x', 'y'] with canonical units {'angle': 'deg', 'field': 'Oe', 'x': 'V', 'y': 'V'};
- Zero instrument I/O in __init__;
- Setup profile composition (AMRSetupProfile) with FieldSource, FieldReader, TransportReadout, OrientationController;
- Lock-in settings preservation by default (readout_configuration='preserve');
- Validates excitation shutdown policy before energizing;
- Attempt-all safe shutdown propagating failures to SafetyStatus.UNSAFE while retaining connections;
- Backward compatibility for unmigrated subclasses (AMR) until Checkpoint 24b.
"""

from __future__ import annotations

import math
from pathlib import Path
import time
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from piec.analysis.utilities import (
    create_measurement_filename,
    metadata_and_data_to_csv,
)
from piec.measurement.base import BaseMeasurement
from piec.measurement.contracts import (
    HardwareSafetyError,
    MeasurementSnapshot,
    ReservationToken,
    RunRequest,
    RunState,
    SafetyReport,
    SafetyStatus,
    ShutdownAttemptRecorder,
)

if TYPE_CHECKING:
    from piec.measurement.adapters.amr import (
        AMRSetupProfile,
        FieldReader,
        FieldSource,
        OrientationController,
        TransportReadout,
    )


class MagnetoTransport(BaseMeasurement):
    """
    Parent class for managing all magneto-transport measurements.

    Provides core functionality for configuring magnet field sources, orientation
    controllers, transport electrical readout, data capture, and attempt-all safing.
    Designed to be subclassed for specific measurement types (e.g. AMR).

    Attributes:
        dmm: DMM / Hall sensor instrument object (optional/setup reader)
        calibrator: Calibrator / magnet power supply instrument object
        arduino: Stepper motor instrument object
        lockin: Lock-in amplifier instrument object
        field: Commanded magnetic field in Oersted
        save_dir: Legacy directory path for data storage
        voltage_callibration: Legacy calibration factor (Oe/V)
        voltage_calibration: Canonical calibration factor (Oe/V)
        profile: AMRSetupProfile composite coordinating setup roles
    """

    snapshot_type = MeasurementSnapshot
    mtype = "magneto_transport"
    measurement_schema = "amr"
    measurement_schema_version = 1
    supports_pause = True
    ordered_columns: Tuple[str, ...] = ("angle", "field", "x", "y")
    column_units = {"angle": "deg", "field": "Oe", "x": "V", "y": "V"}
    raw_column_units = {"angle": "deg", "field": "Oe", "x": "V", "y": "V"}

    def __init__(
        self,
        dmm: Any = None,
        calibrator: Any = None,
        stepper: Any = None,
        lockin: Any = None,
        *,
        field: float = 0.0,
        output_dir: Optional[Union[str, Path]] = None,
        profile: Optional[AMRSetupProfile] = None,
        save_dir: str = r"\scratch",
        voltage_calibration: float = 10000.0,
        live_plot: bool = True,
        plot_config: Optional[Dict[str, str]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        require_excitation_safing: bool = False,
        readout_configuration: str = "preserve",
        excitation_source: str = "internal",
        shutdown_handler: Optional[Callable[[], None]] = None,
        external_source_owner: Optional[str] = None,
        measurement_schema: str = "amr",
        column_units: Optional[Mapping[str, str]] = None,
        raw_column_units: Optional[Mapping[str, str]] = None,
    ) -> None:
        """
        Initialize core magneto-transport measurement system without performing hardware I/O.
        """
        cal_factor = float(voltage_calibration)
        if not math.isfinite(cal_factor) or cal_factor <= 0:
            raise ValueError(f"voltage_calibration must be a positive finite number, got {voltage_calibration!r}")
        self.voltage_calibration = cal_factor
        self.voltage_callibration = cal_factor

        # Commanded field
        field_f = float(field)
        if not math.isfinite(field_f):
            raise ValueError(f"field must be a finite number, got {field!r}")
        self.field = field_f

        # Instruments & profile
        self.dmm = dmm
        self.calibrator = calibrator
        self.stepper = stepper
        self.arduino = stepper
        self.lockin = lockin

        if profile is not None:
            self._profile = profile
            if self.dmm is None and profile.field_reader is not None:
                self.dmm = profile.field_reader.instrument
            if self.calibrator is None:
                self.calibrator = profile.field_source.instrument
            if self.stepper is None and profile.orientation_controller is not None:
                self.stepper = profile.orientation_controller.instrument
                self.arduino = self.stepper
            if self.lockin is None and profile.transport_readout is not None:
                self.lockin = profile.transport_readout.instrument
        elif calibrator is not None and stepper is not None and lockin is not None:
            from piec.measurement.adapters.amr import AMRSetupProfile

            self._profile = AMRSetupProfile.from_instruments(
                dmm=dmm,
                calibrator=calibrator,
                arduino=stepper,
                lockin=lockin,
                field_calibration=self.voltage_calibration,
                reader_calibration=self.voltage_calibration if dmm is not None else None,
                readout_configuration=readout_configuration,
                excitation_source=excitation_source,
                shutdown_handler=shutdown_handler,
                external_source_owner=external_source_owner,
            )
        else:
            self._profile = None

        # Storage directories
        self.save_dir = str(output_dir) if output_dir is not None else str(save_dir)
        norm_save = str(save_dir).replace("/", "\\")
        if output_dir is not None:
            out_path = Path(output_dir)
        elif norm_save not in (r"\scratch", r"\\scratch"):
            out_path = Path(save_dir)
        else:
            out_path = None
        self.output_dir = out_path

        # Live plotting & config
        self.live_plot = bool(live_plot)
        self.plot_config = dict(plot_config or {"x": "angle", "y": "X"})
        self.require_excitation_safing = bool(require_excitation_safing)
        self.readout_configuration = str(readout_configuration)
        self._fig = None
        self._ax = None
        self._in_jupyter = self._is_jupyter()
        self._legacy_metadata_df: Optional[pd.DataFrame] = None
        self._abort_requested: bool = False
        self._pause_requested: bool = False

        initial_metadata: Dict[str, Any] = {
            "field": self.field,
            "voltage_calibration": self.voltage_calibration,
            "voltage_callibration": self.voltage_callibration,
        }
        if metadata is not None:
            initial_metadata.update(dict(metadata))

        c_units = (
            dict(column_units)
            if column_units is not None
            else {"angle": "deg", "field": "Oe", "x": "V", "y": "V"}
        )
        r_units = (
            dict(raw_column_units)
            if raw_column_units is not None
            else {"angle": "deg", "field": "Oe", "x": "V", "y": "V"}
        )

        super().__init__(
            output_dir=self.output_dir,
            measurement_schema=measurement_schema,
            column_units=c_units,
            raw_column_units=r_units,
            metadata=initial_metadata,
        )

    # ------------------------------------------------------------------------
    # Setup Role Properties
    # ------------------------------------------------------------------------

    @property
    def profile(self) -> Optional[AMRSetupProfile]:
        """Active AMRSetupProfile instance, if configured."""
        return self._profile

    @property
    def field_source(self) -> Optional[FieldSource]:
        """FieldSource role adapter from setup profile."""
        return self._profile.field_source if self._profile else None

    @property
    def field_reader(self) -> Optional[FieldReader]:
        """FieldReader role adapter from setup profile."""
        return self._profile.field_reader if self._profile else None

    @property
    def transport_readout(self) -> Optional[TransportReadout]:
        """TransportReadout role adapter from setup profile."""
        return self._profile.transport_readout if self._profile else None

    @property
    def orientation_controller(self) -> Optional[OrientationController]:
        """OrientationController role adapter from setup profile."""
        return self._profile.orientation_controller if self._profile else None

    # ------------------------------------------------------------------------
    # Cooperative Controls & Properties
    # ------------------------------------------------------------------------

    @property
    def abort_requested(self) -> bool:
        """Cooperative abort flag linked to BaseMeasurement coordinator."""
        return self._abort_requested or self._coordinator.is_stop_requested

    @abort_requested.setter
    def abort_requested(self, value: bool) -> None:
        self._abort_requested = bool(value)
        if value:
            if self._coordinator.run_state.is_active:
                self.request_stop()
            else:
                self._coordinator._stop_event.set()
        else:
            self._coordinator._stop_event.clear()

    @property
    def pause_requested(self) -> bool:
        """Cooperative pause flag linked to BaseMeasurement coordinator."""
        return self._pause_requested or self._coordinator.is_pause_requested

    @pause_requested.setter
    def pause_requested(self, value: bool) -> None:
        self._pause_requested = bool(value)
        if self._coordinator.run_state.is_active:
            self.request_pause(bool(value))
        else:
            if value:
                self._coordinator._pause_event.set()
            else:
                self._coordinator._pause_event.clear()

    @property
    def data(self) -> Optional[pd.DataFrame]:
        """Captured or analyzed data DataFrame."""
        return self._data

    @data.setter
    def data(self, value: Optional[pd.DataFrame]) -> None:
        self._data = value

    @property
    def filename(self) -> Optional[str]:
        """Path to saved data file, or None."""
        return self._filename

    @filename.setter
    def filename(self, value: Optional[str]) -> None:
        self._filename = value

    @property
    def metadata(self) -> pd.DataFrame:
        """DataFrame representation of measurement metadata for legacy compatibility."""
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
    # Legacy Direct Methods
    # ------------------------------------------------------------------------

    def initialize(self) -> None:
        """
        Ensure proper connection along all base instruments.
        Legacy direct execution method.
        """
        try:
            if self.dmm is not None and hasattr(self.dmm, "idn"):
                self.dmm.idn()
            if self.calibrator is not None and hasattr(self.calibrator, "idn"):
                self.calibrator.idn()
            if self.arduino is not None and hasattr(self.arduino, "idn"):
                self.arduino.idn()
            if self.lockin is not None and hasattr(self.lockin, "idn"):
                self.lockin.idn()
            print("All instruments working nominally")
        except Exception:
            print("Error communicating with instruments")
        self.set_field()

    def set_field(self) -> None:
        """
        Set the magnetic field using the calibrator and verify with DMM.
        Legacy direct execution method.
        """
        voltage = convert_field_to_voltage(self.field, self.voltage_callibration)
        self.calibrator.set_output(voltage)
        time.sleep(3)  # Allow time for field to stabilize
        actual_voltage = self.dmm.get_voltage()
        actual_field = convert_voltage_to_field(actual_voltage, self.voltage_callibration)
        tolerance = 1.0 + 0.1 * abs(self.field)
        if abs(actual_field - self.field) > tolerance:
            print(f"Warning: Field set to {self.field} Oe, but actual field is {actual_field} Oe")
        else:
            print(f"Set field to {self.field} Oe and checked it is at {actual_field} Oe")

    def configure_lockin(self) -> None:
        """
        Placeholder for measurement specific lockin configuration.

        Raises:
            AttributeError: If not implemented in child class
        """
        raise AttributeError("configure_lockin() must be defined in the child class specific to measurement")

    def capture_data(
        self,
        *,
        on_update: Optional[Callable[[Any], None]] = None,
    ) -> pd.DataFrame:
        """
        Public capture data method.

        If called directly on base MagnetoTransport outside an active session,
        raises AttributeError for legacy base compatibility.
        """
        if type(self) is MagnetoTransport and self._active_session is None:
            raise AttributeError("capture_data() must be defined in the child class specific to measurement")
        return super().capture_data(on_update=on_update)

    def shut_off(self) -> None:
        """
        Turns off the field by setting the calibrator to zero volts.
        Legacy direct execution method.
        """
        if self.calibrator is not None:
            self.calibrator.set_output(0)
            output_fn = getattr(self.calibrator, "output", None)
            if callable(output_fn):
                try:
                    output_fn(on=False)
                except Exception:
                    pass
        print("Field turned off.")

    def analyze(self) -> None:
        """Placeholder for measurement-specific analysis."""
        if self.data is not None:
            print(f"Analysis method not defined. Not changing {self.filename}")
        else:
            print("No data to analyze. Capture the waveform first.")

    @staticmethod
    def _is_jupyter() -> bool:
        """Detect if running inside a Jupyter notebook."""
        try:
            from IPython import get_ipython

            shell = get_ipython()
            if shell is None:
                return False
            if shell.__class__.__name__ == "ZMQInteractiveShell":
                return True
        except ImportError:
            pass
        return False

    def _init_live_plot(self) -> None:
        """Initialize the live plot figure and axes."""
        if not self.live_plot:
            return
        if not self._in_jupyter:
            plt.ion()
        self._fig, self._ax = plt.subplots(figsize=(8, 5))
        x_col = self.plot_config.get("x", "angle")
        y_col = self.plot_config.get("y", "X")
        self._ax.set_xlabel(x_col)
        self._ax.set_ylabel(y_col)
        self._ax.set_title(f"{y_col} vs {x_col} (live)")

    def _update_live_plot(self) -> None:
        """Update the live plot with the latest data."""
        if not self.live_plot or self._fig is None or self.data is None:
            return
        x_col = self.plot_config.get("x", "angle")
        y_col = self.plot_config.get("y", "X")
        if x_col not in self.data.columns or y_col not in self.data.columns:
            return

        self._ax.clear()
        self._ax.plot(self.data[x_col], self.data[y_col], "o-", color="blue")
        self._ax.set_xlabel(x_col)
        self._ax.set_ylabel(y_col)
        self._ax.set_title(f"{y_col} vs {x_col} (live)")

        if self._in_jupyter:
            from IPython.display import clear_output, display

            clear_output(wait=True)
            display(self._fig)
        else:
            self._fig.canvas.draw_idle()
            self._fig.canvas.flush_events()

    def _close_live_plot(self) -> None:
        """Close the live plot and show a final static version."""
        if not self.live_plot or self._fig is None:
            return
        if not self._in_jupyter:
            plt.ioff()
        plt.close(self._fig)
        self._fig = None
        self._ax = None

    def plot_results(self) -> None:
        """Show a final static plot of the captured data."""
        if not self.live_plot:
            return
        if self.data is None:
            print("No data to plot.")
            return
        x_col = self.plot_config.get("x", "angle")
        y_col = self.plot_config.get("y", "X")
        if x_col not in self.data.columns or y_col not in self.data.columns:
            print(f"Columns '{x_col}' or '{y_col}' not found in data.")
            return
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(self.data[x_col], self.data[y_col], "o-", color="blue")
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        ax.set_title(f"{y_col} vs {x_col}")
        plt.tight_layout()
        plt.show()

    # ------------------------------------------------------------------------
    # BaseMeasurement Lifecycle Hooks
    # ------------------------------------------------------------------------

    def _validate_options(self, options: Optional[Mapping[str, Any]]) -> None:
        """Validate run options before reservation or hardware I/O."""
        super()._validate_options(options)
        if options is not None and type(self) is MagnetoTransport:
            valid_keys = {"configure_lockin", "readout_configuration", "require_excitation_safing"}
            for key in options:
                if key not in valid_keys:
                    raise ValueError(f"Unknown option: {key}")

            if "readout_configuration" in options:
                cfg = str(options["readout_configuration"]).lower()
                if cfg not in ("preserve", "configure"):
                    raise ValueError(f"readout_configuration must be 'preserve' or 'configure', got {cfg!r}")

        req_safing = (
            options.get("require_excitation_safing")
            if options and "require_excitation_safing" in options
            else self.require_excitation_safing
        )
        if req_safing:
            if self.profile is None or self.profile.transport_readout.shutdown_handler is None:
                raise HardwareSafetyError(
                    "Excitation shutdown handler required before energizing, but none declared"
                )

    def _configure_instruments(self, request: RunRequest) -> None:
        """
        Configure instruments during CONFIGURING phase with excitation safing validation before energizing.
        """
        opts = request.options or {}
        req_safing = opts.get("require_excitation_safing", self.require_excitation_safing)
        if req_safing:
            if self.profile is None or self.profile.transport_readout.shutdown_handler is None:
                raise HardwareSafetyError(
                    "Excitation shutdown handler required before energizing, but none declared"
                )

        if self.profile is None:
            raise ValueError("MagnetoTransport requires instruments or profile to execute")

        if self._coordinator.is_stop_requested:
            return

        # Query IDNs if available on worker thread
        for role_name, inst in (
            ("dmm", self.dmm),
            ("calibrator", self.calibrator),
            ("arduino", self.arduino),
            ("lockin", self.lockin),
        ):
            if inst is not None and hasattr(inst, "idn"):
                try:
                    self.measurement_metadata[role_name] = str(inst.idn())
                except Exception:
                    pass

        # Handle lock-in configuration policy
        cfg_mode = opts.get(
            "readout_configuration",
            getattr(self, "readout_configuration", "preserve"),
        )
        if "configure_lockin" in opts:
            cfg_mode = "configure" if opts["configure_lockin"] else "preserve"
        if (
            cfg_mode == "configure"
            and self.profile is not None
            and self.profile.transport_readout is not None
        ):
            saved_mode = self.profile.transport_readout.readout_configuration
            try:
                self.profile.transport_readout.readout_configuration = "configure"
                self.profile.transport_readout.configure()
            finally:
                self.profile.transport_readout.readout_configuration = saved_mode
        # Note: If 'preserve' (default), NO configuration commands are sent to lock-in!

        if self._coordinator.is_stop_requested:
            return

        # Energize magnetic field via field source
        self.profile.field_source.set_field(self.field)
        if self.profile.field_reader is not None:
            try:
                self.profile.field_reader.verify_field(self.field)
            except Exception:
                pass

    def _capture_data(
        self,
        request: RunRequest,
        on_update: Optional[Callable[[Any], None]] = None,
    ) -> pd.DataFrame:
        """
        Acquire magneto-transport point.
        """
        if self._coordinator.is_stop_requested:
            return pd.DataFrame(columns=self.ordered_columns)

        if self.profile is None:
            raise AttributeError("capture_data() must be defined in the child class specific to measurement")

        angle = self.profile.orientation_controller.current_angle
        field_val = (
            self.profile.field_source.commanded_field
            if self.profile.field_source.commanded_field is not None
            else self.field
        )
        signals = self.profile.transport_readout.read_signals()

        row = {
            "angle": float(angle),
            "field": float(field_val),
            "x": float(signals["x"]),
            "y": float(signals["y"]),
        }
        df = pd.DataFrame([row])
        self._raw_data = df.copy()
        self._data = df.copy()

        snap = self.publish_snapshot(views={"raw": df}, completed_steps=1, total_steps=1)
        if on_update is not None:
            on_update(snap)

        return df

    def _safe_shutdown(
        self, recorder: Optional[ShutdownAttemptRecorder] = None
    ) -> SafetyReport:
        """
        Attempt-all shutdown across all setup roles.
        Propagates any role error or unconfirmed shutdown to SafetyStatus.UNSAFE.
        Retains instrument connections intact.
        """
        if recorder is None:
            recorder = ShutdownAttemptRecorder()

        if self.profile is not None:
            recorder.record_action(
                name="field_source_shutdown",
                action_fn=self.profile.field_source.safe_shutdown,
            )
            recorder.record_action(
                name="orientation_controller_shutdown",
                action_fn=self.profile.orientation_controller.safe_shutdown,
            )
            recorder.record_action(
                name="transport_readout_shutdown",
                action_fn=self.profile.transport_readout.safe_shutdown,
            )
        elif self.calibrator is not None:
            recorder.record_action(
                name="calibrator_shut_off",
                action_fn=self.shut_off,
            )

        return recorder.build_report()

    def _analyze_data(
        self, raw_data: pd.DataFrame, request: Optional[RunRequest] = None
    ) -> pd.DataFrame:
        """In-memory analysis hook (identity pass-through for base magneto-transport)."""
        return raw_data.copy() if raw_data is not None else pd.DataFrame()

    def run_experiment(
        self,
        *,
        on_update: Optional[Callable[[Any], None]] = None,
        save: bool = True,
        save_partial: Optional[bool] = None,
        options: Optional[Mapping[str, Any]] = None,
        token: Optional[ReservationToken] = None,
    ) -> pd.DataFrame:
        """
        Standard BaseMeasurement execution wrapper.
        """
        opts = dict(options or {})
        return super().run_experiment(
            token=token,
            on_update=on_update,
            save=save,
            save_partial=save_partial,
            options=opts,
        )


### SPECIFIC WAVEFORM MEASUREMENT CLASSES ###
class AMR(MagnetoTransport):
    """
    Performs the AMR measurement using the lockin amplifier and the stepper motor.

    Attributes:
        :type (str): Measurement type identifier ('amr')
        :angle_step (float): Step size for angle in degrees
        :total_angle (float): Total angle to rotate in degrees
        :amplitude (float): Peak voltage amplitude in volts
        :frequency (float): Excitation frequency in Hz
    """

    mtype = "amr"

    def __init__(
        self,
        dmm=None,
        calibrator=None,
        arduino=None,
        lockin=None,
        field=None,
        angle_step=15,
        total_angle=360,
        amplitude=1.0,
        frequency=10,
        measure_time=60,
        sensitivity="50uv/pa",
        save_dir=r"\scratch",
        voltage_callibration=10000,
        live_plot=True,
        plot_config=None,
    ):
        """
        Initialize AMR measurement parameters.

        Specializes MagnetoTransport for AMR measurements.
        """
        super().__init__(
            dmm=dmm,
            calibrator=calibrator,
            stepper=arduino,
            lockin=lockin,
            field=float(field) if field is not None else 0.0,
            save_dir=save_dir,
            voltage_calibration=float(voltage_callibration),
            live_plot=live_plot,
            plot_config=plot_config or {"x": "angle", "y": "X"},
        )
        self.arduino = arduino
        self.angle_step = angle_step
        self.total_angle = total_angle
        self.amplitude = amplitude
        self.frequency = frequency
        self.measure_time = measure_time
        self.sensitivity = sensitivity
        self.notes = str(amplitude).replace(".", "p") + "V_" + str(int(frequency)) + "Hz"
        self.metadata = pd.DataFrame(locals(), index=[0])
        del self.metadata["self"]
        self.metadata["mtype"] = self.mtype
        if self.lockin is not None and hasattr(self.lockin, "idn"):
            self.metadata["lockin"] = self.lockin.idn()
        if self.dmm is not None and hasattr(self.dmm, "idn"):
            self.metadata["dmm"] = self.dmm.idn()
        if self.arduino is not None and hasattr(self.arduino, "idn"):
            self.metadata["arduino"] = self.arduino.idn()
        self.metadata["timestamp"] = time.time()
        self.metadata["processed"] = False
        self.filename = create_measurement_filename(self.save_dir, self.mtype, self.notes)
        self.angle = 0  # initial angle

    def analyze(self):
        """Process AMR data."""
        if self.data is not None:
            print(f"Analysis succeeded, updated {self.filename}")
        else:
            print("No data to analyze. Capture the waveform first.")

    def configure_lockin(self):
        """Configure lock-in amplifier for AMR measurement."""
        self.lockin.initialize()
        self.lockin.configure_reference(voltage=self.amplitude, frequency=self.frequency)
        self.lockin.configure_input(input_configuration="a-b")
        self.lockin.configure_gain_filters(sensitivity=self.sensitivity)
        time.sleep(10)
        print("Lock-in amplifier configured for AMR measurement.")

    def capture_data(self):
        """Loop through angles and capture data at each step."""
        if self.angle_step > 0:
            direction = 1
        else:
            direction = 0
        steps = convert_angle_to_steps(self.angle_step)
        for angle in np.arange(0, self.total_angle, self.angle_step):
            while self.pause_requested:
                if self.abort_requested:
                    break
                time.sleep(0.5)

            if self.abort_requested:
                print("Measurement aborted by user.")
                break

            self.angle = angle
            print("capturing data at angle: ", self.angle)
            self.capture_data_point()
            self.save_data_point()
            self._update_live_plot()
            self.arduino.step(abs(steps), direction)
            time.sleep(1)

        # Legacy observation AMR-ANGLE-001 (repaired in Checkpoint 24b)
        if self.angle != self.total_angle and not self.abort_requested:
            self.angle = self.total_angle
            self.arduino.step(abs(steps), direction)
            time.sleep(1)
            self.capture_data_point()
            self.save_data_point()
            self._update_live_plot()

    def capture_data_point(self):
        """Take a single data point from the lockin with averaging."""
        current_time = time.time()
        x_avg_list = []
        y_avg_list = []
        while (time.time() - current_time) < self.measure_time:
            time.sleep(0.1)
            x, y = self.lockin.get_X_Y()
            x_avg_list.append(x)
            y_avg_list.append(y)
        x_avg = np.mean(x_avg_list)
        y_avg = np.mean(y_avg_list)
        if self.data is None:
            self.data = pd.DataFrame(
                {"angle": [self.angle], "field": [self.field], "X": [x_avg], "Y": [y_avg]}
            )
        else:
            self.data.loc[len(self.data)] = {
                "angle": self.angle,
                "field": self.field,
                "X": x_avg,
                "Y": y_avg,
            }
        print(f"Data point at angle {self.angle} degrees and field {self.field} Oe: X={x_avg}, Y={y_avg}")

    def save_data_point(self):
        """Save captured data to CSV file."""
        if self.data is not None and self.filename is not None:
            metadata_and_data_to_csv(self.metadata, self.data, self.filename)
            print(f"Data point saved to {self.filename}")
        else:
            print("No data to save. Capture the data point first.")

    def run_experiment(self, configure_lockin=True):
        """
        Legacy AMR execution workflow (preserved for Checkpoint 24a; migrated in 24b).
        """
        self.initialize()
        if configure_lockin:
            self.configure_lockin()
        self._init_live_plot()
        self.capture_data()
        self._close_live_plot()
        self.shut_off()
        self.analyze()
        self.plot_results()


# ----------------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------------

def convert_steps_to_angle(steps, steps_per_revolution=200) -> float:
    """Helper function to convert steps to an angle in degrees."""
    if not isinstance(steps_per_revolution, (int, np.integer)) or steps_per_revolution <= 0:
        raise ValueError(f"steps_per_revolution must be a positive integer, got {steps_per_revolution!r}")
    return float(steps) * 360.0 / float(steps_per_revolution)


def convert_angle_to_steps(angle, steps_per_revolution=200) -> int:
    """Helper function to convert an angle in degrees to steps."""
    if not isinstance(steps_per_revolution, (int, np.integer)) or steps_per_revolution <= 0:
        raise ValueError(f"steps_per_revolution must be a positive integer, got {steps_per_revolution!r}")
    angle_f = float(angle)
    if not math.isfinite(angle_f):
        raise ValueError(f"angle must be a finite number, got {angle!r}")
    return int(round(angle_f * steps_per_revolution / 360.0))


def convert_field_to_voltage(field, voltage_calibration=10000.0) -> float:
    """
    Convert magnetic field in Oe to calibrator control voltage in V.
    Default calibration is 10000.0 Oe/V (0.01 V for 100 Oe).
    """
    field_f = float(field)
    if not math.isfinite(field_f):
        raise ValueError(f"field must be a finite number, got {field!r}")
    cal_f = float(voltage_calibration)
    if not math.isfinite(cal_f) or cal_f <= 0:
        raise ValueError(f"voltage_calibration must be a positive finite number, got {voltage_calibration!r}")
    return field_f / cal_f


def convert_voltage_to_field(voltage, voltage_calibration=10000.0) -> float:
    """
    Convert sensor / calibrator voltage in V to magnetic field in Oe.
    Default calibration is 10000.0 Oe/V (100 Oe for 0.01 V).
    """
    v_f = float(voltage)
    if not math.isfinite(v_f):
        raise ValueError(f"voltage must be a finite number, got {voltage!r}")
    cal_f = float(voltage_calibration)
    if not math.isfinite(cal_f) or cal_f <= 0:
        raise ValueError(f"voltage_calibration must be a positive finite number, got {voltage_calibration!r}")
    return v_f * cal_f
