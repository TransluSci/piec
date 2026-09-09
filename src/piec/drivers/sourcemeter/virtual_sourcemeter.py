"""Generic virtual sourcemeter for testing and simulation."""

from ..virtual_instrument import VirtualInstrument
from .sourcemeter import Sourcemeter


class VirtualSourcemeter(VirtualInstrument, Sourcemeter):
    """
    Virtual source-and-measure instrument for testing without hardware.

    Measurements are produced by the shared external virtual sample.
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
        super().__init__(address=address, **kwargs)
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
        return "PIEC,Virtual_Sourcemeter,s/n_virtual,ver1.0"

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
            v, i = self._measured_voltage_current()
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

    def output(self, channel=1, on=True):
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        self.state['output_on'] = on

    def set_source_function(self, channel=1, source_func=None):
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if source_func is None:
            raise ValueError("source_func must be provided")
        self.state['source_func'] = source_func.upper()

    def set_sense_function(self, channel=1, sense_func=None):
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if sense_func is None:
            raise ValueError("sense_func must be provided")
        self.state['sense_func'] = sense_func.upper()

    def set_sense_mode(self, channel=1, sense_mode=None):
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if sense_mode is None:
            raise ValueError("sense_mode must be provided")
        self.state['sense_mode'] = sense_mode.upper()

    # Source Configuration

    def set_source_voltage(self, channel=1, voltage=None):
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if voltage is None:
            raise ValueError("voltage must be provided")
        self.state['source_voltage'] = self._clamp(voltage, *self.voltage)

    def set_source_current(self, channel=1, current=None):
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if current is None:
            raise ValueError("current must be provided")
        self.state['source_current'] = self._clamp(current, *self.current)

    def set_voltage_compliance(self, channel=1, voltage_compliance=None):
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if voltage_compliance is None:
            raise ValueError("voltage_compliance must be provided")
        self.state['voltage_compliance'] = voltage_compliance

    def set_current_compliance(self, channel=1, current_compliance=None):
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        if current_compliance is None:
            raise ValueError("current_compliance must be provided")
        self.state['current_compliance'] = current_compliance

    # Convenience Configuration

    def configure_voltage_source(self, channel=1, voltage=0.0, current_compliance=1.05):
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        self.set_source_function(channel=channel, source_func='VOLT')
        self.set_source_voltage(channel=channel, voltage=voltage)
        self.set_current_compliance(
            channel=channel,
            current_compliance=current_compliance,
        )

    def configure_current_source(self, channel=1, current=0.0, voltage_compliance=210):
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        self.set_source_function(channel=channel, source_func='CURR')
        self.set_source_current(channel=channel, current=current)
        self.set_voltage_compliance(
            channel=channel,
            voltage_compliance=voltage_compliance,
        )

    # Generic instrument status methods

    def error(self):
        return '0'

    def wait(self):
        return None

    def self_test(self):
        return '0'

    def operation_complete(self):
        return '1'

    # Measurement Methods

    def _measured_voltage_current(self):
        """Return the response of the shared external virtual sample."""
        if self.state['source_func'] == 'CURR':
            current = self.state['source_current']
            voltage, _ = self.sample.current_response(current, 0.0)
            voltage = self._clamp(
                float(voltage),
                -self.state['voltage_compliance'],
                self.state['voltage_compliance'],
            )
        else:
            voltage = self.state['source_voltage']
            current, _ = self.sample.voltage_response(voltage, 0.0)
            current = self._clamp(
                float(current),
                -self.state['current_compliance'],
                self.state['current_compliance'],
            )
        return voltage, current

    def quick_read(self, channel=1):
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        sense = self.state['sense_func']
        voltage, current = self._measured_voltage_current()
        if sense == 'VOLT':
            return voltage
        elif sense == 'CURR':
            return current
        elif sense == 'RES':
            return voltage / current if current != 0 else float('inf')
        return voltage

    def get_voltage(self, channel=1):
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        self.state['sense_func'] = 'VOLT'
        voltage, _ = self._measured_voltage_current()
        return voltage

    def get_current(self, channel=1):
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        self.state['sense_func'] = 'CURR'
        _, current = self._measured_voltage_current()
        return current

    def get_resistance(self, channel=1):
        if channel not in self.channel:
            raise ValueError(f"Invalid channel {channel}. Must be one of {self.channel}")
        self.state['sense_func'] = 'RES'
        v, i = self._measured_voltage_current()
        return v / i if i != 0 else float('inf')

    def reset(self):
        self.__init__(address='VIRTUAL')

    def clear(self):
        pass

    def get_state(self):
        return self.state.copy()
