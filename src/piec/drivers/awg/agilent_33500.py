# This driver has not been tested yet
from ..scpi import Scpi
from .awg import Awg

class Agilent33500(Scpi, Awg):
    """
    Driver for the Agilent 33500 Series Arbitrary Waveform Generators.
    Covering models like 33511B, 33512B, 33521A, 33522A, etc.
    """
    
    # Class attributes for parameter restrictions
    # IDN example: "Agilent Technologies,33522A,..."
    # We use "335" to catch the series.
    AUTODETECT_ID = "335"
    
    # 33500 series can have 1 or 2 channels
    channel = [1, 2]
    
    waveform = ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER', 'PRBS']
    
    # Frequency ranges (using 30MHz as the typical max for the series, some are 20MHz)
    frequency = {
        'waveform': {
            'SIN': (1e-6, 30e6),
            'SQU': (1e-6, 30e6),
            'RAMP': (1e-6, 200e3),
            'PULS': (1e-6, 30e6),
            'NOIS': None, # Bandwidth fixed
            'DC': None,
            'USER': (1e-6, 30e6),
            'PRBS': (1e-6, 30e6)
        }
    }
    
    # Amplitude: 1 mVpp to 10 Vpp into 50 ohms
    amplitude = (0.001, 10.0)
    
    # Offset: +/- 5V into 50 ohms
    offset = (-5.0, 5.0)
    
    # Phase
    phase = (-360.0, 360.0)
    
    # Duty Cycle (Square)
    duty_cycle = (0.01, 99.99)
    
    # Symmetry (Ramp)
    symmetry = (0.0, 100.0)
    
    # Pulse Width: 16ns upwards
    pulse_width = (16e-9, 2000.0)
    
    # Edges: 8.4ns to 1us (varies by model, 8.4ns is standard for 33500B)
    edge_time = (8.4e-9, 1.0)
    




    def output(self, channel=1, on=True):
        state = "ON" if on else "OFF"
        self.instrument.write(f"OUTP{channel} {state}")

    def set_waveform(self, channel=1, waveform=None):
        if waveform is None:
             raise ValueError("waveform must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC {waveform}")

    def set_frequency(self, channel=1, frequency=None):
        if frequency is None:
             raise ValueError("frequency must be provided")
        self.instrument.write(f"SOUR{channel}:FREQ {frequency}")

    def set_amplitude(self, channel=1, amplitude=None):
        if amplitude is None:
             raise ValueError("amplitude must be provided")
        self.instrument.write(f"SOUR{channel}:VOLT {amplitude}")

    def set_offset(self, channel=1, offset=None):
        if offset is None:
             raise ValueError("offset must be provided")
        self.instrument.write(f"SOUR{channel}:VOLT:OFFS {offset}")

    def set_phase(self, channel=1, phase=None):
        if phase is None:
             raise ValueError("phase must be provided")
        self.instrument.write(f"SOUR{channel}:PHAS {phase}")

    def set_square_duty_cycle(self, channel=1, duty_cycle=None):
        if duty_cycle is None:
             raise ValueError("duty_cycle must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:SQU:DCYC {duty_cycle}")

    def set_ramp_symmetry(self, channel=1, symmetry=None):
        if symmetry is None:
             raise ValueError("symmetry must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:RAMP:SYMM {symmetry}")

    def set_pulse_width(self, channel=1, width=None):
        if width is None:
             raise ValueError("width must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:WIDT {width}")

    def set_pulse_edge_time(self, channel=1, edge_time=None):
        if edge_time is None:
             raise ValueError("edge_time must be provided")
        # 33500 supports separate rise/fall, but we define a common interface here first
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:TRAN {edge_time}")

    def set_pulse_rise_time(self, channel=1, rise_time=None):
        if rise_time is None:
             raise ValueError("rise_time must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:TRAN:LEAD {rise_time}")

    def set_pulse_fall_time(self, channel=1, fall_time=None):
        if fall_time is None:
             raise ValueError("fall_time must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:TRAN:TRA {fall_time}")
        
    def set_pulse_duty_cycle(self, channel=1, duty_cycle=None):
        if duty_cycle is None:
             raise ValueError("duty_cycle must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:DCYC {duty_cycle}")
