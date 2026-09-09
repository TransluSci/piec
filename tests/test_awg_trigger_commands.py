"""Model-specific command regressions; source references live in docs/awg_trigger_support.md."""

from unittest.mock import Mock, call, patch

import pytest

from piec.drivers.awg.agilent_33220a import Agilent33220A
from piec.drivers.awg.agilent_33500 import Agilent33500
from piec.drivers.awg.rigol_dg1000 import RigolDG1000
from piec.drivers.awg.rigol_dg4000 import RigolDG4000


def driver(cls, protocol=None, check_params=False):
    instance = cls.__new__(cls)
    instance.instrument = Mock()
    instance.check_params = check_params
    if protocol is not None:
        instance._rigol_protocol = protocol
    return instance


PROFILES = [
    (Agilent33220A, None, 1, 'TRIG', 'BURS', 'IMM', 'BUS'),
    (Agilent33500, None, 2, 'TRIG2', 'SOUR2:BURS', 'IMM', 'BUS'),
    (RigolDG1000, 'dg1000', 1, 'TRIG', 'BURS', 'IMM', 'BUS'),
    (RigolDG1000, 'dg1000z', 2, 'TRIG2', 'SOUR2:BURS', 'INT', 'BUS'),
    (RigolDG4000, None, 2, 'SOUR2:BURS:TRIG', 'SOUR2:BURS', 'INT', 'MAN'),
]


@pytest.mark.parametrize('check_params', [False, True])
@pytest.mark.parametrize('cls,protocol,ch,trig,burst,internal,manual', PROFILES)
def test_trigger_commands_and_omitted_settings(cls, protocol, ch, trig, burst, internal, manual, check_params):
    awg = driver(cls, protocol, check_params)
    awg.configure_trigger(ch, trigger_source='MaN', trigger_slope='nEg', trigger_mode='EDGE')
    assert awg.instrument.write.call_args_list == [
        call(f'{trig}:SOUR {manual}'), call(f'{trig}:SLOP NEG'), call(f'{burst}:MODE TRIG')]
    awg.instrument.reset_mock()
    awg.configure_trigger(ch)
    awg.instrument.write.assert_not_called()
    for value in ('INT', 'IMM'):
        awg.set_trigger_source(ch, value)
        awg.instrument.write.assert_called_with(f'{trig}:SOUR {internal}')
    awg.set_trigger_source(ch, 'BUS')
    awg.instrument.write.assert_called_with(f'{trig}:SOUR {manual}')
    awg.set_trigger_source(ch, 'EXT')
    awg.instrument.write.assert_called_with(f'{trig}:SOUR EXT')
    awg.set_trigger_mode(ch, 'LEV')
    awg.instrument.write.assert_called_with(f'{burst}:MODE GAT')


@pytest.mark.parametrize('cls,protocol,ch,trig,burst,internal,manual', PROFILES)
@pytest.mark.parametrize('bad', [
    {'trigger_source': 'EXT;*RST'}, {'trigger_slope': 'EITH'},
    {'trigger_mode': 'nonsense'}, {'trigger_function': 'auto'},
    {'trigger_function': 'sweep', 'trigger_mode': 'LEV'},
])
def test_invalid_configuration_writes_nothing(cls, protocol, ch, trig, burst, internal, manual, bad):
    awg = driver(cls, protocol)
    args = {'trigger_source': 'EXT', **bad}
    with pytest.raises(ValueError):
        awg.configure_trigger(ch, **args)
    awg.instrument.write.assert_not_called()


@pytest.mark.parametrize('cls,protocol,ch,trig,burst,internal,manual', PROFILES)
@pytest.mark.parametrize('channel', [0, 3, True, '1', 1.5])
def test_bad_channel_never_writes(cls, protocol, ch, trig, burst, internal, manual, channel):
    awg = driver(cls, protocol)
    with pytest.raises(ValueError):
        awg.configure_trigger(channel, trigger_source='MAN')
    awg.instrument.write.assert_not_called()


