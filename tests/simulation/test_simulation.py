"""
Consolidated Simulation and Virtual Bench Tests.

Consolidates:
- Simulation contracts and role definitions (test_simulation_contracts.py)
- Numerical physics regressions (test_simulation_review.py)
- VirtualBench numerical routing and replay (test_virtual_bench.py)
- Consumer plant fixtures and isolation (test_virtual_consumer_plants.py)
- AMR bench fixture isolation and reset (test_amr_bench_fixture.py)
- FE bench fixture isolation and replay (test_fe_bench_fixture.py)

Validates:
- Canonical physical units across all simulation roles.
- Two-terminal electrical load contracts (ResistorLoad, DiodeLoad, CapacitiveLoad).
- Field-responsive and angle-dependent materials (HystereticMagneticMaterial, MagneticSample, Ferroelectric).
- Deterministic timebases and independent RNG streams.
- VirtualBench dynamic wiring, multi-instrument isolation, and atomic reset.
- Interactive consumer plant connection (connect_fe_plant, connect_amr_plant).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import math
from threading import Barrier
from types import MappingProxyType
from typing import Mapping
from unittest.mock import Mock

import numpy as np
import pytest

from piec.analysis.field_calibration import FieldCalibration
from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.lockin.virtual_lockin import VirtualLockin
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.measurement.iv_sweep import IVSweep
from piec.measurement.moke import MokeMeasurement
from piec.simulation import (
    AngleDependentResistanceContract,
    CalibratorFieldHook,
    CapacitiveLoad,
    DeterministicTimebase,
    Dielectric,
    DiodeLoad,
    DmmVoltageReaderHook,
    ElectricalLoadContract,
    Ferroelectric,
    FieldResponsiveMaterialContract,
    HystereticMagneticMaterial,
    LoadMode,
    LoadResponse,
    LockinTransportHook,
    MagneticSample,
    Material,
    Resistor,
    ResistorLoad,
    ScopeChannelHook,
    SimulationRole,
    StepperAngleHook,
    WaveformResponsiveMaterialContract,
)
from piec.simulation.setups import (
    connect_amr_plant,
    connect_fe_plant,
    example_fe_parameters,
)


# ==============================================================================
# Part 1: Simulation Contracts and Role Definitions
# ==============================================================================
class TestDeclaredUnits:
    """Verify that every simulation role declares immutable canonical physical units."""

    def test_electrical_load_declared_units(self):
        load = ResistorLoad(1000.0)
        units = load.declared_units
        assert isinstance(units, (dict, MappingProxyType))
        assert units["voltage"] == "V"
        assert units["current"] == "A"
        assert units["resistance"] == "Ohm"
        assert units["time"] == "s"

        # Ensure units mapping is immutable
        with pytest.raises(TypeError):
            units["voltage"] = "mV"  # type: ignore

    def test_diode_and_capacitive_load_declared_units(self):
        diode = DiodeLoad()
        cap = CapacitiveLoad()
        for dev in (diode, cap):
            assert dev.declared_units["voltage"] == "V"
            assert dev.declared_units["current"] == "A"
            assert dev.declared_units["resistance"] == "Ohm"
            assert dev.declared_units["time"] == "s"

    def test_field_responsive_material_declared_units(self):
        mat = HystereticMagneticMaterial()
        units = mat.declared_units
        assert units["field"] == "Oe"
        assert units["magnetization"] == "dimensionless"
        assert units["time"] == "s"

    def test_angle_dependent_resistance_declared_units(self):
        sample = MagneticSample()
        units = sample.declared_units
        assert units["angle"] == "deg"
        assert units["field"] == "Oe"
        assert units["resistance"] == "Ohm"
        assert units["x"] == "V"
        assert units["y"] == "V"
        assert units["time"] == "s"

    def test_waveform_responsive_material_declared_units(self):
        material_dict = {
            "ferroelectric": {
                "a0": 5.362e5, "b": -1.287e9, "c": 5.0e9, "T0": 673.0,
                "Q12": -0.046, "s11": 14.1e-12, "s12": -4.56e-12,
                "lattice_a": 0.395e-9, "film_thickness": 20e-9,
                "epsilon_r": 50, "leakage_resistance": 10e12,
            },
            "substrate": {"lattice_a": 0.395e-9},
            "electrode": {"screening_lambda": 0.05e-9, "permittivity_e": 1e6, "area": 1.0e-10},
        }
        fe = Ferroelectric(material_dict)
        units = fe.declared_units
        assert units["voltage"] == "V"
        assert units["time"] == "s"
        assert units["current"] == "A"
        assert units["polarization"] == "C/m^2"


# ============================================================================
# 2. Deterministic Timebase Tests
# ============================================================================

class TestDeterministicTimebase:
    """Verify timebase monotonic advancement, explicit setting, reset, and validation."""

    def test_timebase_lifecycle(self):
        tb = DeterministicTimebase(start_time=1.0)
        assert tb.current_time == 1.0

        t1 = tb.advance(0.5)
        assert t1 == 1.5
        assert tb.current_time == 1.5

        tb.advance(2.0)
        assert tb.current_time == 3.5

        tb.set_time(10.0)
        assert tb.current_time == 10.0

        tb.reset(start_time=0.0)
        assert tb.current_time == 0.0

    def test_timebase_validation(self):
        tb = DeterministicTimebase()
        with pytest.raises(ValueError, match="finite non-negative"):
            tb.advance(-0.1)
        with pytest.raises(ValueError, match="finite non-negative"):
            tb.advance(float("nan"))
        with pytest.raises(ValueError, match="finite non-negative"):
            tb.set_time(-1.0)
        with pytest.raises(ValueError, match="finite non-negative"):
            DeterministicTimebase(start_time=-5.0)


# ============================================================================
# 3. Deterministic RNG and Reset Isolation Tests
# ============================================================================

class TestDeterministicRngAndResetIsolation:
    """Verify reproducibility with seeds and independence between instances."""

    def test_seeded_resistor_noise_is_deterministic(self):
        r1 = ResistorLoad(resistance=1000.0, noise_std=1e-3, seed=42)
        r2 = ResistorLoad(resistance=1000.0, noise_std=1e-3, seed=42)

        # Both instances must produce bit-identical responses across a sequence of calls
        responses1 = [r1.source_voltage(1.0).current for _ in range(20)]
        responses2 = [r2.source_voltage(1.0).current for _ in range(20)]
        assert responses1 == responses2

    def test_reset_reproduces_exact_sequence(self):
        r = ResistorLoad(resistance=1000.0, noise_std=1e-3, seed=123)
        first_pass = [r.source_voltage(2.0).current for _ in range(15)]

        # Resetting with same seed reproduces the exact sequence
        r.reset(seed=123)
        second_pass = [r.source_voltage(2.0).current for _ in range(15)]
        assert first_pass == second_pass

    def test_different_seeds_produce_distinct_sequences(self):
        r1 = ResistorLoad(resistance=1000.0, noise_std=1e-3, seed=1)
        r2 = ResistorLoad(resistance=1000.0, noise_std=1e-3, seed=2)

        resp1 = [r1.source_voltage(1.0).current for _ in range(10)]
        resp2 = [r2.source_voltage(1.0).current for _ in range(10)]
        assert resp1 != resp2

    def test_instances_do_not_cross_talk(self):
        r_isolated_a = ResistorLoad(resistance=500.0, seed=10)
        r_isolated_b = ResistorLoad(resistance=1000.0, seed=20)

        # Modifying state or temperature on A must not alter B
        r_isolated_a.set_temperature(400.0)
        assert r_isolated_a._current_temp == 400.0
        assert r_isolated_b._current_temp == 300.0

        r_isolated_a.reset()
        assert r_isolated_a._current_temp == 300.0
        assert r_isolated_b.effective_resistance == 1000.0

    def test_magnetic_sample_deterministic_noise_and_reset(self):
        s1 = MagneticSample(seed=99)
        s2 = MagneticSample(seed=99)

        r_seq1 = [s1.get_resistance(angle=deg) for deg in range(0, 180, 10)]
        r_seq2 = [s2.get_resistance(angle=deg) for deg in range(0, 180, 10)]
        assert r_seq1 == r_seq2

        # Resetting restores initial angle, field, and RNG sequence
        s1.current_angle = 45.0
        s1.current_field = 100.0
        s1.reset(seed=99)
        assert s1.current_angle == 0.0
        assert s1.current_field == 0.0
        r_seq1_after_reset = [s1.get_resistance(angle=deg) for deg in range(0, 180, 10)]
        assert r_seq1 == r_seq1_after_reset


# ============================================================================
# 4. ResistorLoad Contract Tests (Voltage and Current Modes)
# ============================================================================

class TestResistorLoad:
    """Verify linear resistor behavior in voltage-source and current-source modes."""

    def test_voltage_source_mode_ohms_law(self):
        resistor = ResistorLoad(resistance=500.0, noise_std=0.0)
        resp = resistor.source_voltage(voltage=5.0, compliance_current=0.1)

        assert resp.voltage == 5.0
        assert resp.current == pytest.approx(0.010, rel=1e-9)  # 5 V / 500 Ohm = 0.01 A
        assert not resp.compliance_tripped
        assert resp.resistance == pytest.approx(500.0)

    def test_voltage_source_mode_current_compliance(self):
        resistor = ResistorLoad(resistance=100.0, noise_std=0.0)
        # 10 V into 100 Ohm would be 0.1 A, but compliance is 0.05 A
        resp = resistor.source_voltage(voltage=10.0, compliance_current=0.05)

        assert resp.compliance_tripped
        assert resp.current == pytest.approx(0.05)
        # Actual voltage across the clamped resistor drops to I_comp * R = 5.0 V
        assert resp.voltage == pytest.approx(5.0)

    def test_voltage_source_negative_voltage(self):
        resistor = ResistorLoad(resistance=200.0, noise_std=0.0)
        resp = resistor.source_voltage(voltage=-4.0, compliance_current=0.1)

        assert resp.voltage == -4.0
        assert resp.current == pytest.approx(-0.02)
        assert not resp.compliance_tripped

    def test_current_source_mode_ohms_law(self):
        resistor = ResistorLoad(resistance=1000.0, noise_std=0.0)
        resp = resistor.source_current(current=0.005, compliance_voltage=20.0)

        assert resp.current == 0.005
        assert resp.voltage == pytest.approx(5.0)  # 5 mA * 1000 Ohm = 5.0 V
        assert not resp.compliance_tripped
        assert resp.resistance == pytest.approx(1000.0)

    def test_current_source_mode_voltage_compliance(self):
        resistor = ResistorLoad(resistance=10000.0, noise_std=0.0)
        # 10 mA into 10 kOhm would be 100 V, but compliance is 15 V
        resp = resistor.source_current(current=0.010, compliance_voltage=15.0)

        assert resp.compliance_tripped
        assert resp.voltage == pytest.approx(15.0)
        # Current delivered drops to V_comp / R = 1.5 mA
        assert resp.current == pytest.approx(0.0015)

    def test_temperature_coefficient(self):
        # 1000 Ohm at 300 K with temp_coeff = 0.004 / K (typical copper / metal)
        resistor = ResistorLoad(resistance=1000.0, temp_coeff=0.004, nominal_temp=300.0)
        assert resistor.effective_resistance == 1000.0

        # Heat to 350 K (+50 K): R = 1000 * (1 + 0.004 * 50) = 1200 Ohm
        resistor.set_temperature(350.0)
        assert resistor.effective_resistance == pytest.approx(1200.0)

        resp = resistor.source_voltage(12.0)
        assert resp.current == pytest.approx(12.0 / 1200.0)

    def test_input_validation(self):
        resistor = ResistorLoad(100.0)
        with pytest.raises(ValueError, match="stimulus must be finite"):
            resistor.source_voltage(float("nan"))
        with pytest.raises(ValueError, match="compliance must be a finite positive number"):
            resistor.source_voltage(1.0, compliance_current=-0.01)
        with pytest.raises(ValueError, match="compliance must be a finite positive number"):
            resistor.source_voltage(1.0, compliance_current=0.0)
        with pytest.raises(ValueError, match="compliance must be a finite positive number"):
            resistor.source_current(0.01, compliance_voltage=-5.0)


# ============================================================================
# 5. DiodeLoad Contract Tests
# ============================================================================

class TestDiodeLoad:
    """Verify non-linear Shockley diode model in voltage-source and current-source modes."""

    def test_diode_forward_and_reverse_voltage_source(self):
        diode = DiodeLoad(is_sat=1e-12, n=1.0, temp_k=300.0, noise_std=0.0)

        # Reverse bias: current saturates near -I_s = -1 pA
        resp_rev = diode.source_voltage(-1.0)
        assert resp_rev.current == pytest.approx(-1e-12, rel=1e-2)
        assert not resp_rev.compliance_tripped

        # Forward bias: exponential current rise
        resp_fwd1 = diode.source_voltage(0.5)
        resp_fwd2 = diode.source_voltage(0.6)
        assert resp_fwd2.current > resp_fwd1.current > 0.0

    def test_diode_voltage_source_compliance(self):
        diode = DiodeLoad(is_sat=1e-12, n=1.0, noise_std=0.0)
        # Forward bias with 1 mA current compliance
        resp = diode.source_voltage(1.0, compliance_current=1e-3)
        assert resp.compliance_tripped
        assert resp.current == pytest.approx(1e-3)
        # Clamped voltage should be around 0.5 - 0.6 V
        assert 0.4 < resp.voltage < 0.7

    def test_diode_current_source_mode(self):
        diode = DiodeLoad(is_sat=1e-12, n=1.0, noise_std=0.0)
        # Sourcing 1 mA forward current
        resp = diode.source_current(1e-3, compliance_voltage=10.0)
        assert not resp.compliance_tripped
        assert resp.current == 1e-3
        assert 0.4 < resp.voltage < 0.7

    def test_diode_current_source_voltage_compliance(self):
        diode = DiodeLoad(is_sat=1e-12, n=1.0, noise_std=0.0)
        # Clamping at low voltage compliance (0.2 V)
        resp = diode.source_current(10e-3, compliance_voltage=0.2)
        assert resp.compliance_tripped
        assert resp.voltage == pytest.approx(0.2)


# ============================================================================
# 6. CapacitiveLoad Contract Tests
# ============================================================================

class TestCapacitiveLoad:
    """Verify stateful capacitive load tracking charge and time-dependent dynamics."""

    def test_capacitive_load_charging_under_current(self):
        # 1 uF capacitor, initially 0 V
        cap = CapacitiveLoad(capacitance=1e-6, leakage_resistance=1e9)
        assert cap.stored_charge == 0.0

        # Apply 1 mA current for 1 ms -> dV = I * dt / C = 1e-3 * 1e-3 / 1e-6 = 1.0 V
        resp1 = cap.source_current(1e-3, compliance_voltage=50.0, time=0.001)
        assert resp1.voltage == pytest.approx(1.0, rel=1e-4)
        assert cap.stored_charge == pytest.approx(1e-6, rel=1e-4)

        # Apply 1 mA for another 1 ms (time = 0.002 s) -> V reaches 2.0 V
        resp2 = cap.source_current(1e-3, compliance_voltage=50.0, time=0.002)
        assert resp2.voltage == pytest.approx(2.0, rel=1e-4)

    def test_capacitive_load_reset_clears_charge(self):
        cap = CapacitiveLoad(capacitance=1e-6)
        cap.source_current(1e-3, time=0.005)
        assert cap.stored_charge > 0.0

        cap.reset()
        assert cap.stored_charge == 0.0
        assert cap._voltage == 0.0


# ============================================================================
# 7. FieldResponsiveMaterialContract Tests
# ============================================================================

class TestFieldResponsiveMaterialContract:
    """Verify HystereticMagneticMaterial adherence to FieldResponsiveMaterialContract."""

    def test_hysteretic_magnetic_material_contract(self):
        mat = HystereticMagneticMaterial(coercive_field=50.0, switching_width=10.0, domains=101)
        assert isinstance(mat, FieldResponsiveMaterialContract)
        assert isinstance(mat, SimulationRole)

        # Initial state: negative polarity (-1.0)
        assert mat.magnetization == -1.0
        assert mat.current_field == 0.0

        # Positive field below threshold does not switch
        m1 = mat.apply_field(30.0)
        assert m1 == -1.0

        # Sweep above coercive field switches magnetization to +1.0
        m2 = mat.apply_field(70.0)
        assert m2 == 1.0
        assert mat.current_field == 70.0

        # Returning to 0 Oe preserves remanence (+1.0)
        m3 = mat.apply_field(0.0)
        assert m3 == 1.0

        # Negative field below -Hc switches back to -1.0
        m4 = mat.apply_field(-70.0)
        assert m4 == -1.0

    def test_hysteretic_magnetic_material_response_sequence(self):
        mat = HystereticMagneticMaterial(coercive_field=50.0, switching_width=5.0)
        fields = np.array([-100.0, 0.0, 100.0, 0.0, -100.0])
        response = mat.response(fields)

        assert len(response) == 5
        assert response[0] == -1.0
        assert response[2] == 1.0
        assert response[3] == 1.0  # remanence
        assert response[4] == -1.0

    def test_hysteretic_magnetic_material_reset(self):
        mat = HystereticMagneticMaterial(coercive_field=50.0)
        mat.apply_field(100.0)
        assert mat.magnetization == 1.0

        mat.reset(polarity=-1)
        assert mat.magnetization == -1.0
        assert mat.current_field == 0.0


# ============================================================================
# 8. AngleDependentResistanceContract Tests
# ============================================================================

class TestAngleDependentResistanceContract:
    """Verify MagneticSample adherence to AngleDependentResistanceContract."""

    def test_magnetic_sample_contract(self):
        sample = MagneticSample(r_base=100.0, amr_ratio=0.05, seed=42)
        assert isinstance(sample, AngleDependentResistanceContract)
        assert isinstance(sample, SimulationRole)

        assert sample.current_angle == 0.0
        assert sample.current_field == 0.0

        # Angle 0 deg: parallel resistance R_par = 100 * 1.05 = 105 Ohm
        r_0 = sample.get_resistance(angle=0.0)
        assert r_0 == pytest.approx(105.0, abs=0.1)

        # Angle 90 deg: perpendicular resistance R_perp = 100 Ohm
        r_90 = sample.get_resistance(angle=90.0)
        assert r_90 == pytest.approx(100.0, abs=0.1)

        # Angle 180 deg: returns to parallel R_par = 105 Ohm
        r_180 = sample.get_resistance(angle=180.0)
        assert r_180 == pytest.approx(105.0, abs=0.1)

    def test_voltage_response_uses_explicit_current_and_resistive_phase(self):
        sample = MagneticSample(r_base=100.0, amr_ratio=0.02, seed=7)
        resistance = sample.get_resistance(angle=0)
        sample.reset()
        x, y = sample.get_voltage_response(excitation_current=0.002, angle=0)
        assert x == pytest.approx(resistance * 0.002)
        assert y == 0.0
        with pytest.raises(TypeError):
            sample.get_voltage_response()


# ============================================================================
# 9. WaveformResponsiveMaterialContract Tests
# ============================================================================

class TestWaveformResponsiveMaterialContract:
    """Verify Ferroelectric adherence to WaveformResponsiveMaterialContract."""

    def test_ferroelectric_material_contract(self):
        material_dict = {
            "ferroelectric": {
                "a0": 5.362e5, "b": -1.287e9, "c": 5.0e9, "T0": 673.0,
                "Q12": -0.046, "s11": 14.1e-12, "s12": -4.56e-12,
                "lattice_a": 0.395e-9, "film_thickness": 20e-9,
                "epsilon_r": 50, "leakage_resistance": 10e12,
            },
            "substrate": {"lattice_a": 0.395e-9},
            "electrode": {"screening_lambda": 0.05e-9, "permittivity_e": 1e6, "area": 1.0e-10},
        }
        fe = Ferroelectric(material_dict)
        assert isinstance(fe, WaveformResponsiveMaterialContract)
        assert isinstance(fe, SimulationRole)
        assert isinstance(fe, Material)

        # Apply a short test waveform
        t = np.linspace(0, 1e-6, 50)
        v = 2.0 * np.sin(2 * np.pi * 1e6 * t)
        fe.apply_waveform(v, t)

        v_resp, t_resp = fe.get_voltage_response()
        assert len(v_resp) == len(t)
        assert len(t_resp) == len(t)

        # Reset clears response
        fe.reset()
        assert fe.output_voltage is None
        assert fe.t is None


# ============================================================================
# 10. Virtual Hook Type Checking
# ============================================================================

class TestVirtualHooks:
    """Verify typing and callable interfaces for virtual instrument hooks."""

    def test_dmm_hook_callable(self):
        def reader() -> float:
            return 1.234

        hook: DmmVoltageReaderHook = reader
        assert hook() == 1.234

    def test_lockin_hook_callable(self):
        def lockin_reader() -> tuple[float, float]:
            return (0.005, 0.0005)

        hook: LockinTransportHook = lockin_reader
        x, y = hook()
        assert x == 0.005
        assert y == 0.0005

# ==============================================================================
# Part 2: Physics Regressions and Terminal Equations
# ==============================================================================
@pytest.mark.parametrize("series", [0, 10, 1000])
@pytest.mark.parametrize("voltage", [-1, 0, 0.7, 5, 100])
def test_diode_matches_terminal_equation(series, voltage):
    diode = DiodeLoad(r_series=series)
    response = diode.source_voltage(voltage, compliance_current=0.1)
    expected = 1e-12 * math.expm1((response.voltage - response.current * series) / diode.thermal_voltage)
    assert response.current == pytest.approx(expected, rel=1e-8, abs=1e-18)
    assert abs(response.current) <= 0.1
    assert abs(response.voltage) <= abs(voltage) + 1e-12


@pytest.mark.parametrize("limit", [5, 210])
def test_reverse_diode_current_hits_actual_voltage_limit(limit):
    response = DiodeLoad().source_current(-0.001, compliance_voltage=limit)
    assert response.compliance_tripped
    assert response.voltage == -limit
    assert response.current == pytest.approx(-1e-12, abs=1e-18)


@pytest.mark.parametrize("mode", ["voltage", "current"])
@pytest.mark.parametrize("sign", [-1, 1])
def test_capacitor_compliance_conserves_charge_and_leakage(mode, sign):
    cap = CapacitiveLoad(capacitance=1, leakage_resistance=1)
    if mode == "voltage":
        response = cap.source_voltage(sign * 100, compliance_current=1, time=10)
        assert abs(response.current) <= 1
    else:
        response = cap.source_current(sign * 100, compliance_voltage=1, time=10)
        assert abs(response.voltage) <= 1
    assert response.compliance_tripped
    assert response.current * 10 == pytest.approx(cap.stored_charge + response.voltage * 10)
    assert math.copysign(1, response.voltage) == sign
    assert cap.timebase.current_time == 10


def test_capacitor_large_timestep_discharges_without_sign_flip():
    cap = CapacitiveLoad(capacitance=1, leakage_resistance=1, initial_voltage=1)
    response = cap.source_current(0, time=100)
    assert 0 < response.voltage < 1


@pytest.mark.parametrize("factory", [ResistorLoad, DiodeLoad, CapacitiveLoad])
def test_load_time_rejects_reversal_and_nonfinite(factory):
    load = factory()
    load.source_voltage(0.1, time=1)
    for t in [-1, 0.5, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            load.source_voltage(0.1, time=t)
        assert load.timebase.current_time == 1


def test_capacitor_does_not_invent_elapsed_time():
    cap = CapacitiveLoad()
    with pytest.raises(ValueError, match="strictly later"):
        cap.source_current(0.001)
    assert cap.stored_charge == 0


@pytest.mark.parametrize("factory", [ResistorLoad, DiodeLoad, CapacitiveLoad, MagneticSample, HystereticMagneticMaterial])
def test_reset_restores_initial_time_and_unseeded_rng(factory):
    role = factory(start_time=4)
    assert role.timebase.current_time == 4
    first = role.rng.normal(size=5)
    role.timebase.advance(1)
    role.reset()
    assert role.timebase.current_time == 4
    np.testing.assert_array_equal(role.rng.normal(size=5), first)


def test_clock_overflow_rejected_without_state_change():
    clock = DeterministicTimebase(1e308)
    with pytest.raises(ValueError):
        clock.advance(1e308)
    assert clock.current_time == 1e308


def test_response_state_is_detached_and_recursively_immutable():
    state = {"nested": {"values": [1, 2]}}
    response = LoadResponse(1, 1, False, state=state)
    state["nested"]["values"][0] = 3
    assert response.state["nested"]["values"] == (1, 2)
    with pytest.raises(TypeError):
        response.state["nested"]["other"] = 4


def test_invalid_field_history_does_not_partially_switch_material():
    role = HystereticMagneticMaterial()
    with pytest.raises(ValueError):
        role.response([100, -100], times=[1, float("nan")])
    assert role.magnetization == -1
    assert role.timebase.current_time == 0


def test_virtual_lockin_forwards_declared_current_and_both_channels():
    class Sample:
        def get_voltage_response(self, *, excitation_current):
            assert excitation_current == 0.002
            return (0.2, -0.01)
    lockin = VirtualLockin(excitation_current=0.002)
    lockin.mag_sample = Sample()
    assert lockin.quick_read() == (0.2, -0.01)


@pytest.mark.parametrize("times", [[0, 0], [1, 0], [0, float("nan")], [0, 1, 3]])
def test_fe_rejects_invalid_time_grid_before_computing(times):
    sample = Ferroelectric({})
    with pytest.raises(ValueError):
        sample.apply_waveform(np.zeros(len(times)), times)
    assert sample.t is None
    assert sample.timebase.current_time == 0


def test_diode_noise_units_are_independent_and_resettable():
    diode = DiodeLoad(noise_std=1, voltage_noise_std=0, seed=7)
    assert diode.source_current(0.001).voltage == diode.source_current(0.001).voltage
    diode = DiodeLoad(voltage_noise_std=0.001, seed=7)
    first = diode.source_current(0.001).voltage
    diode.reset()
    assert diode.source_current(0.001).voltage == first

# ==============================================================================
# Part 3: Direct Load Evaluation and VirtualSourcemeter Compliance
# ==============================================================================

def test_sourcemeter_with_resistor_load_both_modes():
    sm = VirtualSourcemeter()
    load = ResistorLoad(resistance=100.0)
    sm.load_hook = load
    sm.configure_voltage_source(voltage=10.0, current_compliance=0.02)
    sm.output(on=True)
    assert sm.get_voltage() == pytest.approx(2.0)
    assert sm.get_current() == pytest.approx(0.02)
    assert sm.compliance_tripped

    sm.configure_current_source(current=0.1, voltage_compliance=3.0)
    assert sm.get_voltage() == pytest.approx(3.0)
    assert sm.get_current() == pytest.approx(0.03)
    assert sm.compliance_tripped
    sm.output(on=False)







# ==============================================================================
# Part 4: Virtual Consumer Plants (FE & AMR)
# ==============================================================================
def test_fe_consumer_pairs_ignore_shared_fallback_and_are_isolated(monkeypatch):
    monkeypatch.setattr(VirtualInstrument, '_shared_fe_sample', object())
    a, sa = VirtualAwg(simulation_points=50), VirtualScope()
    b, sb = VirtualAwg(simulation_points=50), VirtualScope()
    ma, mb = connect_fe_plant(a, sa), connect_fe_plant(b, sb)
    a.output_trigger()
    first = sa.get_data()
    assert mb.output_voltage is None
    b.output_trigger()
    np.testing.assert_array_equal(sb.get_data(), first)
    ma.reset()
    np.testing.assert_array_equal(sb.get_data(), first)


def test_amr_consumer_preserves_front_panel_and_uses_explicit_current(monkeypatch):
    monkeypatch.setattr(VirtualInstrument, '_shared_mag_sample', object())
    cal, dmm, stepper, lockin = VirtualCalibrator(), VirtualDMM(), VirtualStepper(), VirtualLockin()
    lockin.configure_gain_filters(sensitivity='100uv/pa')
    before = lockin.get_state()
    model = connect_amr_plant(cal, dmm, stepper, lockin, seed=42)
    assert lockin.get_state() == before
    cal.set_output(.01)
    cal.output(True)
    stepper.step(50, 1)
    assert model.current_angle == 90.
    assert dmm.get_voltage() == .01
    x, y = lockin.get_X_Y()
    assert x == pytest.approx(100e-6, abs=1e-7)
    assert y == 0.
    lockin.excitation_current = 0.
    assert lockin.get_X_Y() == (0., 0.)
    cal.output(False)
    assert dmm.get_voltage() == 0.


def test_example_parameters_are_independent_and_not_shared():
    first = example_fe_parameters()
    first['ferroelectric']['a0'] = -1
    assert example_fe_parameters()['ferroelectric']['a0'] > 0


def test_consumer_plant_rejects_physical_objects_before_wiring():
    with pytest.raises(TypeError):
        connect_fe_plant(object(), object())
    with pytest.raises(TypeError):
        connect_amr_plant(object(), object(), object(), object())


