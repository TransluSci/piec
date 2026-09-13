"""Runtime registrations consumed by each category's shared behavioral test.

These are minimum representative contracts, supplemented by the model-specific
command and boundary cases in each category module. Adding a class name alone
cannot satisfy discovery: the new driver needs an executable case here.
"""
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import Mock
import importlib

from piec.drivers.awg.agilent_33220a import Agilent33220A
from piec.drivers.awg.agilent_33500 import Agilent33500
from piec.drivers.awg.k_81150a import Keysight81150a
from piec.drivers.awg.rigol_dg1000 import RigolDG1000
from piec.drivers.awg.rigol_dg4000 import RigolDG4000
from piec.drivers.awg.sdg2000 import SDG2000X
from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.emulators.daq_to_awg import DaqAsAwg
from piec.drivers.dmm.agilent_34410a import Agilent34410A
from piec.drivers.dmm.keithley_2000 import Keithley2000
from piec.drivers.dmm.keithley193a import Keithley193a
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.sourcemeter.keithley2400 import Keithley2400
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.drivers.daq.usb231 import USB231
from piec.drivers.daq.usb1208hs import USB1208HS
from piec.drivers.daq.virtual_daq import VirtualDaq
from piec.drivers.lockin.srs830 import SRS830
from piec.drivers.lockin.virtual_lockin import VirtualLockin
from piec.drivers.dc_calibrator.edc522 import EDC522
from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
from piec.drivers.stepper_motor.arduino_stepper import Geos_Stepper
from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
from piec.drivers.pulser.bnc765 import BNC765
from piec.drivers.pulser.virtual_pulser import VirtualPulser
from piec.drivers.rf_source.virtual_rf_source import VirtualRFSource
from tests.support.transports import create_test_driver


@dataclass(frozen=True)
class DriverCase:
    cls: type
    factory: object
    operation: object
    expected: object

    def check(self, monkeypatch):
        instrument = self.factory(monkeypatch)
        assert type(instrument) is self.cls, "Fixture must exercise the registered concrete driver"
        assert self.operation(instrument) == self.expected


def physical(cls, responses=None, **state):
    def make(monkeypatch):
        return create_test_driver(cls, responses=responses, strict=True, **state)
    return make


def virtual(cls, **options):
    return lambda monkeypatch: cls(**options)


def trigger_commands(instrument):
    instrument.output_trigger()
    return tuple(instrument.instrument.writes)


def virtual_awg(monkeypatch):
    instrument = VirtualAwg(waveform_hook=Mock(), simulation_points=3)
    return instrument


def virtual_trigger(instrument):
    instrument.output_trigger()
    return instrument.waveform_hook.call_count


def daq_awg(monkeypatch):
    instrument = DaqAsAwg(VirtualDaq())
    instrument.configure_trigger_output(1, .001)
    return instrument


def analog_input(cls):
    def make(monkeypatch):
        if cls is VirtualDaq:
            instrument = cls()
            instrument.state['ai_values'][0] = 1.25
        else:
            # Replace only the vendor boundary. Channel/range validation and
            # the concrete driver's read_AI implementation still execute.
            module = importlib.import_module(cls.__module__)
            monkeypatch.setattr(module, 'ULRange', SimpleNamespace(BIP10VOLTS=10))
            instrument = create_test_driver(cls, board_num=7,
                                            ul=SimpleNamespace(v_in=Mock(return_value=1.25)),
                                            _ai_mode='se', _ai_ranges={})
        return instrument
    return make


def ddc_meter(monkeypatch):
    instrument = create_test_driver(Keithley193a, strict=True)
    instrument.instrument.read = Mock(return_value='NDCV+1.250000E+00')
    return instrument


def virtual_source(monkeypatch):
    instrument = VirtualSourcemeter(load_hook=lambda **kwargs: (1.25, .01))
    instrument.output(1, True)
    return instrument


