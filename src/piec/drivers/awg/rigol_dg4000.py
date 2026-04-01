# This driver has not been tested yet
from ..scpi import Scpi
from .awg import Awg

class RigolDG4000(Scpi, Awg):
    """
    Driver for the Rigol DG4000 Series Arbitrary Waveform Generators.
    e.g. DG4062, DG4102, DG4162, DG4202
    """
    
    # "RIGOL TECHNOLOGIES,DG4162,..."
    AUTODETECT_ID = "DG4"
    
    channel = [1, 2]
    
    waveform = ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER', 'HARM']
    
    # Frequency: up to 200MHz (DG4202)
    # Using 160MHz as a high-end representative
    frequency = {
        'waveform': {
            'SIN': (1e-6, 160e6),
            'SQU': (1e-6, 50e6),
            'RAMP': (1e-6, 4e6),
            'PULS': (1e-6, 40e6),
            'NOIS': (1e-6, 120e6), # Bandwidth
            'DC': None,
            'USER': (1e-6, 40e6),
            'HARM': (1e-6, 80e6)
        }
    }
    
    # Amplitude: 1mVpp to 10Vpp (50 ohm)
    amplitude = (0.001, 10.0)
    
    # Offset: +/- 5V (50 ohm)
    offset = (-5.0, 5.0)
    
    phase = (0.0, 360.0)
    
    # Duty Cycle (Square)
    duty_cycle = (1.0, 99.0)
    
    # Symmetry (Ramp): 0% to 100%
    symmetry = (0.0, 100.0)
    
    # Pulse Width: 12ns min
    pulse_width = (12e-9, 1000000.0)
    
    # Edges: 2.5ns to 1us
    edge_time = (2.5e-9, 1.0e-6)
    




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
        
    def set_pulse_duty_cycle(self, channel=1, duty_cycle=None):
        if duty_cycle is None:
             raise ValueError("duty_cycle must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:DCYC {duty_cycle}")

    def set_pulse_rise_time(self, channel=1, rise_time=None):
        if rise_time is None:
             raise ValueError("rise_time must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:TRAN:LEAD {rise_time}")

    def set_pulse_fall_time(self, channel=1, fall_time=None):
        if fall_time is None:
             raise ValueError("fall_time must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:TRAN:TRA {fall_time}")
         
    def set_pulse_edge_time(self, channel=1, edge_time=None):
        if edge_time is None:
             raise ValueError("edge_time must be provided")
        # Set both
        self.set_pulse_rise_time(channel, edge_time)
        self.set_pulse_fall_time(channel, edge_time)
