# Command tests are available; physical verification remains pending.
import re

from ..scpi import Scpi
from .awg import Awg
from ._scpi_trigger import ScpiTriggerMixin

class RigolDG1000(ScpiTriggerMixin, Scpi, Awg):
    """
    Driver for the Rigol DG1000 Series Arbitrary Waveform Generators
    and DG1000Z series.

    Trigger source, external edge and triggered/gated burst configuration are
    implemented using the model's programming reference. See
    docs/awg_trigger_support.md for prerequisites and per-model limitations.
    """
    
    # "RIGOL TECHNOLOGIES,DG1022,..."
    AUTODETECT_ID = "DG1"
    
    channel = [1, 2]

    def __init__(self, address, check_params=False, verbose=False, *, protocol=None, **kwargs):
        """Select the legacy DG1000 or DG1000Z dialect.

        By default the first operation queries *IDN? and caches the dialect.
        An explicit protocol ('dg1000' or 'dg1000z') avoids that query when the
        caller already knows the model. No outputs are changed by identification.
        """
        if protocol not in (None, 'dg1000', 'dg1000z'):
            raise ValueError("protocol must be 'dg1000', 'dg1000z', or None")
        self._rigol_protocol = protocol
        super().__init__(address, check_params=check_params, verbose=verbose, **kwargs)

    def _resolve_protocol(self):
        protocol = self.__dict__.get('_rigol_protocol')
        if protocol is None:
            identity = self.instrument.query('*IDN?')
            fields = identity.strip().upper().split(',') if isinstance(identity, str) else []
            model = fields[1].strip() if len(fields) >= 2 else ''
            if re.fullmatch(r'DG1\d{3}Z', model):
                protocol = 'dg1000z'
            elif model in ('DG1012', 'DG1022', 'DG1022A', 'DG1022U'):
                protocol = 'dg1000'
            else:
                raise ValueError('Cannot identify DG1000/DG1000Z dialect; supply a verified protocol')
            self._rigol_protocol = protocol
        self._trigger_source_map = {
            'imm': 'INT' if protocol == 'dg1000z' else 'IMM',
            'int': 'INT' if protocol == 'dg1000z' else 'IMM',
            'ext': 'EXT', 'man': 'BUS', 'bus': 'BUS',
        }
        return protocol

    def _validate_trigger_channel(self, channel):
        super()._validate_trigger_channel(channel)
        if self._resolve_protocol() == 'dg1000' and channel != 1:
            raise NotImplementedError('Legacy DG1000 burst/sweep triggering is available on channel 1 only')

    def _trigger_prefix(self, channel, trigger_function):
        return f'TRIG{channel}' if self._resolve_protocol() == 'dg1000z' else 'TRIG'

    def _burst_prefix(self, channel):
        return f'SOUR{channel}:BURS' if self._resolve_protocol() == 'dg1000z' else 'BURS'

    def output_trigger(self):
        """Issue a DG1000Z bus trigger; legacy software initiation is unverified.

        The older programming guide documents BUS source but no launch command.
        Do not guess that its firmware implements the DG1000Z *TRG command.
        Legacy callers can use a front-panel or external trigger.
        """
        if self._resolve_protocol() != 'dg1000z':
            raise NotImplementedError('Legacy DG1000 software trigger command is not verified; use external triggering')
        super().output_trigger()

    def _wave_command(self, channel, mnemonic):
        # General outputs still support both channels on legacy models.
        ScpiTriggerMixin._validate_trigger_channel(self, channel)
        if self._resolve_protocol() == 'dg1000z':
            return f'OUTP{channel}' if mnemonic == 'OUTP' else f'SOUR{channel}:{mnemonic}'
        # Legacy DG1000 uses CH2 suffixes rather than SOUR2 prefixes.
        if mnemonic.startswith('FUNC:PULS:'):
            mnemonic = mnemonic.replace('FUNC:PULS:', 'PULS:', 1)
        return mnemonic + (':CH2' if channel == 2 else '')
    
    waveform = ['SIN', 'SQU', 'RAMP', 'PULS', 'NOIS', 'DC', 'USER']
    
    # Frequency: 1uHz to 25MHz (DG1022Z) or up to 60MHz (DG1062Z)
    # Using 60MHz to support the top end; instrument will error if out of range for specific model.
    frequency = {
        'waveform': {
            'SIN': (1e-6, 60e6),
            'SQU': (1e-6, 25e6),
            'RAMP': (1e-6, 500e3), # DG1000Z ramp max is usually lower
            'PULS': (1e-6, 25e6), 
            'NOIS': (1e-6, 25e6), # Bandwidth
            'DC': None,
            'USER': (1e-6, 20e6)
        }
    }
    
    # Amplitude: 1mVpp to 10Vpp (50 ohm)
    amplitude = (0.001, 10.0)
    
    # Offset: +/- 5V (50 ohm)
    offset = (-5.0, 5.0)
    
    phase = (0.0, 360.0)
    
    # Duty Cycle (Square): 1% to 99% (limited by freq)
    duty_cycle = (1.0, 99.0)
    
    # Symmetry (Ramp): 0% to 100%
    symmetry = (0.0, 100.0)
    
    # Pulse Width
    pulse_width = (16e-9, 1000.0)
    




    def output(self, channel=1, on=True):
        state = "ON" if on else "OFF"
        self.instrument.write(f"{self._wave_command(channel, 'OUTP')} {state}")

    def set_waveform(self, channel=1, waveform=None):
        if waveform is None:
             raise ValueError("waveform must be provided")
        # FUNC changes shape without APPLy's frequency/amplitude side effects.
        self.instrument.write(f"{self._wave_command(channel, 'FUNC')} {waveform}")

    def set_frequency(self, channel=1, frequency=None):
        if frequency is None:
             raise ValueError("frequency must be provided")
        self.instrument.write(f"{self._wave_command(channel, 'FREQ')} {frequency}")

    def set_amplitude(self, channel=1, amplitude=None):
        if amplitude is None:
             raise ValueError("amplitude must be provided")
        self.instrument.write(f"{self._wave_command(channel, 'VOLT')} {amplitude}")

    def set_offset(self, channel=1, offset=None):
        if offset is None:
             raise ValueError("offset must be provided")
        self.instrument.write(f"{self._wave_command(channel, 'VOLT:OFFS')} {offset}")

    def set_phase(self, channel=1, phase=None):
        if phase is None:
             raise ValueError("phase must be provided")
        self.instrument.write(f"{self._wave_command(channel, 'PHAS')} {phase}")

    def set_square_duty_cycle(self, channel=1, duty_cycle=None):
        if duty_cycle is None:
             raise ValueError("duty_cycle must be provided")
        self.instrument.write(f"{self._wave_command(channel, 'FUNC:SQU:DCYC')} {duty_cycle}")

    def set_ramp_symmetry(self, channel=1, symmetry=None):
        if symmetry is None:
             raise ValueError("symmetry must be provided")
        self.instrument.write(f"{self._wave_command(channel, 'FUNC:RAMP:SYMM')} {symmetry}")

    def set_pulse_width(self, channel=1, width=None):
        if width is None:
             raise ValueError("width must be provided")
        self.instrument.write(f"{self._wave_command(channel, 'FUNC:PULS:WIDT')} {width}")
        
    def set_pulse_duty_cycle(self, channel=1, duty_cycle=None):
        if duty_cycle is None:
             raise ValueError("duty_cycle must be provided")
        self.instrument.write(f"{self._wave_command(channel, 'FUNC:PULS:DCYC')} {duty_cycle}")
    
    # The Z reference documents separate leading/trailing transition commands.
    def set_pulse_edge_time(self, channel=1, edge_time=None):
        if edge_time is None:
             raise ValueError("edge_time must be provided")
        ScpiTriggerMixin._validate_trigger_channel(self, channel)
        if self._resolve_protocol() != 'dg1000z':
            raise NotImplementedError('Legacy DG1000 programmable pulse transition is not documented')
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:TRAN:BOTH {edge_time}")

    def set_pulse_rise_time(self, channel=1, rise_time=None):
        if rise_time is None:
             raise ValueError("rise_time must be provided")
        ScpiTriggerMixin._validate_trigger_channel(self, channel)
        if self._resolve_protocol() != 'dg1000z':
            raise NotImplementedError('Legacy DG1000 programmable pulse rise time is not documented')
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:TRAN:LEAD {rise_time}")

    def set_pulse_fall_time(self, channel=1, fall_time=None):
        if fall_time is None:
             raise ValueError("fall_time must be provided")
        ScpiTriggerMixin._validate_trigger_channel(self, channel)
        if self._resolve_protocol() != 'dg1000z':
            raise NotImplementedError('Legacy DG1000 programmable pulse fall time is not documented')
        self.instrument.write(f"SOUR{channel}:FUNC:PULS:TRAN:TRA {fall_time}")