@pytest.mark.parametrize('cls,protocol', [(Agilent33220A, None), (Agilent33500, None),
                                        (RigolDG1000, 'dg1000z'), (RigolDG4000, None)])
def test_software_trigger_is_single_bus_command_without_output_enable(cls, protocol):
    awg = driver(cls, protocol)
    awg.output_trigger()
    awg.instrument.write.assert_called_once_with('*TRG')


def test_dg4000_sweep_has_its_own_trigger_subsystem():
    awg = driver(RigolDG4000)
    awg.configure_trigger(2, trigger_source='EXT', trigger_slope='POS', trigger_function='sweep')
    assert awg.instrument.write.call_args_list == [
        call('SOUR2:SWE:TRIG:SOUR EXT'), call('SOUR2:SWE:TRIG:SLOP POS')]


@pytest.mark.parametrize('level', [0.9, 2.0, 3.8])
def test_33500_programmed_trigger_level(level):
    awg = driver(Agilent33500)
    awg.set_trigger_level(2, level)
    awg.instrument.write.assert_called_once_with(f'TRIG2:LEV {level}')


@pytest.mark.parametrize('level', [0.8, 3.9, float('nan'), float('inf'), True, '2'])
def test_invalid_trigger_level_prevents_even_source_write(level):
    awg = driver(Agilent33500)
    with pytest.raises(ValueError):
        awg.configure_trigger(1, trigger_source='MAN', trigger_level=level)
    awg.instrument.write.assert_not_called()


@pytest.mark.parametrize('cls,protocol', [(Agilent33220A, None), (RigolDG1000, 'dg1000'),
                                        (RigolDG1000, 'dg1000z'), (RigolDG4000, None)])
def test_unimplemented_level_is_explicit_and_does_not_partially_configure(cls, protocol):
    awg = driver(cls, protocol)
    with pytest.raises(NotImplementedError):
        awg.configure_trigger(1, trigger_source='EXT', trigger_level=1.0)
    awg.instrument.write.assert_not_called()


@pytest.mark.parametrize('model,expected', [('DG1022', 'TRIG:SOUR IMM'),
                                          ('DG1022A', 'TRIG:SOUR IMM'),
                                          ('DG1022Z', 'TRIG1:SOUR INT'),
                                          ('DG1062Z', 'TRIG1:SOUR INT')])
def test_rigol_identifies_protocol_once(model, expected):
    awg = driver(RigolDG1000)
    awg.instrument.query.return_value = f'RIGOL TECHNOLOGIES,{model},serial,1.0'
    awg.set_trigger_source(1, 'INT')
    awg.set_trigger_source(1, 'INT')
    awg.instrument.query.assert_called_once_with('*IDN?')
    assert awg.instrument.write.call_args_list == [call(expected), call(expected)]


def test_unknown_rigol_model_is_not_assigned_a_guessed_protocol():
    awg = driver(RigolDG1000)
    awg.instrument.query.return_value = 'RIGOL,DG9999,serial,1.0'
    with pytest.raises(ValueError, match='dialect'):
        awg.set_trigger_source(1, 'MAN')
    awg.instrument.write.assert_not_called()


def test_legacy_rigol_channel_and_software_trigger_limits():
    awg = driver(RigolDG1000, 'dg1000')
    with pytest.raises(NotImplementedError, match='channel 1'):
        awg.set_trigger_source(2, 'MAN')
    with pytest.raises(NotImplementedError, match='not verified'):
        awg.output_trigger()
    awg.instrument.write.assert_not_called()


@pytest.mark.parametrize('protocol,commands', [
    ('dg1000', ['OUTP:CH2 OFF', 'FREQ:CH2 1000', 'VOLT:CH2 2',
                'VOLT:OFFS:CH2 0.2', 'PULS:WIDT:CH2 0.001']),
    ('dg1000z', ['OUTP2 OFF', 'SOUR2:FREQ 1000', 'SOUR2:VOLT 2',
                 'SOUR2:VOLT:OFFS 0.2', 'SOUR2:FUNC:PULS:WIDT 0.001']),
])
def test_rigol_related_output_commands_use_correct_dialect(protocol, commands):
    awg = driver(RigolDG1000, protocol)
    awg.output(2, False)
    awg.set_frequency(2, 1000)
    awg.set_amplitude(2, 2)
    awg.set_offset(2, 0.2)
    awg.set_pulse_width(2, 0.001)
    assert awg.instrument.write.call_args_list == [call(command) for command in commands]


