"""
Characterization and regression tests for DiscreteWaveform, HysteresisLoop, and ThreePulsePund.

Stage 0 Checkpoint 2c: FE and PUND characterization fixtures and golden comparison.
"""

from pathlib import Path
import tempfile
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from piec.analysis.utilities import standard_csv_to_metadata_and_data
from tests.fixtures.virtual_setups import fe_bench
from piec.analysis.hysteresis import (
    STANDARD_HYSTERESIS_COLUMNS,
    STANDARD_HYSTERESIS_UNITS,
)
from piec.analysis.pund import (
    STANDARD_PUND_COLUMNS,
    STANDARD_PUND_UNITS,
)
from piec.measurement.discrete_waveform import (
    DiscreteWaveform,
    HysteresisLoop,
    ThreePulsePund,
)
from piec.measurement.persistence import read_measurement_csv
from tests.fixtures.measurement_compatibility import (
    assert_data_columns_match,
    assert_golden_csv_matches,
    assert_numerical_data_matches_reference,
    assert_piec_csv_layout,
    load_manifest,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "measurement_compatibility"
DISCRETE_WAVEFORM_GOLDEN_PATH = FIXTURES_DIR / "discrete_waveform_golden.csv"
HYSTERESIS_LOOP_GOLDEN_PATH = FIXTURES_DIR / "hysteresis_loop_golden.csv"
THREE_PULSE_PUND_GOLDEN_PATH = FIXTURES_DIR / "three_pulse_pund_golden.csv"


class TestDiscreteWaveformCompatibility:
    """Verify standardized DiscreteWaveform behavior and regression goldens."""

    def test_discrete_waveform_constructor_and_attributes(self, tmp_path):
        bench, awg, osc = fe_bench()
        dw = DiscreteWaveform(
            awg=awg,
            osc=osc,
            v_div=0.02,
            voltage_channel="2",
            length=0.002,
            osc_channel=1,
            output_dir=str(tmp_path),
        )

        assert dw.awg is awg
        assert dw.osc is osc
        assert dw.v_div == 0.02
        assert dw.voltage_channel == "2"
        assert dw.length == 0.002
        assert dw.osc_channel == 1
        assert dw.output_dir == Path(tmp_path)
        assert dw.data is None
        assert dw.filename is None
        assert dw.history == []
        assert dw.mtype == "discrete_waveform"
        assert dw.measurement_schema == "discrete_waveform"
        assert dw.column_units == {"time": "s", "voltage": "V"}

        # Target contract: zero hardware I/O in __init__
        assert osc.state["armed"] is False

    def test_discrete_waveform_instrument_configuration(self, tmp_path):
        bench, awg, osc = fe_bench()
        dw = DiscreteWaveform(
            awg=awg,
            osc=osc,
            v_div=0.05,
            voltage_channel="1",
            length=0.001,
            output_dir=str(tmp_path),
        )

        dw.configure_instruments()
        assert awg.state["load_impedance"][1] == 50.0
        assert str(awg.state["trigger_source"][1]).upper() == "MAN"

        assert osc.state["armed"] is False
        assert osc.state["tdiv"] == pytest.approx(dw.length / 8)
        assert osc.state["vdiv"][1] == pytest.approx(0.05)
        assert str(osc.state["trigger_source"]).upper() == "EXT"
        assert str(osc.state["trigger_sweep"]).upper() == "NORM"

    def test_discrete_waveform_raw_capture_and_save(self, tmp_path):
        bench, awg, osc = fe_bench()
        dw = DiscreteWaveform(
            awg=awg,
            osc=osc,
            v_div=0.01,
            voltage_channel="1",
            output_dir=str(tmp_path),
        )

        result = dw.run_experiment(save=True)

        assert isinstance(result, pd.DataFrame)
        assert_data_columns_match(result, ["time", "voltage"], exact_order=True)
        assert len(result) == 70  # 50 simulation points + 20 prep points

        assert dw.filename is not None
        assert Path(dw.filename).is_file()

        meta, data = assert_piec_csv_layout(dw.filename)
        assert len(meta) == 1
        assert len(data) == 70
        assert_data_columns_match(data, ["time", "voltage"], exact_order=True)

    def test_discrete_waveform_golden_csv_regression(self, tmp_path):
        """Verify that deterministic raw capture matches golden CSV."""
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

    def test_discrete_waveform_numerical_equivalence_with_mapping(self, tmp_path):
        """Verify numerical equivalence using the harness old_to_new_column_mapping with view='raw'."""
        from piec.measurement.persistence import read_measurement_csv

        bench, awg, osc = fe_bench()
        dw = DiscreteWaveform(
            awg=awg,
            osc=osc,
            v_div=0.01,
            voltage_channel="1",
            output_dir=str(tmp_path),
        )
        dw.run_experiment(save=True)

        _, gold_data, _ = read_measurement_csv(DISCRETE_WAVEFORM_GOLDEN_PATH)
        assert_numerical_data_matches_reference(dw.data, gold_data, "DiscreteWaveform", view="raw")


class TestHysteresisLoopCompatibility:
    """Characterize migrated HysteresisLoop behavior and verify regression goldens."""

    def test_hysteresis_constructor_and_attributes(self, tmp_path):
        bench, awg, osc = fe_bench()
        hl = HysteresisLoop(
            awg=awg,
            osc=osc,
            v_div=0.1,
            frequency=500.0,
            amplitude=2.0,
            offset=0.1,
            n_cycles=3,
            voltage_channel="1",
            area=2e-5,
            time_offset=2e-8,
            show_plots=False,
            save_plots=False,
            auto_timeshift=True,
            output_dir=str(tmp_path),
        )

        assert hl.awg is awg
        assert hl.osc is osc
        assert hl.mtype == "hysteresis"
        assert hl.measurement_schema == "hysteresis"
        assert hl.column_units == STANDARD_HYSTERESIS_UNITS
        assert hl.frequency == 500.0
        assert hl.amplitude == 2.0
        assert hl.offset == 0.1
        assert hl.n_cycles == 3
        assert hl.area == 2e-5
        assert hl.time_offset == 2e-8
        assert hl.voltage_channel == "1"
        assert hl.show_plots is False
        assert hl.save_plots is False
        assert hl.auto_timeshift is True
        assert hl.length == pytest.approx(1 / 500.0)
        assert hl.output_dir == Path(tmp_path)
        assert hl.data is None
        assert hl.filename is None
        assert hl.history == []

        # Target contract: zero hardware I/O in __init__
        assert osc.state["armed"] is False

        # Must reject legacy save_dir
        with pytest.raises(TypeError):
            HysteresisLoop(awg=awg, osc=osc, save_dir=str(tmp_path))

    def test_hysteresis_configure_awg(self):
        bench, awg, osc = fe_bench()
        hl = HysteresisLoop(awg=awg, osc=osc, frequency=1000.0, amplitude=1.5, offset=0.0)
        hl.configure_awg()

        assert awg.state["waveform"][1] == "USER"
        assert awg.state["amplitude"][1] == pytest.approx(3.0)  # abs(amplitude) * 2
        assert awg.state["frequency"][1] == pytest.approx(1000.0)
        assert str(awg.state["polarity"][1]).upper() == "NORM"

    def test_hysteresis_run_experiment_lifecycle(self, tmp_path):
        bench, awg, osc = fe_bench()
        hl = HysteresisLoop(
            awg=awg,
            osc=osc,
            frequency=1000.0,
            amplitude=1.0,
            offset=0.0,
            n_cycles=2,
            area=1e-5,
            show_plots=False,
            save_plots=False,
            output_dir=str(tmp_path),
        )

        result = hl.run_experiment(save=True)
        assert isinstance(result, pd.DataFrame)
        assert hl.filename is not None
        assert Path(hl.filename).is_file()

        # Metadata in CSV must be marked processed
        meta, data = assert_piec_csv_layout(hl.filename)
        assert bool(meta.loc[0, "processed"]) is True
        assert len(hl.run_records) == 1

        assert_data_columns_match(data, list(STANDARD_HYSTERESIS_COLUMNS), exact_order=True)

    def test_hysteresis_golden_csv_regression(self, tmp_path):
        """Verify deterministic hysteresis run matches golden CSV."""
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

    def test_hysteresis_numerical_equivalence(self, tmp_path):
        """Verify numerical equivalence against golden CSV."""
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

        _, gold_data, _ = read_measurement_csv(HYSTERESIS_LOOP_GOLDEN_PATH)
        assert_numerical_data_matches_reference(hl.data, gold_data, "HysteresisLoop")

    def test_hysteresis_polarization_calculations(self, tmp_path):
        """Verify physical polarization calculation from current and area."""
        bench, awg, osc = fe_bench()
        area = 1e-5
        hl = HysteresisLoop(
            awg=awg,
            osc=osc,
            frequency=1000.0,
            amplitude=1.0,
            offset=0.0,
            n_cycles=2,
            area=area,
            show_plots=False,
            save_plots=False,
            auto_timeshift=False,
            output_dir=str(tmp_path),
        )
        hl.run_experiment(save=True)

        _, df, _ = read_measurement_csv(hl.filename)
        # Polarization starts at 0
        assert df["polarization"].iloc[0] == pytest.approx(0.0)
        # Polarization has non-zero range
        p_min = df["polarization"].min()
        p_max = df["polarization"].max()
        assert p_max > p_min
        # Applied voltage spans the requested amplitude
        assert df["applied_voltage"].max() == pytest.approx(1.0, rel=0.1)

    def test_hysteresis_auto_timeshift(self, tmp_path):
        """Verify auto_timeshift detects time alignment offset."""
        bench, awg, osc = fe_bench()

        # auto_timeshift=False retains configured time_offset
        hl_manual = HysteresisLoop(
            awg=awg,
            osc=osc,
            time_offset=1e-8,
            auto_timeshift=False,
            show_plots=False,
            save_plots=False,
            output_dir=str(tmp_path / "manual"),
        )
        hl_manual.run_experiment(save=True)
        meta_man, _, _ = read_measurement_csv(hl_manual.filename)
        assert float(meta_man["time_offset"]) == pytest.approx(1e-8)

        # auto_timeshift=True automatically determines non-zero time offset
        hl_auto = HysteresisLoop(
            awg=awg,
            osc=osc,
            time_offset=1e-8,
            auto_timeshift=True,
            show_plots=False,
            save_plots=False,
            output_dir=str(tmp_path / "auto"),
        )
        hl_auto.run_experiment(save=True)
        meta_auto, _, _ = read_measurement_csv(hl_auto.filename)
        assert float(meta_auto["time_offset"]) > 1e-8

    def test_hysteresis_plot_artifacts(self, tmp_path):
        """Verify that save_plots=True creates _PV.png, _IV.png, and _trace.png."""
        bench, awg, osc = fe_bench()

        # Run with save_plots=True
        hl_save = HysteresisLoop(
            awg=awg,
            osc=osc,
            show_plots=False,
            save_plots=True,
            output_dir=str(tmp_path),
        )
        hl_save.run_experiment(save=True)

        base_stem = Path(hl_save.filename).stem
        pv_file = Path(tmp_path) / f"{base_stem}_PV.png"
        iv_file = Path(tmp_path) / f"{base_stem}_IV.png"
        trace_file = Path(tmp_path) / f"{base_stem}_trace.png"

        assert pv_file.is_file(), f"Expected plot file {pv_file} not found"
        assert iv_file.is_file(), f"Expected plot file {iv_file} not found"
        assert trace_file.is_file(), f"Expected plot file {trace_file} not found"
        assert pv_file.stat().st_size > 0
        assert iv_file.stat().st_size > 0
        assert trace_file.stat().st_size > 0

        # Run with save_plots=False
        tmp_no_plots = tmp_path / "no_plots"
        tmp_no_plots.mkdir()
        hl_nosave = HysteresisLoop(
            awg=awg,
            osc=osc,
            show_plots=False,
            save_plots=False,
            output_dir=str(tmp_no_plots),
        )
        hl_nosave.run_experiment(save=True)

        png_files = list(tmp_no_plots.glob("*.png"))
        assert len(png_files) == 0, f"Expected no PNG plots, found {png_files}"

        # Run with save=False
        tmp_nosave_run = tmp_path / "nosave_run"
        tmp_nosave_run.mkdir()
        hl_nosave_run = HysteresisLoop(
            awg=awg,
            osc=osc,
            show_plots=False,
            save_plots=True,
            output_dir=str(tmp_nosave_run),
        )
        hl_nosave_run.run_experiment(save=False)
        assert len(list(tmp_nosave_run.glob("*"))) == 0


class TestThreePulsePundCompatibility:
    """Verify standardized ThreePulsePund behavior and regression goldens."""

    def test_pund_constructor_and_attributes(self, tmp_path):
        bench, awg, osc = fe_bench()
        pund = ThreePulsePund(
            awg=awg,
            osc=osc,
            v_div=0.1,
            reset_amp=2.0,
            reset_width=2e-3,
            reset_delay=1e-3,
            p_u_amp=1.5,
            p_u_width=1e-3,
            p_u_delay=2e-3,
            offset=0.0,
            voltage_channel="1",
            area=1.5e-5,
            time_offset=1e-8,
            show_plots=False,
            save_plots=False,
            auto_timeshift=True,
            output_dir=str(tmp_path),
        )

        assert pund.mtype == "3pulsepund"
        assert pund.measurement_schema == "three_pulse_pund"
        assert pund.column_units == STANDARD_PUND_UNITS
        assert pund.raw_column_units == {"time": "s", "voltage": "V"}
        assert pund.reset_amp == 2.0
        assert pund.reset_width == 2e-3
        assert pund.reset_delay == 1e-3
        assert pund.p_u_amp == 1.5
        assert pund.p_u_width == 1e-3
        assert pund.p_u_delay == 2e-3
        assert pund.offset == 0.0
        assert pund.voltage_channel == "1"
        assert pund.area == 1.5e-5
        assert pund.time_offset == 1e-8
        assert pund.show_plots is False
        assert pund.save_plots is False
        assert pund.auto_timeshift is True
        expected_length = 2e-3 + 1e-3 + 2 * 1e-3 + 2 * 2e-3
        assert pund.length == pytest.approx(expected_length)
        assert pund.output_dir == Path(tmp_path)
        assert pund.data is None
        assert pund.filename is None
        assert pund.notes == "2p0Vres_1p5Vpu"

        # Target contract: zero hardware I/O in __init__
        assert osc.state["armed"] is False

        # Must reject legacy save_dir
        with pytest.raises(TypeError):
            ThreePulsePund(awg=awg, osc=osc, save_dir=str(tmp_path))

    def test_pund_configure_awg(self):
        bench, awg, osc = fe_bench()
        pund = ThreePulsePund(
            awg=awg,
            osc=osc,
            reset_amp=1.0,
            p_u_amp=1.0,
            offset=0.0,
        )
        pund.configure_awg()

        assert awg.state["waveform"][1] == "USER"
        assert awg.state["amplitude"][1] == pytest.approx(2.0)  # abs(reset_amp) + abs(p_u_amp)
        assert awg.state["frequency"][1] == pytest.approx(1 / pund.length)

    def test_pund_run_experiment_lifecycle(self, tmp_path):
        bench, awg, osc = fe_bench()
        pund = ThreePulsePund(
            awg=awg,
            osc=osc,
            show_plots=False,
            save_plots=False,
            output_dir=str(tmp_path),
        )

        result = pund.run_experiment(save=True)
        assert isinstance(result, pd.DataFrame)
        assert pund.filename is not None
        assert Path(pund.filename).is_file()

        # Metadata in CSV must be marked processed
        meta, data = assert_piec_csv_layout(pund.filename)
        assert bool(meta.loc[0, "processed"]) is True
        assert len(pund.run_records) == 1

        assert_data_columns_match(data, list(STANDARD_PUND_COLUMNS), exact_order=True)

    def test_pund_golden_csv_regression(self, tmp_path):
        """Verify deterministic PUND run matches golden CSV."""
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

    def test_pund_numerical_equivalence(self, tmp_path):
        """Verify numerical equivalence against golden CSV."""
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

        _, gold_data, _ = read_measurement_csv(THREE_PULSE_PUND_GOLDEN_PATH)
        assert_numerical_data_matches_reference(pund.data, gold_data, "ThreePulsePund")

    def test_pund_polarization_calculations(self, tmp_path):
        """Verify PUND polarization calculations and array zeroing."""
        bench, awg, osc = fe_bench()
        pund = ThreePulsePund(
            awg=awg,
            osc=osc,
            show_plots=False,
            save_plots=False,
            output_dir=str(tmp_path),
        )
        pund.run_experiment(save=True)

        _, df, _ = read_measurement_csv(pund.filename)
        # polarization_p_hat and polarization_p_star initial values must be zeroed
        assert df["polarization_p_hat"].iloc[0] == pytest.approx(0.0)
        assert df["polarization_p_star"].iloc[0] == pytest.approx(0.0)
        assert df["polarization_p_hat_r"].iloc[0] == pytest.approx(0.0)
        assert df["polarization_p_star_r"].iloc[0] == pytest.approx(0.0)
        assert df["delta_polarization"].iloc[0] == pytest.approx(0.0)

        # delta_polarization must have a non-zero maximum representing switched polarization
        dp_max = df["delta_polarization"].max()
        assert dp_max > 0.0

    def test_pund_auto_timeshift(self, tmp_path):
        """Verify auto_timeshift detects PUND pulse onset."""
        bench, awg, osc = fe_bench()

        pund_auto = ThreePulsePund(
            awg=awg,
            osc=osc,
            time_offset=1e-8,
            auto_timeshift=True,
            show_plots=False,
            save_plots=False,
            output_dir=str(tmp_path / "auto"),
        )
        pund_auto.run_experiment(save=True)
        meta_auto, _, _ = read_measurement_csv(pund_auto.filename)
        assert float(meta_auto["time_offset"]) > 1e-8

        pund_manual = ThreePulsePund(
            awg=awg,
            osc=osc,
            time_offset=1e-8,
            auto_timeshift=False,
            show_plots=False,
            save_plots=False,
            output_dir=str(tmp_path / "manual"),
        )
        pund_manual.run_experiment(save=True)
        meta_man, _, _ = read_measurement_csv(pund_manual.filename)
        assert float(meta_man["time_offset"]) == pytest.approx(1e-8)

    def test_pund_plot_artifacts(self, tmp_path):
        """Verify that save_plots=True creates _dPvst.png and _trace.png."""
        bench, awg, osc = fe_bench()

        # Run with save_plots=True
        pund_save = ThreePulsePund(
            awg=awg,
            osc=osc,
            show_plots=False,
            save_plots=True,
            output_dir=str(tmp_path),
        )
        pund_save.run_experiment(save=True)

        base_stem = Path(pund_save.filename).stem
        dp_file = Path(tmp_path) / f"{base_stem}_dPvst.png"
        trace_file = Path(tmp_path) / f"{base_stem}_trace.png"

        assert dp_file.is_file(), f"Expected plot file {dp_file} not found"
        assert trace_file.is_file(), f"Expected plot file {trace_file} not found"
        assert dp_file.stat().st_size > 0
        assert trace_file.stat().st_size > 0

        # Run with save_plots=False
        tmp_no_plots = tmp_path / "no_plots"
        tmp_no_plots.mkdir()
        pund_nosave = ThreePulsePund(
            awg=awg,
            osc=osc,
            show_plots=False,
            save_plots=False,
            output_dir=str(tmp_no_plots),
        )
        pund_nosave.run_experiment(save=True)

        png_files = list(tmp_no_plots.glob("*.png"))
        assert len(png_files) == 0, f"Expected no PNG plots, found {png_files}"

        # Run with save=False
        tmp_nosave_run = tmp_path / "nosave_run"
        tmp_nosave_run.mkdir()
        pund_nosave_run = ThreePulsePund(
            awg=awg,
            osc=osc,
            show_plots=False,
            save_plots=True,
            output_dir=str(tmp_nosave_run),
        )
        pund_nosave_run.run_experiment(save=False)
        assert len(list(tmp_nosave_run.glob("*"))) == 0
