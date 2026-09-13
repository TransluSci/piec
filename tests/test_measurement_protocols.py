"""
Consolidated Scientific Protocol and Golden Verification Tests.

Consolidates:
- IV Sweep: known resistor response, ramp/step ordering and bounds, correct source programming,
  precedence of de-energizing before configuration, abort preservation, golden CSV regression.
- FE Hysteresis & PUND: pulse order and polarity, time alignment and pretrigger data,
  DC offset invariance on current, area/shunt scaling, plot staging cleanup on failure,
  golden CSV regressions for DiscreteWaveform, HysteresisLoop, and ThreePulsePund.
- MOKE: calibration direction and units, dual field modes (calibrated vs measured),
  cycle/direction structure, partial cycle exclusion from averaging, material memory,
  golden CSV regressions.
- AMR / Magneto-Transport: angular endpoints and quantization, no extra motion,
  field conversion, independent X/Y readouts, cos^2(theta) physical response,
  preservation of manual settings, shutdown of excitation, golden CSV regression.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from unittest.mock import MagicMock, Mock, call, patch

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
import pytest

from piec.analysis.field_calibration import FieldCalibration
from piec.analysis.hysteresis import (
    STANDARD_HYSTERESIS_COLUMNS,
    STANDARD_HYSTERESIS_UNITS,
    process_hysteresis,
)
from piec.analysis.pund import (
    STANDARD_PUND_COLUMNS,
    STANDARD_PUND_UNITS,
    process_pund,
)
from piec.analysis.utilities import standard_csv_to_metadata_and_data
from piec.measurement.adapters.amr import (
    AMRSetupProfile,
    FieldReader,
    FieldSource,
    OrientationController,
    TransportReadout,
)
from piec.measurement.amr import (
    AMR,
    convert_angle_to_steps,
    convert_field_to_voltage,
    convert_steps_to_angle,
    convert_voltage_to_field,
)
from piec.measurement.contracts import RunState, SafetyStatus
from piec.measurement.discrete_waveform import (
    DiscreteWaveform,
    HysteresisLoop,
    ThreePulsePund,
)
from piec.measurement.iv_sweep import IVSweep
from piec.measurement.moke import MokeMeasurement
from piec.simulation.hysteretic_magnetic_material import HystereticMagneticMaterial
from tests.fixtures.measurement_compatibility import (
    assert_data_columns_match,
    assert_golden_csv_matches,
    assert_numerical_data_matches_reference,
    assert_piec_csv_layout,
)
from tests.fixtures.virtual_setups import (
    amr_bench,
    fe_bench,
    iv_bench,
    moke_bench,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "measurement_compatibility"
IV_GOLDEN_PATH = FIXTURES_DIR / "iv_sweep_golden.csv"
DISCRETE_WAVEFORM_GOLDEN_PATH = FIXTURES_DIR / "discrete_waveform_golden.csv"
HYSTERESIS_LOOP_GOLDEN_PATH = FIXTURES_DIR / "hysteresis_loop_golden.csv"
THREE_PULSE_PUND_GOLDEN_PATH = FIXTURES_DIR / "three_pulse_pund_golden.csv"
MOKE_CAL_GOLDEN_PATH = FIXTURES_DIR / "moke_calibrated_golden.csv"
MOKE_MEAS_GOLDEN_PATH = FIXTURES_DIR / "moke_measured_golden.csv"
AMR_GOLDEN_PATH = FIXTURES_DIR / "amr_golden.csv"
AMR_SIGNAL_ATOL = 1e-10


# ============================================================================
# 1. IV Sweep Protocol & Resistor Response
# ============================================================================

class TestIVProtocols:
    """Scientific verification for IV sweep protocols."""

    def test_known_resistor_response(self):
        """Verify Ohm's law V = I * R across positive and negative sweep ranges."""
        resistance = 100.0
        bench, sm = iv_bench(resistance=resistance)
        iv = IVSweep(
            sourcemeter=sm,
            v_start=-1.0,
            v_stop=1.0,
            num_steps=21,
            dwell_time=0.0,
            sense_mode="2W",
        )
        df = iv.run_experiment(save=False)
        assert len(df) == 21
        assert list(df.columns) == ["voltage", "current"]

        expected_current = df["voltage"] / resistance
        np.testing.assert_allclose(df["current"], expected_current, rtol=1e-5, atol=1e-8)

    @pytest.mark.parametrize("start,stop", [(0.0, 1.0), (1.0, -1.0)])
    def test_all_voltage_transitions_respect_ramp_step(self, monkeypatch, start, stop):
        """Verify that every voltage step during sweep complies with max ramp_step bound."""
        bench, sm = iv_bench()
        voltages = []
        original_set = sm.set_source_voltage

        def record(channel=1, voltage=None):
            voltages.append(voltage)
            return original_set(channel=channel, voltage=voltage)

        monkeypatch.setattr(sm, "set_source_voltage", record)
        iv = IVSweep(sm, v_start=start, v_stop=stop, num_steps=2, ramp_step=0.1, dwell_time=0.0, ramp_delay=0.0)
        data = iv.run_experiment(save=False)
        assert all(abs(b - a) <= 0.10000001 for a, b in zip(voltages, voltages[1:]))
        assert data.voltage.tolist() == [start, stop]

    def test_source_configuration_and_energize_precedence(self, monkeypatch):
        """Verify output disabled BEFORE configuring energized source, then properly configured."""
        bench, sm = iv_bench()
        sm.output(channel=1, on=True)
        events = []
        for name in ("output", "idn", "configure_voltage_source", "set_sense_mode"):
            orig = getattr(sm, name)

            def record(*args, _name=name, _orig=orig, **kwargs):
                events.append((_name, kwargs))
                return _orig(*args, **kwargs)

            monkeypatch.setattr(sm, name, record)

        iv = IVSweep(sm, v_start=0.0, v_stop=1.0, num_steps=2, current_compliance=0.05, sense_mode="4W", dwell_time=0.0, ramp_delay=0.0)
        iv.run_experiment(save=False)

        # First hardware action must disable output
        assert events[0] == ("output", {"channel": 1, "on": False})
        # Last action disables output
        assert events[-1] == ("output", {"channel": 1, "on": False})
        assert sm.state["source_voltage"] == 0.0

    def test_stop_during_sweep_transition_preserves_data_and_zeros_source(self, monkeypatch):
        """Stop during sweep step transition aborts cleanly, retains points, and zeros source."""
        bench, sm = iv_bench()
        iv = IVSweep(sm, v_start=0.0, v_stop=1.0, num_steps=2, ramp_step=0.1, dwell_time=0.0, ramp_delay=0.0)
        original_set = sm.set_source_voltage

        def stop_at_half(channel=1, voltage=None):
            res = original_set(channel=channel, voltage=voltage)
            if voltage == pytest.approx(0.3) and iv.run_state == RunState.RUNNING:
                iv.request_stop()
            return res

        monkeypatch.setattr(sm, "set_source_voltage", stop_at_half)
        data = iv.run_experiment(save=False)
        assert iv.run_state == RunState.ABORTED
        assert len(data) >= 1
        assert sm.state["source_voltage"] == 0.0
        assert not sm.state["output_on"]

    def test_iv_sweep_golden_csv_regression(self, tmp_path):
        """Verify deterministic IV sweep run matches golden CSV."""
        bench, sm = iv_bench(resistance=100.0)
        iv = IVSweep(
            sourcemeter=sm,
            v_start=0.0,
            v_stop=1.0,
            num_steps=5,
            dwell_time=0.0,
            sense_mode="2W",
            output_dir=str(tmp_path),
        )
        iv.run_experiment()
        assert_golden_csv_matches(
            actual_path=iv.filename,
            golden_path=IV_GOLDEN_PATH,
            volatile_metadata_keys=["timestamp", "run_id"],
        )


