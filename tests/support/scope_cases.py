"""Waveform fixtures: scripted ADC values and independent expected physical units."""
from dataclasses import dataclass
import struct
from unittest.mock import Mock

from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.drivers.oscilloscope.tektronix_tds2000 import TektronixTDS2000
from piec.drivers.oscilloscope.rigol_ds1000z import RigolDS1000Z
from piec.drivers.oscilloscope.k_dsox3024a import KeysightDSOX3024a
from piec.drivers.oscilloscope.agilent_dsox5000 import AgilentDSOX5000
from piec.drivers.oscilloscope.lecroy_sda6020 import LeCroySDA6020
from piec.drivers.oscilloscope.tektronix_tds6604 import TDS6604
from piec.drivers.emulators.daq_to_oscilloscope import DaqAsOscilloscope
from piec.drivers.daq.virtual_daq import VirtualDaq
from tests.support.transports import create_test_driver


@dataclass(frozen=True)
class ScopeCase:
    cls: type
    responses: dict
    columns: tuple = ("Time", "Voltage")
    time: tuple = (-.25, 0., .25)
    voltage: tuple = (1., 2., 4.)

    def make(self):
        if self.cls is VirtualScope:
            return self.cls(waveform_hook=lambda: {"time": self.time, "voltage": self.voltage})
        if self.cls is DaqAsOscilloscope:
            daq = VirtualDaq()
            daq.read_AI_scan = Mock(return_value=list(self.voltage))
            scope = self.cls(daq)
            scope.set_acquisition_points(3)
            scope.set_horizontal_scale(tdiv=.075)
            return scope
        return create_test_driver(self.cls, responses=self.responses, strict=True)


# Independent example: ADC [0, 2, 6], gain .5 V/count, origin 1 V;
# three samples .25 s apart starting at -.25 s. Nonzero origins catch
# parsers that omit offsets; non-unit gain catches unscaled ADC returns.
TEK_RESPONSES = {"WFMPRE:YMULT?": .5, "WFMPRE:YOFF?": 0,
                 "WFMPRE:YZERO?": 1., "WFMPRE:XINCR?": .25,
                 "WFMPRE:XZERO?": -.25, "CURVe?": [0, 2, 6]}
PREAMBLE = "0,0,3,1,0.25,-0.25,0,0.5,1,0"
descriptor = bytearray(346)
struct.pack_into("<f", descriptor, 156, .5)
struct.pack_into("<f", descriptor, 160, -1.)
struct.pack_into("<f", descriptor, 176, .25)
struct.pack_into("<d", descriptor, 180, -.25)

SCOPE_CASES = [
    ScopeCase(VirtualScope, {}),
    ScopeCase(TektronixTDS2000, TEK_RESPONSES),
    ScopeCase(RigolDS1000Z, {":WAVeform:PREamble?": PREAMBLE, ":WAVeform:DATA?": [0, 2, 6]}),
    ScopeCase(KeysightDSOX3024a, {":WAVeform:PREamble?": PREAMBLE, "WAVeform:DATA?": [0, 2, 6]}),
    ScopeCase(AgilentDSOX5000, {":WAVeform:PREamble?": PREAMBLE, "WAVeform:DATA?": [0, 2, 6]}),
    ScopeCase(LeCroySDA6020, {"C1:WF? DESC": bytes(descriptor), "C1:WF? DAT1": [0, 2, 6]}),
    ScopeCase(TDS6604, dict(TEK_RESPONSES, **{"HORizontal:RECOrdlength?": 3}), ("Time", "Voltage_CH1")),
    ScopeCase(DaqAsOscilloscope, {}, ("Time", "Channel 1"), (0., .25, .5)),
]
