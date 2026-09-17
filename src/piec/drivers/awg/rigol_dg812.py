# This driver has not been tested yet
from ..scpi import Scpi
from .awg import Awg

class RigolDG812(Scpi, Awg):
    """
    Driver for the Rigol DG812 Arbitrary Waveform Generator (DG800 Series).

    The DG800 series spans several bandwidth/channel-count tiers (DG811/821/831
    are single-channel, DG812/822/832 are dual-channel, with 25/40/60 MHz
    bandwidth respectively). AUTODETECT_ID is scoped to "DG812" specifically
    rather than the whole "DG8" family so autodetect doesn't misattribute a
    different tier's channel count or bandwidth to this driver.
    """

    # "RIGOL TECHNOLOGIES,DG812,..."
    AUTODETECT_ID = "DG812"

    channel = [1, 2]

    # DG800 uses 'ARB' rather than the older DG1000/DG3000 'USER' keyword for
    # arbitrary waveforms; mapped internally in set_waveform/set_arb_waveform.
    waveform = ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER']

    _WAVEFORM_MAP = {'USER': 'ARB'}

    # Frequency ranges per the DG812 (25 MHz tier) datasheet.
    # Verify against the official DG800 Programming Guide before relying on
    # these for anything safety-critical.
    frequency = {
        'waveform': {
            'SIN': (1e-6, 25e6),
            'SQU': (1e-6, 25e6),
            'RAMP': (1e-6, 1e6),
            'PULS': (1e-6, 15e6),
            'NOIS': (1e-6, 25e6),  # Bandwidth
            'DC': None,
            'USER': (1e-6, 12e6),
        }
    }

    # Amplitude: 1mVpp to 10Vpp (50 ohm)
    amplitude = (0.001, 10.0)

    # Offset: +/- 5V (50 ohm)
    offset = (-5.0, 5.0)

    phase = (0.0, 360.0)

    # Duty Cycle (Square): frequency-dependent on real hardware; this is the
    # widest documented range.
    duty_cycle = (1.0, 99.0)

    # Symmetry (Ramp): 0% to 100%
    symmetry = (0.0, 100.0)

    # Pulse Width
    pulse_width = (16e-9, 1000.0)

    def output(self, channel=1, on=True):
        state = "ON" if on else "OFF"
        self.instrument.write(f"OUTP{channel} {state}")

    def set_waveform(self, channel=1, waveform=None):
        if waveform is None:
            raise ValueError("waveform must be provided")
        hw_waveform = self._WAVEFORM_MAP.get(waveform.upper(), waveform)
        self.instrument.write(f"SOUR{channel}:FUNC {hw_waveform}")

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

    def set_pulse_width(self, channel=1, pulse_width=None):
        if pulse_width is None:
            raise ValueError("pulse_width must be provided")
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:WIDT {pulse_width}")

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