def output_off(instrument):
    instrument.output(False)
    if isinstance(instrument, VirtualCalibrator):
        return instrument.state['output_on']
    return tuple(instrument.instrument.writes)


def pulser_outputs(instrument):
    instrument.output(1, True)
    if isinstance(instrument, VirtualPulser):
        enabled = instrument.state['output_on'][1]
        instrument.output(1, False)
        return enabled, instrument.state['output_on'][1]
    instrument.output(1, False)
    return tuple(instrument.instrument.writes)


def rf_frequency(instrument):
    instrument.set_frequency(2.4e9)
    return instrument.state['frequency']


DRIVER_CASES = {
    'awg': [
        DriverCase(cls, physical(cls, **({'protocol': 'dg1000z'} if cls is RigolDG1000 else {})),
                   trigger_commands, (command,))
        for cls, command in [(Agilent33220A, '*TRG'), (Agilent33500, '*TRG'),
                             (Keysight81150a, ':TRIG'), (RigolDG1000, '*TRG'),
                             (RigolDG4000, '*TRG'), (SDG2000X, 'C1:BTWV MTRIG')]
    ] + [DriverCase(VirtualAwg, virtual_awg, virtual_trigger, 1),
         DriverCase(DaqAsAwg, daq_awg, lambda inst: inst.output_trigger()['timing'], 'simulated')],
    'dmm': [
        DriverCase(Agilent34410A, physical(Agilent34410A, {'READ?': '1.25'}), lambda inst: inst.get_voltage(), 1.25),
        DriverCase(Keithley2000, physical(Keithley2000, {':READ?': '1.25'}), lambda inst: inst.get_voltage(), 1.25),
        DriverCase(Keithley193a, ddc_meter, lambda inst: inst.get_voltage(), 1.25),
        DriverCase(VirtualDMM, virtual(VirtualDMM, voltage_reader=lambda: 1.25), lambda inst: inst.get_voltage(), 1.25),
    ],
    'sourcemeter': [
        DriverCase(Keithley2400, physical(Keithley2400, {':READ?': '1.25,.01,125'}), lambda inst: inst.get_voltage(1), 1.25),
        DriverCase(VirtualSourcemeter, virtual_source, lambda inst: inst.get_voltage(1), 1.25),
    ],
    'daq': [DriverCase(cls, analog_input(cls), lambda inst: inst.read_AI(0), 1.25)
            for cls in (VirtualDaq, USB231, USB1208HS)],
    'lockin': [
        DriverCase(SRS830, physical(SRS830, {'SNAP? 1,2': '1.25,.5'}), lambda inst: tuple(inst.quick_read()), (1.25, .5)),
        DriverCase(VirtualLockin, virtual(VirtualLockin, xy_reader=lambda: (1.25, .5)), lambda inst: tuple(inst.quick_read()), (1.25, .5)),
    ],
    'dc_calibrator': [
        DriverCase(EDC522, physical(EDC522), output_off, ('00000000',)),
        DriverCase(VirtualCalibrator, virtual(VirtualCalibrator, output_hook=lambda *args: None), output_off, False),
    ],
    'stepper_motor': [
        DriverCase(Geos_Stepper, physical(Geos_Stepper, {'10,1': '10 Complete'}), lambda inst: inst.step(10, 1), 10),
        DriverCase(VirtualStepper, virtual(VirtualStepper, angle_hook=lambda angle: None), lambda inst: inst.step(10, 1), 10),
    ],
    'pulser': [
        DriverCase(BNC765, physical(BNC765), pulser_outputs, ('OUTPut1:STATe ON', 'OUTPut1:STATe OFF')),
        DriverCase(VirtualPulser, virtual(VirtualPulser), pulser_outputs, (True, False)),
    ],
    'rf_source': [DriverCase(VirtualRFSource, virtual(VirtualRFSource), rf_frequency, 2.4e9)],
}
