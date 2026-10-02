"""Single captures for the local quick-start GUI, using existing PIEC drivers."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from piec.drivers.awg.virtual_awg import VirtualAwg
from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
from piec.drivers.awg.k_81150a import Keysight81150a
from piec.drivers.oscilloscope.k_dsox3024a import KeysightDSOX3024a


@dataclass(frozen=True)
class Settings:
    mode: str = "Virtual"
    waveform: str = "SIN"
    frequency: float = 1000
    amplitude_vpp: float = 2
    awg_address: str = ""
    scope_address: str = ""

    def validate(self):
        if self.mode not in ("Virtual", "Physical"):
            raise ValueError("Choose Virtual or Physical instruments.")
        if self.waveform not in ("SIN", "SQU", "RAMP"):
            raise ValueError("Choose sine, square, or ramp.")
        if not math.isfinite(self.frequency) or not 1 <= self.frequency <= 100_000:
            raise ValueError("For this quick start, choose a frequency from 1 to 100,000 Hz.")
        if not math.isfinite(self.amplitude_vpp) or not 0 < self.amplitude_vpp <= 2:
            raise ValueError("For this quick start, choose an amplitude above 0 and at most 2 Vpp.")
        if self.mode == "Physical":
            addresses = (self.awg_address.strip(), self.scope_address.strip())
            if any(not a or a.upper().startswith(("VIRTUAL", "YOUR_")) for a in addresses):
                raise ValueError("Enter the physical VISA addresses for both instruments.")
            if addresses[0] == addresses[1]:
                raise ValueError("The AWG and scope must have different VISA addresses.")


@dataclass
class Capture:
    settings: Settings
    data: pd.DataFrame
    applied: pd.DataFrame | None


def capture(settings):
    """Capture once; disable output and close physical sessions even on failure.

    The UI uses Vpp in both modes. The existing virtual driver expects peak
    volts. Hardware follows quick_start_local.ipynb (81150A + DSOX3024A).
    """
    settings.validate()
    virtual = settings.mode == "Virtual"
    with ExitStack() as sessions:
        awg = VirtualAwg(simulation_points=1000) if virtual else Keysight81150a(
            settings.awg_address.strip(), timeout=10_000,
        )
        if not virtual:
            sessions.callback(awg.instrument.close)
        # Registered before scope construction so connection failures also turn off output.
        with ExitStack() as output:
            output.callback(awg.output, 1, on=False)
            awg.output(1, on=False)
            scope = VirtualScope() if virtual else KeysightDSOX3024a(
                settings.scope_address.strip(), timeout=10_000,
            )
            if not virtual:
                sessions.callback(scope.instrument.close)
                awg.set_source_impedance(1, 50)
                awg.set_load_impedance(1, 50)
                awg.set_trigger_source(1, "IMM")
                scope.toggle_channel(1, on=True)
                scope.set_channel_impedance(1, "50")
                scope.set_input_coupling(1, "DC")
                scope.set_probe_attenuation(1, 1)
                scope.set_vertical_scale(1, vdiv=max(0.001, settings.amplitude_vpp / 4))
                scope.set_vertical_position(1, 0)
                scope.configure_horizontal(x_range=5 / settings.frequency, x_position=0)
                scope.configure_trigger(
                    trigger_source=1, trigger_mode="EDGE", trigger_slope="POS", trigger_level=0,
                )
                scope.set_trigger_sweep("NORM")
                scope.configure_acquisition(channel=1, acquisition_mode="NORM", acquisition_points=1000)
                scope.instrument.write(":WAVeform:FORMat BYTE")
                scope.instrument.write(":WAVeform:UNSigned OFF")

            awg.configure_waveform(
                1, settings.waveform, frequency=settings.frequency,
                amplitude=settings.amplitude_vpp / 2 if virtual else settings.amplitude_vpp,
                offset=0,
            )
            awg.set_square_duty_cycle(1, 50)
            awg.set_ramp_symmetry(1, 100)
            applied = None
            if virtual:
                voltage = awg.get_waveform(1)
                applied = pd.DataFrame({
                    "Time": np.linspace(0, 1 / settings.frequency, len(voltage)),
                    "Voltage": voltage,
                })
            awg.output(1, on=True)
            if virtual:
                scope.arm()
                awg.send_software_trigger()
            else:
                awg.operation_complete()
                scope.set_acquisition()
                scope.operation_complete()
            data = scope.get_data()
    return Capture(settings, data, applied)
