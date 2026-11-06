"""Offline SMU transport and clock for testing the physical GCD code path."""

from piec.drivers.sourcemeter.keithley2400 import Keithley2400
from piec.simulation.battery import Battery
from tests.support.transports import ScriptedTransport, create_test_driver


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []
        self.on_sleep = lambda seconds: None

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.on_sleep(seconds)
        self.now += seconds


class BatteryTransport(ScriptedTransport):
    """Execute real driver SCPI against a simulated load; never open VISA."""

    def __init__(self, *, immediate_cutoffs=False):
        super().__init__({'*IDN?': 'KEITHLEY INSTRUMENTS INC.,MODEL 2400,OFFLINE,1.0'})
        self.battery = Battery(capacity_ah=0.00001)
        self.current = 0.0
        self.output_on = False
        self.off_mode = 'NORM'
        self.immediate_cutoffs = immediate_cutoffs
        self.reads = 0

    def write(self, command):
        super().write(command)
        if command == '*RST':
            raise AssertionError('GCD must not reset a battery-connected SMU')
        if command.startswith(':OUTP:SMOD '):
            self.off_mode = command.split()[-1]
        elif command.startswith(':OUTP '):
            assert self.off_mode == 'HIMP', 'Select HIMP before any output transition'
            self.output_on = command.endswith('ON')
        elif command.startswith(':SOUR:CURR:LEV '):
            self.current = float(command.split()[-1])

    def query(self, command):
        if command == ':READ?':
            self.reads += 1
            current = self.current if self.output_on else 0.0
            if self.immediate_cutoffs:
                voltage = 4.2 if current > 0 else 3.0
            else:
                voltage, _ = self.battery.current_response(current, 0)
            return f'{voltage},{current},0,0,0'
        return super().query(command)

    def advance(self, seconds):
        self.battery.advance_time(self.current if self.output_on else 0.0, seconds)


def scripted_smu(*, immediate_cutoffs=False):
    smu = create_test_driver(Keithley2400)
    smu.instrument = BatteryTransport(immediate_cutoffs=immediate_cutoffs)
    return smu
