"""Pulse dispatch, physical command sequencing, and cleanup without hardware."""
import threading
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from piec.drivers.daq.daq import Daq
from piec.drivers.daq.usb231 import USB231
from piec.drivers.daq.usb1208hs import USB1208HS
from piec.drivers.daq.virtual_daq import VirtualDaq
from piec.drivers.emulators.daq_to_awg import DaqAsAwg


class DigitalDaq(Daq):
    dio_channel = [0, 1]
    ao_channel = [0]
    ao_sample_rate = (1, 1000)

    def __init__(self):
        self.check_params = False
        self.events = []

    def set_DIO_mode(self, channel, mode):
        self.events.append(('mode', channel, mode))

    def write_DO(self, channel, data):
        self.events.append(('write', channel, data))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr('piec.drivers.daq.daq.time.sleep', lambda duration: None)


@pytest.mark.parametrize('active_high,levels', [(True, [0, 1, 0]), (False, [1, 0, 1])])
def test_software_sequence(active_high, levels):
    daq = DigitalDaq()
    result = daq.send_trigger_pulse(1, .001, active_high)
    assert daq.events == [('mode', 1, 'o')] + [('write', 1, level) for level in levels]
    assert result['timing'] == 'software'
    assert result['programmed_pulse_width'] is None


@pytest.mark.parametrize('changes,error', [
    ({'channel': 9}, ValueError), ({'channel': True}, ValueError),
    ({'pulse_width': 0}, ValueError), ({'pulse_width': -1}, ValueError),
    ({'pulse_width': float('nan')}, ValueError),
    ({'pulse_width': float('inf')}, ValueError),
    ({'pulse_width': True}, ValueError), ({'pulse_width': 61}, ValueError),
    ({'active_high': 1}, ValueError), ({'resource': 'timer'}, NotImplementedError),
    ({'require_hardware_timing': True}, NotImplementedError),
])
def test_invalid_request_never_touches_outputs(changes, error):
    daq = DigitalDaq()
    kwargs = dict(channel=0, pulse_width=.001)
    kwargs.update(changes)
    with pytest.raises(error):
        daq.send_trigger_pulse(**kwargs)
    assert daq.events == []


def test_base_stubs_do_not_advertise_pulses():
    daq = object.__new__(Daq)
    daq.check_params = False
    daq.dio_channel = [0]
    with pytest.raises(NotImplementedError):
        daq.send_trigger_pulse(0, .001)


def test_failed_active_write_still_restores_idle():
    daq = DigitalDaq()
    daq.write_DO = Mock(side_effect=[None, OSError('USB failed'), None])
    with pytest.raises(OSError, match='USB failed'):
        daq.send_trigger_pulse(0, .001)
    assert daq.write_DO.call_args_list == [call(0, 0), call(0, 1), call(0, 0)]


def test_cancelled_before_start_produces_no_edges():
    daq = DigitalDaq()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        daq.send_trigger_pulse(0, .001, cancel_event=cancel)
    assert daq.events == []


def test_cancelled_active_pulse_restores_idle():
    daq = DigitalDaq()
    cancel = Mock()
    cancel.wait.side_effect = [False, True]
    with pytest.raises(InterruptedError):
        daq.send_trigger_pulse(0, .001, cancel_event=cancel)
    assert daq.events[-1] == ('write', 0, 0)


@pytest.fixture
def timer(monkeypatch):
    monkeypatch.setattr('piec.drivers.daq.usb1208hs.TimerIdleState',
                        SimpleNamespace(LOW=0, HIGH=1))
    daq = object.__new__(USB1208HS)
    daq.check_params = False
    daq.board_num = 3
    daq.ul = Mock()
    daq.ul.pulse_out_start.return_value = (400.0, .5, .0001)
    daq._wait_trigger_pulse = Mock()
    return daq


@pytest.mark.parametrize('active_high,idle', [(True, 0), (False, 1)])
def test_timer_single_pulse_and_actual_period(timer, active_high, idle):
    result = timer.send_trigger_pulse(0, .001, active_high, resource='timer',
                                      require_hardware_timing=True)
    timer.ul.pulse_out_start.assert_called_once_with(
        3, 0, 500.0, .5, pulse_count=1, initial_delay=0, idle_state=idle)
    assert timer._wait_trigger_pulse.call_args.args[0] == pytest.approx(.0026)
    timer.ul.pulse_out_stop.assert_called_once_with(3, 0)
    timer.ul.d_bit_out.assert_not_called()
    assert result['timing'] == 'hardware'
    assert result['programmed_pulse_width'] == pytest.approx(.00125)


@pytest.mark.parametrize('failure', ['start', 'wait', 'bad_return'])
def test_timer_failure_stops_without_software_retry(timer, failure):
    if failure == 'start':
        timer.ul.pulse_out_start.side_effect = OSError('start')
    elif failure == 'wait':
        timer._wait_trigger_pulse.side_effect = [None, InterruptedError('cancel')]
    else:
        timer.ul.pulse_out_start.return_value = (0, .5, 0)
    with pytest.raises((OSError, ValueError)):
        timer.send_trigger_pulse(0, .001, resource='timer')
    timer.ul.pulse_out_stop.assert_called_once_with(3, 0)
    timer.ul.d_bit_out.assert_not_called()


def test_usb231_uses_digital_fallback(monkeypatch):
    monkeypatch.setattr('piec.drivers.daq.usb231.DigitalPortType', SimpleNamespace(AUXPORT=7))
    monkeypatch.setattr('piec.drivers.daq.usb231.DigitalIODirection', SimpleNamespace(OUT=1, IN=0))
    daq = object.__new__(USB231)
    daq.check_params = False
    daq.board_num = 2
    daq.ul = Mock()
    result = daq.send_trigger_pulse(0, .001)
    assert result['timing'] == 'software'
    assert daq.ul.d_bit_out.call_args_list == [call(2, 7, 0, x) for x in (0, 1, 0)]
    daq.ul.pulse_out_start.assert_not_called()


def test_emulator_generic_dispatch_and_virtual_history():
    daq = VirtualDaq()
    awg = DaqAsAwg(daq)
    awg.configure_trigger_output(1, .001)
    assert 'trigger_pulses' not in daq.state
    original_ao = dict(daq.state['ao_values'])
    result = awg.output_trigger()
    assert result['timing'] == 'simulated'
    assert daq.state['trigger_pulses'] == [result]
    assert daq.state['dio_values'][1] == 0
    assert daq.state['ao_values'] == original_ao
    with pytest.raises(NotImplementedError):
        awg.configure_trigger_output(1, .001, require_hardware_timing=True)


def test_emulator_timer_dispatch(timer):
    awg = DaqAsAwg(timer, check_params=True)
    awg.configure_trigger_output(0, .001, resource='timer', require_hardware_timing=True)
    timer.ul.pulse_out_start.assert_not_called()
    assert awg.output_trigger()['timing'] == 'hardware'
    timer.ul.pulse_out_start.assert_called_once()
