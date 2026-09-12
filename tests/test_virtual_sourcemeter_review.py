import pytest

from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.simulation.contracts import CapacitiveLoad, LoadResponse


@pytest.mark.parametrize('read', [
    lambda s: s.get_voltage(), lambda s: s.get_current(),
    lambda s: s.get_resistance(), lambda s: s.quick_read(),
    lambda s: s.effective_voltage, lambda s: s.effective_current,
    lambda s: s.compliance_tripped, lambda s: s.query(':READ?'),
])
def test_failed_shutdown_never_reads_as_confirmed_zero(read):
    error = ValueError('disconnected')
    def hook(output_on):
        if not output_on:
            raise error
        return 1.0, 0.001
    sm = VirtualSourcemeter(load_hook=hook)
    sm.output(on=True)
    with pytest.raises(ValueError) as caught:
        sm.output(on=False)
    assert caught.value is error
    with pytest.raises(RuntimeError, match='unconfirmed'):
        read(sm)
    sm.load_hook = lambda: (0.0, 0.0)
    sm.output(on=False)
    assert sm.effective_voltage == 0.0


@pytest.mark.parametrize('response', [
    {'voltage': 2., 'current': 1., 'compliance_tripped': False},
    LoadResponse(voltage=2., current=1., compliance_tripped=True),
])
def test_declared_compliance_flag_cannot_bypass_limit(response):
    sm = VirtualSourcemeter(load_hook=lambda: response)
    sm.configure_voltage_source(voltage=2., current_compliance=.01)
    with pytest.raises(ValueError, match='exceeds compliance'):
        sm.output(on=True)


def test_capacitor_uses_setup_clock_and_repeat_reads_share_sample():
    load = CapacitiveLoad(capacitance=1., leakage_resistance=1e9, start_time=10.)
    sm = VirtualSourcemeter(load_hook=load)
    sm.configure_current_source(current=.1, voltage_compliance=10.)
    load.timebase.advance(1.)
    sm.output(on=True)
    assert sm.get_voltage() == pytest.approx(.1)
    assert sm.get_current() == pytest.approx(.1)
    assert float(sm.query(':READ?').split(',')[0]) == pytest.approx(.1)
    load.timebase.advance(1.)
    assert sm.get_voltage() == pytest.approx(.2)
    sm.reset()
    assert load.timebase.current_time == 12.


@pytest.mark.parametrize('hook', [
    lambda saved=123: (saved, .001),
    lambda saved=123, /: (saved, .001),
    lambda voltage, unknown: (voltage, unknown),
    lambda mode, unknown, compliance: (unknown, .001),
])
def test_optional_and_mixed_signatures(hook):
    sm = VirtualSourcemeter(load_hook=hook)
    sm.configure_voltage_source(voltage=2.)
    sm.output(on=True)
    assert sm.get_voltage() in (123., 2.)


def test_inactive_setting_is_not_presented_as_applied_output():
    seen = []
    def hook(voltage, current):
        seen.append((voltage, current))
        return voltage, .001
    sm = VirtualSourcemeter(load_hook=hook)
    sm.set_source_current(current=.4)
    sm.set_source_voltage(voltage=3.)
    sm.output(on=True)
    assert seen[-1] == (3., 0.)


def test_scpi_numeric_output_and_callback_failure():
    def hook(stimulus):
        if stimulus == 2.:
            raise ValueError('callback error')
        return stimulus, .001
    sm = VirtualSourcemeter(load_hook=hook)
    sm.write(':OUTP 1')
    assert sm.query(':OUTP?') == '1'
    with pytest.raises(ValueError, match='callback error'):
        sm.write(':SOUR:VOLT:LEV 2')
    assert sm.query(':OUTP?') == 'UNKNOWN'
    sm.write(':OUTP 0')
    assert sm.query(':OUTP?') == '0'


def test_evaluate_callable_shutdown_typeerror_is_not_swallowed():
    class Hook:
        def evaluate(self, *args, **kwargs):
            return LoadResponse(voltage=0., current=0.)
        def __call__(self, **kwargs):
            raise TypeError('shutdown failure')
    sm = VirtualSourcemeter(load_hook=Hook())
    with pytest.raises(TypeError, match='shutdown failure'):
        sm.output(on=False)
    assert sm.state['output_on'] is None


def test_incomplete_mapping_cannot_use_stale_settings():
    sm = VirtualSourcemeter(load_hook=lambda: {'voltage': 2.})
    with pytest.raises(ValueError, match='voltage and current'):
        sm.output(on=True)


def test_unclocked_callable_does_not_invent_time_or_change_sense_mode():
    times = []
    def hook(time):
        times.append(time)
        return 1., .001
    sm = VirtualSourcemeter(load_hook=hook)
    sm.set_sense_function(sense_func='RES')
    sm.output(on=True)
    assert sm.effective_voltage == 1.
    assert sm.effective_current == .001
    assert sm.state['sense_func'] == 'RES'
    assert times == [None, None, None]