# ============================================================================
# 2. FE Hysteresis & PUND Protocols
# ============================================================================

class TestHysteresisAndPundProtocols:
    """Scientific verification for ferroelectric hysteresis and PUND protocols."""

    @pytest.mark.parametrize("reset_amp", [-2.0, 2.0, 0.0])
    @pytest.mark.parametrize("p_u_amp", [-1.0, 1.0, 0.0])
    def test_analysis_polarity_matches_programmed_awg(self, reset_amp, p_u_amp):
        """Signed PUND pulse analysis polarity matches programmed AWG waveform plateaus."""
        awg = Mock()
        awg.arb_data_range = (2, 601)
        run = ThreePulsePund(
            awg,
            Mock(),
            reset_amp=reset_amp,
            p_u_amp=p_u_amp,
            offset=0.3,
            auto_timeshift=False,
            time_offset=0.0,
        )
        run.configure_awg()
        programmed = np.asarray(awg.create_arb_waveform.call_args.kwargs["data"])
        amplitude = abs(reset_amp) + abs(p_u_amp)
        t = np.linspace(0, 0.007, 701)
        result = process_pund(
            pd.DataFrame({"time": t, "voltage": np.zeros(len(t))}),
            reset_amp=reset_amp,
            p_u_amp=p_u_amp,
            reset_width=0.001,
            reset_delay=0.001,
            p_u_width=0.001,
            p_u_delay=0.001,
            area=1e-5,
            offset=0.3,
            auto_timeshift=False,
            time_offset=0.0,
        )
        for timestamp in (0.0005, 0.0015, 0.0025, 0.0035, 0.0045, 0.0055):
            awg_index = round(timestamp / 0.006 * (len(programmed) - 1))
            expected = programmed[awg_index] * amplitude + 0.3
            observed = result.data.loc[
                np.abs(result.data.time - timestamp).idxmin(), "applied_voltage"
            ]
            assert observed == pytest.approx(expected)

    def test_pund_dc_offset_includes_idle_and_does_not_alter_current(self, tmp_path):
        """DC offset shifts applied voltage by offset without changing current response."""
        m = ThreePulsePund(*fe_bench()[1:], output_dir=tmp_path, offset=2.0)
        result = m.run_experiment(save=False)
        zero = process_pund(m.raw_data, m.measurement_metadata, offset=0.0)
        np.testing.assert_allclose(result.applied_voltage, zero.data.applied_voltage + 2.0)
        np.testing.assert_allclose(result.current, zero.data.current)
        assert m.measurement_metadata["offset"] == 2.0

    def test_hysteresis_dc_offset_includes_idle_and_does_not_alter_current(self, tmp_path):
        """DC offset shifts hysteresis applied voltage without changing current."""
        m = HysteresisLoop(*fe_bench()[1:], output_dir=tmp_path, offset=2.0)
        result = m.run_experiment(save=False)
        zero = process_hysteresis(m.raw_data, m.measurement_metadata, offset=0.0)
        np.testing.assert_allclose(result.applied_voltage, zero.data.applied_voltage + 2.0)
        np.testing.assert_allclose(result.current, zero.data.current)
        assert m.measurement_metadata["offset"] == 2.0

    def test_waveform_timing_regularity(self):
        """Time step regularity and monotonic progression are strictly maintained."""
        bench, awg, osc = fe_bench()
        dw = DiscreteWaveform(awg=awg, osc=osc, length=0.001)
        dw.run_experiment(save=False)
        times = dw.raw_data["time"].to_numpy()
        dt = np.diff(times)
        assert np.all(dt > 0)
        assert len(times) >= 20

    def test_area_and_shunt_scaling(self):
        """Polarization scales inversely with capacitor area; current scales with shunt."""
        bench, awg, osc = fe_bench()
        h1 = HysteresisLoop(awg, osc, area=1e-5, r_shunt=100.0, frequency=1000.0, amplitude=1.0)
        h2 = HysteresisLoop(awg, osc, area=2e-5, r_shunt=100.0, frequency=1000.0, amplitude=1.0)
        df1 = h1.run_experiment(save=False)
        df2 = h2.run_experiment(save=False)
        # 2x area -> exactly 0.5x polarization
        np.testing.assert_allclose(df1["polarization"] * 0.5, df2["polarization"], rtol=1e-4)

    @pytest.mark.parametrize("failure_index", [1, 2])
    def test_plot_failure_cleans_all_pngs_and_figures(self, tmp_path, monkeypatch, failure_index):
        """Failure during plot save cleans all staged PNG files and figures."""
        m = ThreePulsePund(*fe_bench()[1:], output_dir=tmp_path)
        original = Figure.savefig
        count = 0

        def failing_save(fig, *args, **kwargs):
            nonlocal count
            count += 1
            if count == failure_index:
                raise OSError("plot write failed")
            return original(fig, *args, **kwargs)

        figures_before = plt.get_fignums()
        monkeypatch.setattr(Figure, "savefig", failing_save)
        with pytest.raises(OSError, match="plot write failed"):
            m.run_experiment(save=True)
        assert not list(tmp_path.glob("*.png"))
        assert plt.get_fignums() == figures_before
        assert m.recoverable_staging_paths

    def test_discrete_waveform_golden_csv_regression(self, tmp_path):
        """Verify deterministic DiscreteWaveform run matches golden CSV."""
        bench, awg, osc = fe_bench()
        dw = DiscreteWaveform(
            awg=awg,
            osc=osc,
            v_div=0.01,
            voltage_channel="1",
            output_dir=str(tmp_path),
        )
        dw.run_experiment(save=True)
        assert_golden_csv_matches(
            actual_path=dw.filename,
            golden_path=DISCRETE_WAVEFORM_GOLDEN_PATH,
            volatile_metadata_keys=["timestamp", "run_id"],
        )

    def test_hysteresis_loop_golden_csv_regression(self, tmp_path):
        """Verify deterministic HysteresisLoop run matches golden CSV."""
        bench, awg, osc = fe_bench()
        hl = HysteresisLoop(
            awg=awg,
            osc=osc,
            frequency=1000.0,
            amplitude=1.0,
            offset=0.0,
            n_cycles=2,
            area=1e-5,
            time_offset=1e-8,
            show_plots=False,
            save_plots=False,
            auto_timeshift=False,
            output_dir=str(tmp_path),
        )
        hl.run_experiment(save=True)
        assert_golden_csv_matches(
            actual_path=hl.filename,
            golden_path=HYSTERESIS_LOOP_GOLDEN_PATH,
            volatile_metadata_keys=["timestamp", "run_id"],
        )

    def test_three_pulse_pund_golden_csv_regression(self, tmp_path):
        """Verify deterministic ThreePulsePund run matches golden CSV."""
        bench, awg, osc = fe_bench()
        pund = ThreePulsePund(
            awg=awg,
            osc=osc,
            reset_amp=1.0,
            reset_width=1e-3,
            reset_delay=1e-3,
            p_u_amp=1.0,
            p_u_width=1e-3,
            p_u_delay=1e-3,
            offset=0.0,
            area=1e-5,
            time_offset=1e-8,
            show_plots=False,
            save_plots=False,
            auto_timeshift=True,
            output_dir=str(tmp_path),
        )
        pund.run_experiment(save=True)
        assert_golden_csv_matches(
            actual_path=pund.filename,
            golden_path=THREE_PULSE_PUND_GOLDEN_PATH,
            volatile_metadata_keys=["timestamp", "run_id"],
        )


