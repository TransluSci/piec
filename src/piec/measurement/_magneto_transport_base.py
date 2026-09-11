"""Standardized magneto-transport lifecycle, independent of the pending AMR migration."""
import json
import math
import time

import pandas as pd

from .base import BaseMeasurement
from .contracts import HardwareSafetyError


class MagnetoTransport(BaseMeasurement):
    """Acquire a transport point using a declared setup and shared execution ownership.

    Constructors do no I/O. Use run_experiment or a session for hardware work.
    Field units come from the setup; readback remains separate from commanded field.
    The excitation shutdown handler is mandatory before any execution.
    Pause acts before acquisition, retains the field, and is woken by Stop.
    """
    mtype = "magneto_transport"
    measurement_schema = "amr"
    measurement_schema_version = 1
    supports_pause = True
    ordered_columns = ("angle", "field", "x", "y")
    column_units = {"angle": "deg", "field": "Oe", "x": "V", "y": "V"}
    raw_column_units = column_units

    def __init__(self, dmm=None, calibrator=None, stepper=None, lockin=None, *,
                 field=0.0, output_dir=None, profile=None, voltage_calibration=10000.0,
                 metadata=None, readout_configuration=None, excitation_source="internal",
                 shutdown_handler=None, external_source_owner=None, field_settling_time=0.0):
        from .adapters.amr import AMRSetupProfile
        self.field = float(field)
        self.voltage_calibration = float(voltage_calibration)
        self.field_settling_time = float(field_settling_time)
        if not math.isfinite(self.field):
            raise ValueError("field must be a finite number")
        if not math.isfinite(self.voltage_calibration) or self.voltage_calibration <= 0:
            raise ValueError("voltage_calibration must be a positive finite number")
        if not math.isfinite(self.field_settling_time) or self.field_settling_time < 0:
            raise ValueError("field_settling_time must be non-negative and finite")
        if profile is not None:
            if not isinstance(profile, AMRSetupProfile):
                raise TypeError("profile must be an AMRSetupProfile")
            if any(value is not None for value in (dmm, calibrator, stepper, lockin, shutdown_handler, external_source_owner)):
                raise ValueError("Supply a profile or individual instruments/settings, not both")
        elif calibrator is not None and stepper is not None and lockin is not None:
            profile = AMRSetupProfile.from_instruments(
                dmm=dmm, calibrator=calibrator, arduino=stepper, lockin=lockin,
                field_calibration=self.voltage_calibration,
                reader_calibration=self.voltage_calibration if dmm is not None else None,
                readout_configuration=readout_configuration or "preserve",
                excitation_source=excitation_source, shutdown_handler=shutdown_handler,
                external_source_owner=external_source_owner)
        self._profile = profile
        self.dmm = profile.field_reader.instrument if profile and profile.field_reader else dmm
        self.calibrator = profile.field_source.instrument if profile else calibrator
        self.stepper = profile.orientation_controller.instrument if profile else stepper
        self.lockin = profile.transport_readout.instrument if profile else lockin
        self.readout_configuration = self._policy(readout_configuration if readout_configuration is not None
            else profile.transport_readout.readout_configuration if profile else "preserve")
        unit = profile.field_source.field_unit if profile else "Oe"
        units = {"angle": "deg", "field": unit, "x": "V", "y": "V"}
        if profile and profile.field_reader:
            units.update(field_measured=profile.field_reader.field_unit, field_time="s")
        self.ordered_columns = tuple(units)
        info = dict(metadata or {})
        info.update(field=self.field, field_basis="commanded", signal_mode="lockin_xy")
        if profile:
            source = profile.field_source
            info.update(field_source_mode=source.mode, field_source_name=source.name,
                        source_output_unit=source.output_unit,
                        excitation_source=profile.transport_readout.excitation_source,
                        excitation_settings_provenance="user_declared_unverified")
            if source.mode == "linear":
                info["field_source_scale"] = source.calibration
            elif source.mode == "table":
                info["field_source_calibration_json"] = json.dumps(source.calibration.to_dict(), separators=(",", ":"))
            if profile.transport_readout.external_source_owner:
                info["external_source_owner"] = profile.transport_readout.external_source_owner
            if profile.field_reader:
                info.update(field_reader_name=profile.field_reader.name,
                            field_reader_mode=profile.field_reader.mode,
                            field_absolute_tolerance=profile.field_reader.absolute_tolerance,
                            field_relative_tolerance=profile.field_reader.relative_tolerance,
                            field_mismatch_policy=profile.field_reader.mismatch_policy)
                reader = profile.field_reader
                if reader.mode == "linear":
                    info["field_reader_scale"] = reader.calibration
                elif reader.mode == "table":
                    info["field_reader_calibration_json"] = json.dumps(reader.calibration.to_dict(), separators=(",", ":"))
        super().__init__(output_dir=output_dir, measurement_schema="amr",
                         column_units=units, raw_column_units=units, metadata=info)

    @staticmethod
    def _policy(value):
        if value not in ("preserve", "configure"):
            raise ValueError("readout_configuration must be 'preserve' or 'configure'")
        return value

    @property
    def profile(self):
        return self._profile

    @property
    def field_source(self):
        return self.profile.field_source if self.profile else None

    @property
    def field_reader(self):
        return self.profile.field_reader if self.profile else None

    @property
    def transport_readout(self):
        return self.profile.transport_readout if self.profile else None

    @property
    def orientation_controller(self):
        return self.profile.orientation_controller if self.profile else None

    @property
    def metadata(self):
        return self.measurement_metadata

    def _validate_options(self, options):
        super()._validate_options(options)
        opts = options or {}
        unknown = set(opts) - {"configure_lockin", "readout_configuration"}
        if unknown:
            raise ValueError(f"Unknown option: {', '.join(sorted(unknown))}")
        if "configure_lockin" in opts and type(opts["configure_lockin"]) is not bool:
            raise ValueError("configure_lockin must be bool")
        if "readout_configuration" in opts:
            self._policy(opts["readout_configuration"])
        if "configure_lockin" in opts and "readout_configuration" in opts:
            raise ValueError("Specify only one readout configuration option")
        if self.profile is None:
            raise ValueError("MagnetoTransport requires instruments or profile to execute")
        if not callable(self.transport_readout.shutdown_handler):
            raise HardwareSafetyError("Excitation shutdown handler required before energizing, but none declared")
        # Validate the entire field command before lock-in settings can energize excitation.
        self.field_source.compute_output(self.field)

    def _wait(self, duration=0.0, *, pause=False):
        deadline = time.monotonic() + duration
        while not self._coordinator.is_stop_requested:
            remaining = deadline - time.monotonic()
            if remaining <= 0 and not (pause and self._coordinator.is_pause_requested):
                return True
            time.sleep(min(.02, max(0.001, remaining)) if remaining > 0 else .02)
        return False

    def _configure_instruments(self, request):
        self._validate_options(request.options)
        self._field_time_origin = time.monotonic()
        for index, instrument in enumerate(self.profile.unique_instruments()):
            if self._coordinator.is_stop_requested:
                return
            identify = getattr(instrument, "idn", None)
            if callable(identify):
                self.measurement_metadata[f"instrument_{index}"] = str(identify())
        opts = request.options or {}
        policy = opts.get("readout_configuration", self.readout_configuration)
        if "configure_lockin" in opts:
            policy = "configure" if opts["configure_lockin"] else "preserve"
        self.measurement_metadata["readout_configuration"] = policy
        if self._coordinator.is_stop_requested:
            return
        saved = self.transport_readout.readout_configuration
        try:
            self.transport_readout.readout_configuration = policy
            self.transport_readout.configure()
        finally:
            self.transport_readout.readout_configuration = saved
        if self._coordinator.is_stop_requested:
            return
        self.field_source.set_field(self.field)
        if not self._wait(self.field_settling_time):
            return
        if self.field_reader:
            self.field_reader.verify_field(self.field)  # Errors and fail-policy mismatches propagate.

    def _capture_data(self, request, on_update=None):
        if not self._wait(pause=True):
            return pd.DataFrame(columns=self.ordered_columns)
        row = {"angle": float(self.orientation_controller.current_angle), "field": self.field}
        if self.field_reader:
            measured, _ = self.field_reader.read_field()
            self.field_reader.verify_field(self.field, measured)
            row.update(field_measured=measured, field_time=time.monotonic() - self._field_time_origin)
        if self._coordinator.is_stop_requested:
            return pd.DataFrame(columns=self.ordered_columns)
        row.update(self.transport_readout.read_signals())
        frame = pd.DataFrame([row], columns=self.ordered_columns)
        self._raw_data = frame.copy()
        self._data = frame.copy()
        snapshot = self.publish_snapshot(views={"raw": frame}, completed_steps=1, total_steps=1)
        if on_update:
            on_update(snapshot)
        return frame

    def _safe_shutdown(self, recorder):
        if self.profile:
            for name, role in (("field_source", self.field_source),
                               ("orientation_controller", self.orientation_controller),
                               ("transport_readout", self.transport_readout)):
                recorder.record_action(name=name + "_shutdown", action_fn=role.safe_shutdown)
        return recorder.build_report()
