"""Small, independently specified setups for the common measurement contract."""
from dataclasses import dataclass
import inspect
from unittest.mock import Mock

from piec.analysis.field_calibration import FieldCalibration
from piec.measurement.discrete_waveform import DiscreteWaveform, HysteresisLoop, ThreePulsePund
from piec.measurement.iv_sweep import IVSweep
from piec.measurement.moke import MokeMeasurement
from piec.measurement.magneto_transport import AMR, MagnetoTransport
from tests.fixtures.virtual_setups import iv_bench, moke_bench, fe_bench, amr_bench


@dataclass(frozen=True)
class MeasurementCase:
    cls: type
    family: str
    invalid_options: dict
    schema: str
    units: dict

    @property
    def name(self):
        return self.cls.__name__

    @property
    def sensor(self):
        return {"iv": ("source", "get_current"), "moke": ("detector", "get_voltage"),
                "fe": ("osc", "get_data"), "amr": ("lockin", "quick_read")}[self.family]

    @property
    def has_multiple_reads(self):
        return self.family in ("iv", "moke") or self.cls is AMR

    def build(self, monkeypatch, **overrides):
        if self.family == "iv":
            _, source = iv_bench()
            instruments = {"source": source}
            options = dict(sourcemeter=source, v_start=0., v_stop=1., num_steps=5,
                           ramp_delay=0., dwell_time=0.)
        elif self.family == "moke":
            _, source, detector = moke_bench(linear=True)
            instruments = {"source": source, "detector": detector}
            options = dict(sourcemeter=source, dmm=detector,
                           calibration=FieldCalibration([(-5., -500.), (5., 500.)]),
                           output_values=[0., 1., 0.], compliance=.1, max_output_step=.5,
                           dwell_time=0., ramp_delay=0., n_cycles=1)
        elif self.family == "fe":
            _, awg, osc = fe_bench(points=50)
            instruments = {"awg": awg, "osc": osc}
            options = dict(awg=awg, osc=osc)
            if self.cls is DiscreteWaveform:
                options.update(v_div=1., length=.001)
            else:
                options.update(show_plots=False, save_plots=False)
        else:
            _, instruments = amr_bench()
            options = dict(calibrator=instruments["calibrator"], dmm=instruments["dmm"],
                           stepper=instruments["arduino"], lockin=instruments["lockin"],
                           field=100.)
            if self.cls is AMR:
                options.update(angle_step=90., total_angle=90., settling_time=0., measure_time=.001)

        # Observe real virtual methods, including calls made by constructors.
        calls = {}
        for role, instrument in instruments.items():
            for name, method in inspect.getmembers(instrument, inspect.ismethod):
                if not name.startswith("_") and method.__self__ is instrument:
                    spy = Mock(wraps=method)
                    spy.__signature__ = inspect.signature(method)
                    monkeypatch.setattr(instrument, name, spy)
                    calls[role, name] = spy
        if self.family == "amr":
            # The fixture owns an actual virtual excitation shutdown policy.
            shutdown = Mock(side_effect=lambda: setattr(instruments["lockin"], "excitation_current", 0.))
            calls["setup", "shutdown"] = shutdown
            options["shutdown_handler"] = shutdown

        options.update(overrides)
        return instruments, calls, lambda: self.cls(**options)

    def assert_safe(self, instruments, calls):
        for (role, name), spy in calls.items():
            if name == "close":
                spy.assert_not_called()
        if self.family in ("iv", "moke"):
            source = instruments["source"]
            assert source.state["output_on"] is False
            assert source.state["source_voltage"] == 0.
            assert any(c.kwargs.get("on") is False for c in calls["source", "output"].call_args_list)
        elif self.family == "fe":
            awg = instruments["awg"]
            assert all(awg.state["output"][ch] is False for ch in awg.channel)
            assert awg.state["amplitude"][1] == 0.
            calls["awg", "set_amplitude"].assert_called()
        else:
            assert instruments["calibrator"].state["voltage"] == 0.
            assert instruments["calibrator"].state["output_on"] is False
            assert instruments["arduino"].state["moving"] is False
            calls["arduino", "halt"].assert_called()
            calls["setup", "shutdown"].assert_called_once()
            assert instruments["lockin"].excitation_current == 0.


FE_UNITS = {"time": "s", "voltage": "V", "current": "A",
            "polarization": "uC/cm^2", "applied_voltage": "V"}
AMR_UNITS = {"angle": "deg", "field": "Oe", "x": "V", "y": "V"}
MEASUREMENT_CASES = [
    MeasurementCase(IVSweep, "iv", {"v_start": float("nan")}, "iv_sweep",
                    {"voltage": "V", "current": "A"}),
    MeasurementCase(MokeMeasurement, "moke", {"compliance": -1.}, "moke",
                    {"time": "s", "cycle": None, "point": None, "direction": None,
                     "source_output": "V", "field_calibrated": "Oe", "detector_voltage": "V"}),
    MeasurementCase(DiscreteWaveform, "fe", {"v_div": -1.}, "discrete_waveform",
                    {"time": "s", "voltage": "V"}),
    MeasurementCase(HysteresisLoop, "fe", {"amplitude": float("nan")}, "hysteresis", FE_UNITS),
    MeasurementCase(ThreePulsePund, "fe", {"reset_width": -1.}, "three_pulse_pund",
                    dict(FE_UNITS, **{name: "uC/cm^2" for name in (
                        "polarization_p_hat", "polarization_p_star", "polarization_p_hat_r",
                        "polarization_p_star_r", "delta_polarization")})),
    MeasurementCase(AMR, "amr", {"field": float("nan")}, "amr", AMR_UNITS),
    MeasurementCase(MagnetoTransport, "amr", {"field": float("nan")}, "amr",
                    dict(AMR_UNITS, field_measured="Oe", field_time="s")),
]