# ============================================================================
# 3. MOKE Protocols
# ============================================================================

class TestMokeProtocols:
    """Scientific verification for MOKE protocols."""

    def _create_moke(self, **kwargs):
        unit = kwargs.get("calibration", FieldCalibration([(-5, -500), (0, 0), (1, 100), (5, 500)])).output_unit
        bench, source, detector = moke_bench(output_unit=unit)
        options = dict(
            calibration=FieldCalibration([(-5, -500), (0, 0), (1, 100), (5, 500)], name="example"),
            output_values=[-5, 0, 5, 0, -5],
            compliance=0.01,
            max_output_step=1.0,
            dwell_time=0,
            ramp_delay=0,
            n_cycles=2,
        )
        options.update(kwargs)
        return MokeMeasurement(source, detector, **options)

    def test_current_output_calibration_selects_current_source(self):
        """Using an Ampere calibration automatically programs sourcemeter as current source."""
        run = self._create_moke(
            calibration=FieldCalibration([(-0.5, -500), (0.5, 500)], output_unit="A"),
            output_values=[-0.5, 0.5, -0.5],
            compliance=10,
        )
        run.dmm.get_voltage = Mock(return_value=0.123)
        run.run_experiment(save=False)
        assert run.sourcemeter.state["source_func"] == "CURR"
        assert run.sourcemeter.state["voltage_compliance"] == 10
        assert run.data["field_calibrated"].tolist() == [-500, 500, -500] * 2
        assert run.sourcemeter.state["source_current"] == 0.0

    def test_cycle_and_direction_structure(self):
        """Cycles, point sequence, and direction indicators (+1/-1) are accurately tracked."""
        run = self._create_moke()
        data = run.run_experiment(save=False)
        assert len(data) == 10
        assert run.completed_cycles == 2
        # Direction: -5 to 0 (+1), 0 to 5 (+1), 5 to 0 (-1), 0 to -5 (-1)
        cycle0 = data[data["cycle"] == 0]
        assert cycle0["direction"].tolist() == [1, 1, 1, -1, -1]

    def test_partial_cycle_on_stop_is_not_averaged(self):
        """Interrupted cycle is excluded from cycle_average calculation."""
        run = self._create_moke()

        def stop_after_seven(snapshot):
            if len(snapshot.raw) == 7:
                run.request_stop()

        run.run_experiment(on_update=stop_after_seven, save=False)
        assert len(run.data) == 7
        assert run.completed_cycles == 1
        assert len(run.last_cycle) == 5
        assert run.cycle_average["cycles_averaged"].tolist() == [1] * 5

    def test_material_remanence_and_history(self):
        """Magnetic hysteretic material preserves memory and opposite remanence at zero field."""
        material = HystereticMagneticMaterial()
        assert material.response([-500, 0, 500, 0, -500]).tolist() == [-1, -1, 1, 1, -1]
        assert material.apply_field(0) == -1
        partial = material.apply_field(50)
        assert -1 < partial < 1
        assert material.apply_field(0) == partial

    def test_moke_calibrated_golden_csv_regression(self, tmp_path):
        """Verify deterministic calibrated MOKE run matches golden CSV."""
        cal = FieldCalibration([(-5.0, -500.0), (0.0, 0.0), (5.0, 500.0)], name="golden_cal")
        bench, source, detector = moke_bench(linear=True)
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=detector,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.0,
            ramp_delay=0.0,
            n_cycles=1,
            average_cycles=1,
            output_dir=str(tmp_path),
        )
        moke.run_experiment(save=True)
        assert_golden_csv_matches(
            actual_path=moke.filename,
            golden_path=MOKE_CAL_GOLDEN_PATH,
            time_columns=("time", "field_time"),
            volatile_metadata_keys=["timestamp", "save_dir", "filename"],
        )

    def test_moke_measured_golden_csv_regression(self, tmp_path):
        """Verify deterministic measured-field MOKE run matches golden CSV."""
        cal = FieldCalibration([(-5.0, -500.0), (0.0, 0.0), (5.0, 500.0)], name="golden_cal")
        bench, source, detector = moke_bench(linear=True)
        moke = MokeMeasurement(
            sourcemeter=source,
            dmm=detector,
            calibration=cal,
            output_values=[-5.0, 0.0, 5.0, 0.0, -5.0],
            compliance=0.01,
            max_output_step=5.0,
            dwell_time=0.0,
            ramp_delay=0.0,
            n_cycles=1,
            average_cycles=1,
            field_reader=Mock(return_value=50.0),
            field_reader_unit="Oe",
            field_reader_name="test_gaussmeter",
            output_dir=str(tmp_path),
        )
        moke.run_experiment(save=True)
        assert_golden_csv_matches(
            actual_path=moke.filename,
            golden_path=MOKE_MEAS_GOLDEN_PATH,
            time_columns=("time", "field_time"),
            volatile_metadata_keys=["timestamp", "save_dir", "filename"],
        )