def test_trueform_user_waveform_and_both_pulse_edges():
    awg = driver(Agilent33500)
    awg.set_waveform(2, 'USER')
    awg.set_pulse_edge_time(2, 1e-6)
    assert awg.instrument.write.call_args_list == [call('SOUR2:FUNC ARB'),
        call('SOUR2:FUNC:PULS:TRAN:LEAD 1e-06'), call('SOUR2:FUNC:PULS:TRAN:TRA 1e-06')]


def test_trigger_transport_errors_are_not_swallowed():
    awg = driver(Agilent33500)
    awg.instrument.write.side_effect = OSError('disconnected')
    with pytest.raises(OSError, match='disconnected'):
        awg.output_trigger()


@pytest.mark.parametrize('protocol', ['dg1000', 'dg1000z'])
def test_explicit_rigol_protocol_constructor_never_queries_or_enables_output(protocol):
    with patch('piec.drivers.instrument.PiecManager') as manager:
        awg = RigolDG1000('USB::test', protocol=protocol)
        transport = manager.return_value.open_resource.return_value
        transport.write.assert_not_called()
        awg.set_trigger_source(1, 'EXT')
        transport.query.assert_not_called()
        expected = 'TRIG' if protocol == 'dg1000' else 'TRIG1'
        transport.write.assert_called_once_with(f'{expected}:SOUR EXT')


def test_invalid_rigol_protocol_does_not_open_transport():
    with patch('piec.drivers.instrument.PiecManager') as manager:
        with pytest.raises(ValueError):
            RigolDG1000('USB::test', protocol='guess')
        manager.assert_not_called()


@pytest.mark.parametrize('protocol,prefix,suffix', [('dg1000', '', ':CH2'), ('dg1000z', 'SOUR2:', '')])
def test_rigol_remaining_waveform_commands(protocol, prefix, suffix):
    awg = driver(RigolDG1000, protocol)
    awg.set_waveform(2, 'SIN')
    awg.set_phase(2, 90)
    awg.set_square_duty_cycle(2, 40)
    awg.set_ramp_symmetry(2, 60)
    awg.set_pulse_duty_cycle(2, 20)
    pulse = 'PULS:DCYC' if protocol == 'dg1000' else 'FUNC:PULS:DCYC'
    assert awg.instrument.write.call_args_list == [
        call(f'{prefix}FUNC{suffix} sin'), call(f'{prefix}PHAS{suffix} 90'),
        call(f'{prefix}FUNC:SQU:DCYC{suffix} 40'), call(f'{prefix}FUNC:RAMP:SYMM{suffix} 60'),
        call(f'{prefix}{pulse}{suffix} 20')]


def test_rigol_z_edges_are_independent_and_legacy_rejects_undocumented_commands():
    awg = driver(RigolDG1000, 'dg1000z')
    awg.set_pulse_rise_time(2, 1e-6)
    awg.set_pulse_fall_time(2, 2e-6)
    awg.set_pulse_edge_time(2, 3e-6)
    assert awg.instrument.write.call_args_list == [call('SOUR2:FUNC:PULS:TRAN:LEAD 1e-06'),
        call('SOUR2:FUNC:PULS:TRAN:TRA 2e-06'), call('SOUR2:FUNC:PULS:TRAN:BOTH 3e-06')]
    legacy = driver(RigolDG1000, 'dg1000')
    for method in ('set_pulse_rise_time', 'set_pulse_fall_time', 'set_pulse_edge_time'):
        with pytest.raises(NotImplementedError):
            getattr(legacy, method)(1, 1e-6)
    legacy.instrument.write.assert_not_called()
