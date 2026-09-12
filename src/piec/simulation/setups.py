"""Explicit example-plant wiring for interactive virtual measurement consumers.

Models belong to each returned plant, never to VirtualInstrument shared state.
Instrument creation/closing remains the caller's responsibility. These helpers
are for entirely virtual setups; physical interfaces must use their actual wiring.
"""
import json
from pathlib import Path
import numpy as np


def example_fe_parameters():
    """Return a fresh illustrative FE parameter dictionary (not a calibration)."""
    return json.loads(Path(__file__).with_name('example_fe_material.json').read_text(encoding='utf-8'))


def connect_fe_plant(awg, scope, material_parameters=None, seed=None, prep_points=20):
    """Attach one independent FE plant; preserve the example preparation grid."""
    from copy import deepcopy
    from piec.drivers.awg.virtual_awg import VirtualAwg
    from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
    from .fe_material import Ferroelectric
    if not isinstance(awg, VirtualAwg) or not isinstance(scope, VirtualScope):
        raise TypeError('FE plant wiring requires a virtual AWG and scope')
    if isinstance(prep_points, bool) or not isinstance(prep_points, int) or prep_points < 0:
        raise ValueError('prep_points must be a nonnegative integer')
    parameters = example_fe_parameters() if material_parameters is None else deepcopy(material_parameters)
    material = Ferroelectric(parameters, seed=seed)
    material.prep_points = prep_points

    def apply(v, t):
        voltage = np.concatenate([np.zeros(prep_points), v])
        time = np.linspace(0., (t[-1] - t[0]) * len(voltage) / len(v), len(voltage))
        material.apply_waveform(voltage, time)

    awg.waveform_hook = apply
    scope.waveform_hook = material.get_voltage_response
    return material


def connect_amr_plant(calibrator, dmm, stepper, lockin, *, field_scale=10000., seed=None):
    """Wire effective field, actual angle and declared lock-in current to a sample.

    The default sample is resistive (Y=0), with seeded model noise. No sensitivity,
    range, reference amplitude or other front-panel settings are changed.
    """
    from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
    from piec.drivers.dmm.virtual_dmm import VirtualDMM
    from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
    from piec.drivers.lockin.virtual_lockin import VirtualLockin
    from .magnetic_material import MagneticSample
    pairs = ((calibrator, VirtualCalibrator), (dmm, VirtualDMM),
             (stepper, VirtualStepper), (lockin, VirtualLockin))
    if not all(isinstance(obj, kind) for obj, kind in pairs):
        raise TypeError('AMR plant wiring requires four virtual instruments')
    if not np.isfinite(field_scale) or field_scale <= 0:
        raise ValueError('field_scale must be positive and finite')
    if calibrator.state['output_on'] is None:
        raise ValueError('cannot connect an unconfirmed calibrator output')
    material = MagneticSample(seed=seed)
    material.current_angle = stepper.get_angle()

    def field(voltage, mode, output_on):
        if output_on and mode != 'voltage':
            raise ValueError('this field calibration requires voltage output')
        material.current_field = voltage * field_scale

    def angle(angle):
        material.current_angle = angle

    def check_state():
        if calibrator.state['output_on'] is None or stepper.state['moving'] is None:
            raise RuntimeError('AMR plant state is unconfirmed')

    def read_field():
        check_state()
        return material.current_field / field_scale

    def read_xy(excitation_current):
        check_state()
        return material.get_voltage_response(excitation_current)

    state = calibrator.state
    field(state['voltage'] if state['output_on'] else 0., state['mode'], state['output_on'])
    calibrator.output_hook = field
    stepper.angle_hook = angle
    dmm.voltage_reader = read_field
    lockin.xy_reader = read_xy
    return material
