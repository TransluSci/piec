"""Numerical and state regressions for the checkpoint 27 review."""
import math
import numpy as np
import pytest

from piec.simulation.contracts import (
    CapacitiveLoad, DeterministicTimebase, DiodeLoad, LoadResponse, ResistorLoad,
)
from piec.simulation.hysteretic_magnetic_material import HystereticMagneticMaterial
from piec.simulation.magnetic_material import MagneticSample
from piec.simulation.fe_material import Ferroelectric
from piec.drivers.lockin.virtual_lockin import VirtualLockin


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
