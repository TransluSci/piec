import time
from .pulser import Pulser
from ..scpi import Scpi

class BNC765(Pulser, Scpi):
    """
    Berkeley Nucleonics 765 Pulse Generator
    """

    AUTODETECT_ID = "BNC765"
    channel = [1, 2, 3, 4]

    period = (1.25e-9, 8.0)
    frequency = (0.125, 800e6)
    width = (300e-12, 8.0)
    delay = (0.0, 8.0)
    rise_time = (70e-12, 8.0)
    fall_time = (70e-12, 8.0)
    high_level = (-5.0, 5.0)
    low_level = (-5.0, 5.0)
    offset = (-2.5, 2.5)
    
    trigger_source = ['INT', 'EXT', 'MAN']
    trigger_mode = ['CONT', 'BURS']
    burst_count = (1, 1000000)
    polarity = ['NORM', 'INV']

    def set_period(self, channel, period):
        """Sets the period of the pulse"""
        self.instrument.write(f"SOURce{channel}:FREQuency {1.0 / period}")

    def set_frequency(self, channel, frequency):
        """Sets the frequency of the pulse"""
        self.instrument.write(f"SOURce{channel}:FREQuency {frequency}")

    def set_width(self, channel, width):
        """Sets the width of the pulse"""
        self.instrument.write(f"SOURce{channel}:PULSe:WIDTh {width}")

    def set_delay(self, channel, delay):
        """Sets the delay before the pulse starts"""
        self.instrument.write(f"SOURce{channel}:PULSe:DELay {delay}")

    def set_rise_time(self, channel, rise_time):
        """Sets the rise time of the pulse"""
        self.instrument.write(f"SOURce{channel}:PULSe:TRANsition:LEADing {rise_time}")

    def set_fall_time(self, channel, fall_time):
        """Sets the fall time of the pulse"""
        self.instrument.write(f"SOURce{channel}:PULSe:TRANsition:TRAiling {fall_time}")

    def set_high_level(self, channel, high_level):
        """Sets the high level of the pulse"""
        current_amp = float(self.instrument.query(f"SOURce{channel}:VOLTage:LEVel?"))
        current_offset = float(self.instrument.query(f"SOURce{channel}:VOLTage:OFFSet?"))
        current_low = current_offset - (current_amp / 2.0)
        
        new_amp = high_level - current_low
        new_offset = current_low + (new_amp / 2.0)
        
        self.instrument.write(f"SOURce{channel}:VOLTage:LEVel {new_amp}")
        self.instrument.write(f"SOURce{channel}:VOLTage:OFFSet {new_offset}")

    def set_low_level(self, channel, low_level):
        """Sets the low level of the pulse"""
        current_amp = float(self.instrument.query(f"SOURce{channel}:VOLTage:LEVel?"))
        current_offset = float(self.instrument.query(f"SOURce{channel}:VOLTage:OFFSet?"))
        current_high = current_offset + (current_amp / 2.0)
        
        new_amp = current_high - low_level
        new_offset = low_level + (new_amp / 2.0)
        
        self.instrument.write(f"SOURce{channel}:VOLTage:LEVel {new_amp}")
        self.instrument.write(f"SOURce{channel}:VOLTage:OFFSet {new_offset}")

    def set_offset(self, channel, offset):
        """Sets the offset of the pulse"""
        self.instrument.write(f"SOURce{channel}:VOLTage:OFFSet {offset}")

    def output(self, channel, on=True):
        """Turns the pulse output on or off for the specified channel"""
        state = "ON" if on else "OFF"
        self.instrument.write(f"OUTPut{channel}:STATe {state}")

    def set_trigger_source(self, source):
        """Sets the trigger source for the pulse"""
        mapping = {'INT': 'INTERNAL', 'EXT': 'EXTERNAL', 'MAN': 'MANUAL'}
        src = mapping.get(source.upper(), source.upper())
        self.instrument.write(f"TRIGger:SOURce {src}")

    def set_trigger_mode(self, mode):
        """Sets the trigger mode for the pulse"""
        mapping = {'CONT': 'CONTINUOUS', 'BURS': 'BURST'}
        m = mapping.get(mode.upper(), mode.upper())
        self.instrument.write(f"TRIGger:MODe {m}")
        
    def set_burst_count(self, channel, count):
        """Sets the number of pulses in a burst"""
        self.instrument.write(f"SOURce{channel}:BURSt:NCYCles {count}")

    def set_polarity(self, channel, polarity):
        """Sets the polarity of the pulse output"""
        state = "ON" if polarity.upper() == 'INV' else "OFF"
        self.instrument.write(f"SOURce{channel}:INVert {state}")
