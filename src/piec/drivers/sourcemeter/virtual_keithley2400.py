"""
Virtual Keithley 2400 SourceMeter Module

A simple virtual implementation of the Keithley 2400 for testing.
Stores state internally and returns the set values directly as measurements.
"""

from ..virtual_instrument import VirtualInstrument
from .sourcemeter import Sourcemeter
from ..scpi import Scpi


class VirtualKeithley2400(VirtualInstrument, Sourcemeter, Scpi):
    """
    Virtual Keithley 2400 SourceMeter for testing without hardware.

    Measurements simply return whatever values were configured 
    """

    channel = [1]
    source_func = ['VOLT', 'CURR']
    sense_func = ['VOLT', 'CURR', 'RES']
    sense_mode = ['2W', '4W']
    voltage = (-210, 210)
    current = (-1.05, 1.05)
    voltage_compliance = (-210, 210)
    current_compliance = (-1.05, 1.05)

    def __init__(self, address='VIRTUAL', **kwargs):
        VirtualInstrument.__init__(self, address=address)
        self.instrument = self

        self.state = {
            'output_on': False,
            'source_func': 'VOLT',
            'source_voltage': 0.0,
            'source_current': 0.0,
            'sense_func': 'VOLT',
            'sense_mode': '2W',
            'voltage_compliance': 210.0,
            'current_compliance': 1.05,
        }

    def idn(self):
        return "Virtual Keithley 2400"

    def write(self, command):
        cmd = command.upper().strip()

        if ':OUTP' in cmd:
            self.state['output_on'] = 'ON' in cmd
        elif ':SOUR:FUNC' in cmd:
            if 'VOLT' in cmd:
                self.state['source_func'] = 'VOLT'
            elif 'CURR' in cmd:
                self.state['source_func'] = 'CURR'
        elif ':SOUR:VOLT:LEV' in cmd:
            try:
                self.state['source_voltage'] = self._clamp(self._extract_value(cmd), *self.voltage)
            except ValueError:
                pass
        elif ':SOUR:CURR:LEV' in cmd:
            try:
                self.state['source_current'] = self._clamp(self._extract_value(cmd), *self.current)
            except ValueError:
                pass
        elif ':SENS:FUNC' in cmd:
            if 'VOLT' in cmd:
                self.state['sense_func'] = 'VOLT'
            elif 'CURR' in cmd:
                self.state['sense_func'] = 'CURR'
            elif 'RES' in cmd:
                self.state['sense_func'] = 'RES'
        elif ':SENS:VOLT:PROT' in cmd:
            try:
                self.state['voltage_compliance'] = self._clamp(self._extract_value(cmd), *self.voltage_compliance)
            except ValueError:
                pass
        elif ':SENS:CURR:PROT' in cmd:
            try:
                self.state['current_compliance'] = self._clamp(self._extract_value(cmd), *self.current_compliance)
            except ValueError:
                pass
        elif ':SYST:RSEN' in cmd:
            self.state['sense_mode'] = '4W' if 'ON' in cmd else '2W'
        elif cmd == '*RST':
            self.reset()
        elif cmd == '*CLS':
            pass

    def query(self, command):
        cmd = command.upper().strip()

        if cmd == '*IDN?':
            return self.idn()
        elif cmd == '*ESR?':
            return '0'
        elif cmd == '*OPC?':
            return '1'
        elif ':READ?' in cmd:
            v = self.state['source_voltage']
            i = self.state['source_current']
            r = v / i if i != 0 else float('inf')
            return f"{v:.6E},{i:.6E},{r:.6E},0.000000E+00,0"
        elif ':SOUR:VOLT:LEV?' in cmd:
            return str(self.state['source_voltage'])
        elif ':SOUR:CURR:LEV?' in cmd:
            return str(self.state['source_current'])
        elif ':OUTP?' in cmd:
            return '1' if self.state['output_on'] else '0'
        return ''

    @staticmethod
    def _extract_value(command):
        parts = command.replace(':', ' ').replace(',', ' ').split()
        for part in reversed(parts):
            try:
                return float(part)
            except ValueError:
                continue
        raise ValueError(f"No numeric value found in command: {command}")

    @staticmethod
    def _clamp(value, lo, hi):
        return max(lo, min(hi, value))

    # Core Instrument State Control

    def output(self, on=True):
        self.state['output_on'] = on

    def set_source_function(self, source_func):
        self.state['source_func'] = source_func.upper()

    def set_sense_function(self, sense_func):
        self.state['sense_func'] = sense_func.upper()

    def set_sense_mode(self, sense_mode):
        self.state['sense_mode'] = sense_mode.upper()

    # Source Configuration

    def set_source_voltage(self, voltage):
        self.state['source_voltage'] = self._clamp(voltage, *self.voltage)

    def set_source_current(self, current):
        self.state['source_current'] = self._clamp(current, *self.current)

    def set_voltage_compliance(self, voltage_compliance):
        self.state['voltage_compliance'] = voltage_compliance

    def set_current_compliance(self, current_compliance):
        self.state['current_compliance'] = current_compliance

    # Convenience Configuration

    def configure_voltage_source(self, voltage, current_compliance):
        self.set_source_function('VOLT')
        self.set_source_voltage(voltage)
        self.set_current_compliance(current_compliance)

    def configure_current_source(self, current, voltage_compliance):
        self.set_source_function('CURR')
        self.set_source_current(current)
        self.set_voltage_compliance(voltage_compliance)

    # Measurement Methods (just return set values)

    def quick_read(self):
        sense = self.state['sense_func']
        if sense == 'VOLT':
            return self.state['source_voltage']
        elif sense == 'CURR':
            return self.state['source_current']
        elif sense == 'RES':
            v, i = self.state['source_voltage'], self.state['source_current']
            return v / i if i != 0 else float('inf')
        return self.state['source_voltage']

    def get_voltage(self):
        self.state['sense_func'] = 'VOLT'
        return self.state['source_voltage']

    def get_current(self):
        self.state['sense_func'] = 'CURR'
        return self.state['source_current']

    def get_resistance(self):
        self.state['sense_func'] = 'RES'
        v, i = self.state['source_voltage'], self.state['source_current']
        return v / i if i != 0 else float('inf')

    def reset(self):
        self.__init__(address='VIRTUAL')

    def clear(self):
        pass

    def get_state(self):
        return self.state.copy()
