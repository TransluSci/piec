import numpy as np
import struct
from .awg import Awg
from ..scpi import Scpi

class SDG2000X(Awg, Scpi):
    """
    Driver for the Siglent SDG2000X Series Arbitrary Waveform Generator.
    Based on the Programming Guide PG02-E03B.
    """

    # --- AUTODETECT IDENTIFIER ---
    # Derived from *IDN? response examples in the manual.
    # The manual explicitly lists responses for these models in the examples[cite: 198, 1407, 1467].
    AUTODETECT_ID = ["SDG2042X", "SDG2122X", "SDG2102X"]

    # --- INSTRUMENT PARAMETERS ---
    
    # Channel: The manual specifies C1 and C2[cite: 318].
    channel = [1, 2]

    # Waveform: Mapped from manual types SINE, SQUARE, RAMP, PULSE, NOISE, ARB, DC, PRBS[cite: 328].
    waveform = ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER', 'PRBS']

    # Frequency: Manual refers to the data sheet for valid ranges[cite: 328].
    frequency = {
        'func': {
            'SIN': (None, None), 
            'SQU': (None, None), 
            'RAMP': (None, None), 
            'PULS': (None, None), 
            'NOIS': (None, None), 
            'DC': (None, None), 
            'USER': (None, None),
            'PRBS': (None, None)
        }
    }

    # Amplitude: Manual refers to the data sheet for valid ranges[cite: 328].
    amplitude = (None, None)
    
    # Offset: Manual refers to the data sheet for valid ranges[cite: 328].
    offset = (None, None)

    # Load Impedance: Manual lists 50 to 100000 Hz for SDG2000X[cite: 321].
    load_impedance = (50, 100000)

    # Source Impedance: Not specified as a settable parameter in the OUTPUT command[cite: 318].
    source_impedance = None

    # Polarity: Manual lists NOR (Normal) and INVT (Invert)[cite: 318].
    polarity = ['NORM', 'INV']

    # Duty Cycle: Manual lists 0 to 100%[cite: 328].
    duty_cycle = (0.0, 100.0)

    # Symmetry: Manual lists 0 to 100%[cite: 328].
    symmetry = (0.0, 100.0)

    # Pulse Width: Manual refers to the data sheet[cite: 328].
    pulse_width = (None, None)
    
    # Pulse Delay: Manual refers to the data sheet[cite: 337].
    pulse_delay = (None, None)

    # Rise/Fall Time: Manual refers to the data sheet[cite: 328, 337].
    rise_time = (None, None)
    fall_time = (None, None)

    # Trigger Source: Manual lists EXT, INT, MAN[cite: 463].
    trigger_source = ['INT', 'EXT', 'MAN']

    # Trigger Slope: Manual lists RISE, FALL[cite: 463].
    trigger_slope = ['POS', 'NEG']

    # Trigger Mode: Manual lists GATE and NCYC[cite: 463].
    # Mapped to 'LEV' (Level/Gated) and 'EDGE' (Cycle/Edge).
    trigger_mode = ["EDGE", "LEV"] 

    # Arb Data Range: Manual specifies 16B - 16MB for SDG2000X[cite: 715].
    arb_data_range = (16, 16777216)


    def output(self, channel, on=True):
        """
        Turns the output of a specified channel on or off[cite: 318].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")
        
        state = "ON" if on else "OFF"
        self.instrument.write(f"C{channel}:OUTP {state}")

    def set_waveform(self, channel, waveform):
        """
        Sets the built_in waveform type[cite: 328].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        mapping = {
            'SIN': 'SINE', 'SQU': 'SQUARE', 'RAMP': 'RAMP',
            'PULS': 'PULSE', 'NOIS': 'NOISE', 'DC': 'DC',
            'USER': 'ARB', 'PRBS': 'PRBS'
        }
        
        if waveform not in mapping:
             raise ValueError(f"Invalid waveform. Must be one of {list(mapping.keys())}")

        self.instrument.write(f"C{channel}:BSWV WVTP,{mapping[waveform]}")

    def set_frequency(self, channel, frequency):
        """
        Sets the frequency of the waveform[cite: 328].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")
        
        self.instrument.write(f"C{channel}:BSWV FRQ,{frequency}")

    def set_amplitude(self, channel, amplitude):
        """
        Sets the amplitude (Vpp)[cite: 328].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        self.instrument.write(f"C{channel}:BSWV AMP,{amplitude}")

    def set_offset(self, channel, offset):
        """
        Sets the offset voltage[cite: 328].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        self.instrument.write(f"C{channel}:BSWV OFST,{offset}")

    def set_load_impedance(self, channel, load_impedance):
        """
        Sets the output load impedance[cite: 318, 321].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        self.instrument.write(f"C{channel}:OUTP LOAD,{load_impedance}")

    def set_polarity(self, channel, polarity):
        """
        Sets the output polarity[cite: 318].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        mapping = {'NORM': 'NOR', 'INV': 'INVT'}
        if polarity not in mapping:
            raise ValueError(f"Invalid polarity. Must be one of {list(mapping.keys())}")

        self.instrument.write(f"C{channel}:OUTP PLRT,{mapping[polarity]}")

    def set_square_duty_cycle(self, channel, duty_cycle):
        """
        Sets the duty cycle for Square waves[cite: 328].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        self.instrument.write(f"C{channel}:BSWV DUTY,{duty_cycle}")

    def set_ramp_symmetry(self, channel, symmetry):
        """
        Sets the symmetry for Ramp waves[cite: 328].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        self.instrument.write(f"C{channel}:BSWV SYM,{symmetry}")

    def set_pulse_width(self, channel, pulse_width):
        """
        Sets the positive pulse width[cite: 328].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        self.instrument.write(f"C{channel}:BSWV WIDTH,{pulse_width}")

    def set_pulse_rise_time(self, channel, rise_time):
        """
        Sets the rise time for Pulse waves[cite: 328].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        self.instrument.write(f"C{channel}:BSWV RISE,{rise_time}")

    def set_pulse_fall_time(self, channel, fall_time):
        """
        Sets the fall time for Pulse waves[cite: 337].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        self.instrument.write(f"C{channel}:BSWV FALL,{fall_time}")

    def set_pulse_duty_cycle(self, channel, duty_cycle):
        """
        Sets the duty cycle for Pulse waves[cite: 328].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        self.instrument.write(f"C{channel}:BSWV DUTY,{duty_cycle}")

    def set_pulse_delay(self, channel, pulse_delay):
        """
        Sets the pulse delay[cite: 337].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        self.instrument.write(f"C{channel}:BSWV DLY,{pulse_delay}")

    def create_arb_waveform(self, channel, name, data):
        """
        Creates/Downloads an arbitrary waveform to the instrument[cite: 697, 715, 1549].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")
        
        # Convert data to binary (Little endian, 16-bit 2's complement) as per Python Example 4.1.5
        # Example 4.1.5 converts values to hex strings then bytes, but direct packing is more efficient.
        if isinstance(data, (list, tuple, np.ndarray)):
            # Ensure data consists of integers
            data = [int(x) for x in data]
            binary_data = b''.join([struct.pack('<h', x) for x in data])
        else:
            binary_data = data 

        # Construct header command. 
        # Example 4.1.5 uses: C1:WVDT WVNM,wave1, ... WAVEDATA,<data>
        cmd_header = f"C{channel}:WVDT WVNM,{name},WAVEDATA,"
        
        # Send raw command with binary data appended
        self.instrument.write_raw(cmd_header.encode('ascii') + binary_data)

    def set_arb_waveform(self, channel, name):
        """
        Selects an arbitrary waveform by name[cite: 501].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        self.instrument.write(f"C{channel}:ARWV NAME,{name}")

    def set_trigger_source(self, channel, trigger_source):
        """
        Sets the trigger source for Burst/Sweep modes[cite: 463].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        mapping = {'INT': 'INT', 'EXT': 'EXT', 'MAN': 'MAN'}
        if trigger_source not in mapping:
             raise ValueError(f"Invalid trigger source. Must be one of {list(mapping.keys())}")
        
        self.instrument.write(f"C{channel}:BTWV TRSR,{mapping[trigger_source]}")

    def set_trigger_slope(self, channel, trigger_slope):
        """
        Sets the trigger edge (slope)[cite: 463].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        mapping = {'POS': 'RISE', 'NEG': 'FALL'}
        if trigger_slope not in mapping:
            raise ValueError(f"Invalid trigger slope. Must be one of {list(mapping.keys())}")

        self.instrument.write(f"C{channel}:BTWV EDGE,{mapping[trigger_slope]}")

    def set_trigger_mode(self, channel, trigger_mode):
        """
        Sets the burst mode (Gated or Cycle) which corresponds to Level or Edge triggering[cite: 463].
        """
        if channel not in self.channel:
            raise ValueError(f"Invalid channel. Must be one of {self.channel}")

        mapping = {'EDGE': 'NCYC', 'LEV': 'GATE'}
        if trigger_mode not in mapping:
             raise ValueError(f"Invalid trigger mode. Must be one of {list(mapping.keys())}")

        self.instrument.write(f"C{channel}:BTWV GATE_NCYC,{mapping[trigger_mode]}")

    def output_trigger(self):
        """
        Sends a manual trigger signal[cite: 446].
        Defaulting to Channel 1 as this is a device-action.
        """
        self.instrument.write(f"C1:BTWV MTRIG")