# ============================================================================
# 4. AMR & Magneto-Transport Protocols
# ============================================================================

class TestAmrAndMagnetoTransportProtocols:
    """Scientific verification for AMR and Magneto-Transport protocols."""

    def test_angular_endpoints_and_quantization(self):
        """Steps and angles convert accurately for cardinal angles and fractional quantization."""
        assert convert_angle_to_steps(0.0) == 0
        assert convert_angle_to_steps(90.0) == 50
        assert convert_angle_to_steps(180.0) == 100
        assert convert_angle_to_steps(360.0) == 200
        assert convert_angle_to_steps(-90.0) == -50

        assert convert_steps_to_angle(0) == pytest.approx(0.0)
        assert convert_steps_to_angle(50) == pytest.approx(90.0)
        assert convert_steps_to_angle(200) == pytest.approx(360.0)

        # Fractional angle rounds to nearest integer step
        assert convert_angle_to_steps(1.8) == 1
        assert convert_angle_to_steps(0.8) == 0

    def test_field_conversion(self):
        """Linear field-to-voltage and voltage-to-field conversions."""
        cal = 10000.0  # Oe/V
        assert convert_field_to_voltage(0.0, cal) == pytest.approx(0.0)
        assert convert_field_to_voltage(100.0, cal) == pytest.approx(0.01)
        assert convert_field_to_voltage(-500.0, cal) == pytest.approx(-0.05)

        assert convert_voltage_to_field(0.01, cal) == pytest.approx(100.0)
        assert convert_voltage_to_field(-0.05, cal) == pytest.approx(-500.0)

    def test_no_extra_motion_during_sweep(self):
        """Stepper moves only to requested angles without overshoot or spurious steps."""
        instruments = amr_bench()[1]
        stepper = instruments["arduino"]
        stepper.set_steps_per_rev(200)

        amr = AMR(
            dmm=instruments["dmm"],
            calibrator=instruments["calibrator"],
            stepper=stepper,
            lockin=instruments["lockin"],
            total_angle=180.0,
            angle_step=45.0,
            field=100.0,
            amplitude=1.0,
            frequency=10.0,
            measure_time=0.01,
            settling_time=0.0,
            shutdown_handler=lambda: None,
        )
        df = amr.run_experiment(save=False)
        assert df["angle"].tolist() == [0.0, 45.0, 90.0, 135.0, 180.0]
        assert stepper.get_angle() == pytest.approx(180.0)

    def test_independent_xy_lockin_readouts(self):
        """Lock-in in-phase X and quadrature Y readouts recorded independently without crosstalk."""
        instruments = amr_bench()[1]
        amr = AMR(
            dmm=instruments["dmm"],
            calibrator=instruments["calibrator"],
            stepper=instruments["arduino"],
            lockin=instruments["lockin"],
            total_angle=90.0,
            angle_step=90.0,
            field=100.0,
            amplitude=1.0,
            frequency=10.0,
            measure_time=0.01,
            settling_time=0.0,
            shutdown_handler=lambda: None,
        )
        df = amr.run_experiment(save=False)
        assert "x" in df.columns
        assert "y" in df.columns
        assert df["x"].to_numpy() is not df["y"].to_numpy()

    def test_amr_cos2_theta_physical_dependence(self, tmp_path):
        """
        Verify physical AMR angular dependence:
        R(theta) = R_perp + delta_R * cos^2(theta).
        Signal x is maximal at theta = 0, 180 deg and minimal at theta = 90 deg.
        """
        bench, instruments = amr_bench(100.0, 10.0, 10000.0, golden=True)
        shutdown = Mock()
        amr = AMR(
            dmm=instruments["dmm"],
            calibrator=instruments["calibrator"],
            stepper=instruments["arduino"],
            lockin=instruments["lockin"],
            field=100.0,
            angle_step=45.0,
            total_angle=180.0,
            amplitude=1.0,
            frequency=10,
            measure_time=0.01,
            settling_time=0.0,
            sensitivity="50uv/pa",
            output_dir=tmp_path,
            shutdown_handler=shutdown,
        )
        df = amr.run_experiment(save=False)
        x_vals = df["x"].to_numpy()
        # R(0) > R(90) and R(180) > R(90)
        assert x_vals[0] > x_vals[2]
        assert x_vals[4] > x_vals[2]
        # R(0) approx R(180)
        assert x_vals[0] == pytest.approx(x_vals[4], rel=1e-2)

    def test_preservation_of_manually_owned_settings(self):
        """readout_configuration='preserve' does not modify lock-in parameters."""
        instruments = amr_bench()[1]
        lockin = instruments["lockin"]
        lockin.state["reference_frequency"] = 77.0

        amr = AMR(
            dmm=instruments["dmm"],
            calibrator=instruments["calibrator"],
            stepper=instruments["arduino"],
            lockin=lockin,
            field=100.0,
            total_angle=0.0,
            angle_step=10.0,
            measure_time=0.01,
            settling_time=0.0,
            readout_configuration="preserve",
            shutdown_handler=lambda: None,
        )
        amr.run_experiment(save=False)
        assert lockin.state["reference_frequency"] == 77.0

    def test_shutdown_of_measurement_owned_excitation(self):
        """Field source output is zeroed upon safe shutdown."""
        instruments = amr_bench()[1]
        calibrator = instruments["calibrator"]

        amr = AMR(
            dmm=instruments["dmm"],
            calibrator=calibrator,
            stepper=instruments["arduino"],
            lockin=instruments["lockin"],
            field=500.0,
            total_angle=0.0,
            angle_step=10.0,
            measure_time=0.01,
            settling_time=0.0,
            shutdown_handler=lambda: None,
        )
        amr.run_experiment(save=False)
        assert calibrator.state["voltage"] == 0.0

    def test_amr_golden_csv_regression(self, tmp_path):
        """Verify deterministic AMR sweep matches golden CSV."""
        bench, instruments = amr_bench(100.0, 2.0, 10000.0, golden=True)
        shutdown = Mock()
        with patch("time.sleep", return_value=None):
            amr = AMR(
                dmm=instruments["dmm"],
                calibrator=instruments["calibrator"],
                stepper=instruments["arduino"],
                lockin=instruments["lockin"],
                field=100.0,
                angle_step=45.0,
                total_angle=180.0,
                amplitude=1.0,
                frequency=10,
                measure_time=0.01,
                settling_time=0.0,
                sensitivity="50uv/pa",
                output_dir=tmp_path,
                shutdown_handler=shutdown,
            )
            amr.run_experiment(save=True)
        assert_golden_csv_matches(
            actual_path=amr.filename,
            golden_path=AMR_GOLDEN_PATH,
            float_tolerance=AMR_SIGNAL_ATOL,
            volatile_metadata_keys=["timestamp", "run_id"],
        )
