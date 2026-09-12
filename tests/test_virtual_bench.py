"""Numerical routing, ownership, replay and real measurement consumer checks."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import numpy as np
import pytest

from piec.analysis.field_calibration import FieldCalibration
from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.drivers.virtual_instrument import VirtualInstrument
from piec.simulation import (
    BenchResetError, CapacitiveLoad, HystereticMagneticMaterial, ResistorLoad, VirtualBench,
)


def electrical(seed=42, **load_parameters):
    bench = VirtualBench(seed=seed, start_time=10.)
    sm = bench.add_instrument('source', VirtualSourcemeter)
    bench.add_model('load', ResistorLoad, resistance=100., **load_parameters)
    bench.connect_load('wire', 'source', 'load')
    return bench, sm


def optical(seed=42, noise=0., output_unit='V'):
    bench = VirtualBench(seed=seed)
    sm = bench.add_instrument('source', VirtualSourcemeter)
    dmm = bench.add_instrument('detector', VirtualDMM)
    bench.add_model('load', ResistorLoad, resistance=1000.)
    bench.add_model('magnet', HystereticMagneticMaterial)
    calibration = FieldCalibration([(-5., -500.), (5., 500.)], output_unit=output_unit)
    bench.connect_moke('optics', 'source', 'load', 'magnet', 'detector', calibration, noise_std=noise)
    return bench, sm, dmm


def test_both_source_modes_solve_terminal_compliance():
    bench, sm = electrical()
    sm.configure_voltage_source(voltage=10., current_compliance=.02)
    sm.output(on=True)
    assert sm.get_voltage() == pytest.approx(2.)
    assert sm.get_current() == pytest.approx(.02)
    assert sm.compliance_tripped
    sm.configure_current_source(current=.1, voltage_compliance=3.)
    assert sm.get_voltage() == pytest.approx(3.)
    assert sm.get_current() == pytest.approx(.03)
    assert sm.compliance_tripped
    assert bench.timebase.current_time == 10.


def test_stateful_load_explicit_time_and_reset():
    bench = VirtualBench(seed=7, start_time=10.)
    sm = bench.add_instrument('source', VirtualSourcemeter)
    load = bench.add_model('capacitor', CapacitiveLoad, capacitance=1.)
    bench.connect_load('wire', 'source', 'capacitor')
    sm.configure_current_source(current=.1, voltage_compliance=10.)
    bench.advance(1.)
    sm.output(on=True)
    assert sm.get_voltage() == pytest.approx(.1)
    assert sm.get_current() == pytest.approx(.1)
    assert load.stored_charge == pytest.approx(.1)
    bench.advance(1.)
    assert sm.get_voltage() == pytest.approx(.2)
    bench.reset()
    assert load.stored_charge == 0.
    assert bench.timebase.current_time == load.timebase.current_time == 10.
    assert sm.state['output_on'] is False
    assert sm.load_hook is not None


def test_two_concurrent_benches_and_reset_do_not_cross_talk():
    a, sa = electrical()
    b, sb = electrical()
    barrier = Barrier(2)
    def run(bench, sm, voltage):
        sm.configure_voltage_source(voltage=voltage)
        sm.output(on=True)
        bench.advance(1.)
        barrier.wait(timeout=10)
        return sm.get_current()
    with ThreadPoolExecutor(max_workers=2) as executor:
        fa = executor.submit(run, a, sa, 1.)
        fb = executor.submit(run, b, sb, 2.)
        assert fa.result() == pytest.approx(.01)
        assert fb.result() == pytest.approx(.02)
    a.reset()
    assert sb.state['output_on'] is True
    assert sb.get_current() == pytest.approx(.02)
    assert b.timebase.current_time == 11.
    assert a.models['load'] is not b.models['load']


def test_optical_routing_remanence_noise_replay_and_measured_field():
    a, sa, da = optical(noise=.001)
    b, sb, db = optical(noise=.001)
    def trace(bench, sm, dmm):
        sm.configure_voltage_source(voltage=0., current_compliance=.1)
        sm.output(on=True)
        values = []
        for v in (-5., 0., 5., 0.):
            bench.advance(.1)
            sm.set_source_voltage(voltage=v)
            values.append(dmm.get_voltage())
            assert bench.field_reader('optics')() == pytest.approx(100. * v)
        return values
    first = trace(a, sa, da)
    assert first[:2] == pytest.approx([.48, .48], abs=.005)
    assert first[2:] == pytest.approx([.52, .52], abs=.005)
    np.testing.assert_array_equal(first, trace(b, sb, db))
    before = b.models['magnet'].magnetization
    a.reset()
    assert b.models['magnet'].magnetization == before
    np.testing.assert_array_equal(first, trace(a, sa, da))


def test_moke_field_uses_compliant_terminal_output_and_unknown_propagates():
    bench, sm, dmm = optical()
    sm.configure_voltage_source(voltage=5., current_compliance=.001)
    sm.output(on=True)
    assert bench.field_reader('optics')() == pytest.approx(100.)  # 1 V, not commanded 5 V
    sm.state['output_on'] = None
    with pytest.raises(RuntimeError, match='unconfirmed'):
        dmm.get_voltage()


def test_waveform_route_output_gate_channel_selection_and_reset():
    bench = VirtualBench(seed=123)
    awg = bench.add_instrument('awg', VirtualAwg, simulation_points=3)
    scope = bench.add_instrument('scope', VirtualScope)
    bench.connect_waveform('wire', 'awg', 'scope', scope_channel=2)
    with pytest.raises(RuntimeError, match='triggered'):
        scope.get_data(2)
    awg.create_arb_waveform(1, 'test', [-1., 0., 1.])
    awg.set_arb_waveform(1, 'test')
    awg.set_amplitude(1, 2.)
    awg.set_offset(1, 3.)
    awg.set_polarity(1, 'INV')
    awg.output(1, True)
    awg.output_trigger()
    result = scope.get_data(2)
    np.testing.assert_allclose(result.Voltage, [5., 3., 1.])
    result.loc[:, 'Voltage'] = 99.
    np.testing.assert_allclose(scope.get_data(2).Voltage, [5., 3., 1.])
    with pytest.raises(ValueError, match='not connected'):
        scope.get_data(1)
    awg.output(1, False)
    awg.output_trigger()
    np.testing.assert_allclose(scope.get_data(2).Voltage, 0.)
    bench.reset()
    with pytest.raises(RuntimeError, match='triggered'):
        scope.get_data(2)


def test_bench_does_not_assign_shared_fallback_and_rejects_reused_instances():
    a, _ = electrical()
    shared = (VirtualInstrument._shared_fe_sample, VirtualInstrument._shared_mag_sample)
    b, _ = optical()[:2]
    assert (VirtualInstrument._shared_fe_sample, VirtualInstrument._shared_mag_sample) == shared
    assert a.instruments['source'].sample is None
    with pytest.raises(TypeError):
        b.add_model('shared', a.models['load'])
    with pytest.raises(TypeError):
        b.add_instrument('shared', a.instruments['source'])
    with pytest.raises(ValueError, match='duplicate'):
        a.add_model('load', ResistorLoad)
    with pytest.raises(TypeError):
        a.models['x'] = a.models['load']


def test_route_conflicts_rejected_without_replacing_hook():
    bench, sm = electrical()
    hook = sm.load_hook
    with pytest.raises(ValueError, match='already connected'):
        bench.connect_load('other', 'source', 'load')
    assert sm.load_hook is hook


def test_current_calibrated_plant_and_mode_mismatch():
    bench, sm, dmm = optical(output_unit='A')
    sm.configure_current_source(current=.1, voltage_compliance=50.)
    sm.output(on=True)
    assert bench.field_reader('optics')() == pytest.approx(5.)  # .05 A at compliance
    with pytest.raises(ValueError, match='mode'):
        sm.set_source_function(source_func='VOLT')
    with pytest.raises(RuntimeError, match='unconfirmed'):
        dmm.get_voltage()
    sm.output(on=False)
    assert bench.field_reader('optics')() == 0.


def test_calibration_unit_failure_leaves_ports_available():
    bench = VirtualBench()
    sm = bench.add_instrument('source', VirtualSourcemeter)
    bench.add_instrument('detector', VirtualDMM)
    bench.add_model('load', ResistorLoad)
    bench.add_model('magnet', HystereticMagneticMaterial)
    bad = FieldCalibration([(-1., -100.), (1., 100.)], field_unit='T')
    with pytest.raises(ValueError, match='units'):
        bench.connect_moke('wire', 'source', 'load', 'magnet', 'detector', bad)
    assert sm.load_hook is None
    assert not bench.routes
    bench.connect_load('wire', 'source', 'load')


@pytest.mark.parametrize('delta', [-1., float('inf'), float('nan')])
def test_invalid_time_does_not_mutate_any_clock(delta):
    bench, _ = electrical()
    with pytest.raises(ValueError):
        bench.advance(delta)
    assert bench.timebase.current_time == bench.models['load'].timebase.current_time == 10.


def test_all_supported_drivers_reset_without_touching_shared_samples():
    from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
    from piec.drivers.lockin.virtual_lockin import VirtualLockin
    from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
    bench, _ = electrical()
    shared = (VirtualInstrument._shared_fe_sample, VirtualInstrument._shared_mag_sample)
    for cls in (VirtualCalibrator, VirtualLockin, VirtualStepper, VirtualAwg, VirtualScope, VirtualDMM):
        bench.add_instrument(cls.__name__, cls)
    bench.reset()
    assert VirtualInstrument._shared_fe_sample is shared[0]
    assert VirtualInstrument._shared_mag_sample is shared[1]


def test_model_and_awg_noise_replay_on_bench_reset():
    bench, sm = electrical(noise_std=1e-6)
    awg = bench.add_instrument('awg', VirtualAwg, simulation_points=10)
    def sample():
        sm.configure_voltage_source(voltage=1.)
        sm.output(on=True)
        awg.set_waveform(1, 'NOIS')
        return sm.get_current(), awg.get_waveform(1)
    first_i, first_wave = sample()
    bench.advance(1.)
    sm.get_current()
    bench.reset()
    next_i, next_wave = sample()
    assert next_i == first_i
    np.testing.assert_array_equal(next_wave, first_wave)


def test_reset_attempts_all_components_and_reports_original_failure():
    bench, sm = electrical()
    bench.advance(2.)
    error = RuntimeError('injected reset failure')
    def fail():
        raise error
    sm.reset = fail
    bench.models['load'].set_temperature(350.)
    with pytest.raises(BenchResetError) as caught:
        bench.reset()
    assert caught.value.errors == (('source', error),)
    assert bench.timebase.current_time == 10.
    assert bench.models['load'].timebase.current_time == 10.


def test_named_rng_streams_are_order_independent_and_reset_in_place():
    a, b = VirtualBench(seed=4), VirtualBench(seed=4)
    stream = a.rng('noise')
    first = stream.normal(size=5)
    b.rng('unrelated').normal(size=50)
    np.testing.assert_array_equal(first, b.rng('noise').normal(size=5))
    a.reset()
    assert a.rng('noise') is stream
    np.testing.assert_array_equal(first, stream.normal(size=5))


def test_real_iv_measurement_matches_hardware_interface_schema():
    from piec.measurement.iv_sweep import IVSweep
    from tests.test_measurement_iv import create_mock_sourcemeter
    bench, sm = electrical()
    options = dict(num_steps=3, dwell_time=0., ramp_delay=0.)
    virtual = IVSweep(sm, **options)
    hardware_interface = IVSweep(create_mock_sourcemeter(resistance=100.), **options)
    virtual.run_experiment(save=False)
    hardware_interface.run_experiment(save=False)
    assert virtual.data.columns.tolist() == hardware_interface.data.columns.tolist() == ['voltage', 'current']
    assert virtual.column_units == hardware_interface.column_units
    np.testing.assert_allclose(virtual.data, hardware_interface.data)


@pytest.mark.parametrize('measured', [False, True])
def test_real_moke_measurement_uses_bench_without_schema_changes(measured):
    from piec.measurement.moke import MokeMeasurement
    from tests.test_moke import measurement
    bench, sm, dmm = optical()
    extras = dict(field_reader=bench.field_reader('optics'), field_reader_unit='Oe') if measured else {}
    options = dict(output_values=[-5., 0., 5., 0., -5.], n_cycles=1,
                   dwell_time=0., ramp_delay=0., max_output_step=1., compliance=.01)
    run = MokeMeasurement(sm, dmm, calibration=FieldCalibration([(-5., -500.), (5., 500.)]), **options, **extras)
    reference = measurement(**options, **extras)
    run.run_experiment(save=False)
    reference.run_experiment(save=False)
    assert run.data.columns.tolist() == reference.data.columns.tolist()
    assert run.column_units == reference.column_units
    np.testing.assert_allclose(run.data.detector_voltage, [.48, .48, .52, .52, .48])
    if measured:
        np.testing.assert_allclose(run.data.field_measured, [-500., 0., 500., 0., -500.])
