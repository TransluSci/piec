"""Shared sample initialization and dictionary-based model configuration."""

import numpy as np
import pytest

from piec.simulation.fe_material import Material, Resistor, Dielectric, Ferroelectric
from piec.simulation.magnetic_material import MagneticSample
from piec.simulation.sample import Sample


@pytest.mark.parametrize('sample_class, default_name', [
    (Sample, None),
    (Material, 'pass_through'),
    (Resistor, 'resistor'),
    (Dielectric, 'dielectric'),
    (Ferroelectric, None),
    (MagneticSample, 'virtual_magnetic_sample'),
])
def test_all_samples_share_name_and_parameter_initialization(sample_class, default_name):
    parameters = {}
    sample = sample_class(parameter_dict=parameters)
    assert isinstance(sample, Sample)
    assert sample.name == default_name
    assert sample.parameter_dict is parameters
    assert sample_class(parameter_dict={}, name='custom').name == 'custom'


@pytest.mark.parametrize('sample_class', [Sample, Material, Resistor, Dielectric, MagneticSample])
def test_default_parameter_dictionaries_are_independent(sample_class):
    first = sample_class()
    second = sample_class()
    first.parameter_dict['extra'] = 1
    assert 'extra' not in second.parameter_dict


def test_resistor_dictionary_controls_response_and_preserves_scalar_api():
    voltage = np.array([0.0, 1.0, 2.0])
    time = np.array([0.0, 0.5, 1.0])
    resistor = Resistor(resistance=1000, parameter_dict={'resistance': 2000})
    current, response_time = resistor.voltage_response(voltage, time)
    np.testing.assert_allclose(current, [0.0, 0.0005, 0.001])
    assert response_time is time
    np.testing.assert_array_equal(resistor.current_response(current, time)[0], voltage)
    np.testing.assert_array_equal(Resistor(2000).voltage_response(voltage, time)[0], current)
    assert Resistor().resistance == 1000
    resistor.resistance = 1000
    np.testing.assert_allclose(resistor.voltage_response(voltage, time)[0], [0, 0.001, 0.002])


def test_dielectric_configuration_preserves_pass_through_response():
    sample = Dielectric(parameter_dict={'permittivity': 1e-10})
    assert sample.permittivity == 1e-10
    assert Dielectric(1e-10).permittivity == sample.permittivity
    assert Dielectric().permittivity == 8.85e-12
    voltage, time = np.array([1.0, 2.0]), np.array([0.0, 1.0])
    for response in (sample.voltage_response, sample.current_response):
        values, response_time = response(voltage, time)
        assert values is voltage
        assert response_time is time


def test_magnetic_dictionary_controls_resistance(monkeypatch):
    monkeypatch.setattr(np.random, 'normal', lambda *args: 0.0)
    parameters = {'r_base': 200.0, 'amr_ratio': 0.1, 'phi_offset': 30.0}
    sample = MagneticSample(parameter_dict=parameters)
    legacy = MagneticSample(200.0, 0.1, 30.0)
    assert sample.current_angle == sample.current_field == 0.0
    assert sample.get_resistance(angle=30) == pytest.approx(220.0)
    assert sample.get_resistance(angle=120) == pytest.approx(200.0)
    assert sample.get_resistance(angle=60) == legacy.get_resistance(angle=60)
    assert sample.get_voltage_response() == legacy.get_voltage_response()
    assert MagneticSample().get_resistance(angle=0) == pytest.approx(102.0)


def test_magnetic_partial_dictionary_retains_scalar_defaults():
    sample = MagneticSample(r_base=200, parameter_dict={'amr_ratio': 0.1})
    assert sample.parameter_dict == {'r_base': 200, 'amr_ratio': 0.1, 'phi_offset': 0.0}
    assert (sample.r_base, sample.amr_ratio, sample.phi_offset) == (200, 0.1, 0.0)


def test_ferroelectric_reads_shared_parameter_dictionary():
    parameters = {
        'ferroelectric': {
            'a0': 5.362e5, 'b': -1.287e9, 'c': 5e9, 'T0': 673,
            'Q12': -0.046, 's11': 14.1e-12, 's12': -4.56e-12,
            'lattice_a': 0.395e-9, 'film_thickness': 20e-9,
        },
        'substrate': {'lattice_a': 0.395e-9},
        'electrode': {'screening_lambda': 0.05e-9, 'permittivity_e': 1e6},
    }
    sample = Ferroelectric(parameters, 310, name='capacitor')
    assert sample.temperature == 310
    assert sample.output_voltage is None
    assert sample.t is None
    before = sample._compute_renormalized_coefficients()[0]
    parameters['ferroelectric']['T0'] += 10
    after = sample._compute_renormalized_coefficients()[0]
    assert after - before == pytest.approx(-10 * parameters['ferroelectric']['a0'])
