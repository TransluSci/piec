"""Owned simulation setups for measurement numerical and lifecycle fixtures."""
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.simulation import ResistorLoad, VirtualBench
from piec.analysis.field_calibration import FieldCalibration
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.simulation import HystereticMagneticMaterial
from piec.simulation import MagneticSample


class LinearFieldFixture(HystereticMagneticMaterial):
    """Preserve the original linear MOKE golden's field-to-voltage fixture law."""

    @property
    def magnetization(self):
        return self.current_field / 500.0


class AmrGoldenMaterial(MagneticSample):
    """Explicit noiseless reference with a declared 0.1 quadrature/in-phase ratio."""

    def get_voltage_response(self, excitation_current, angle=None, field=None, time=None):
        import math
        theta = self.current_angle if angle is None else angle
        if time is not None:
            self.timebase.set_time(time)
        resistance = self.r_base * (1. + self.amr_ratio * math.cos(math.radians(theta)) ** 2)
        x = resistance * excitation_current
        return x, .1 * x


def amr_bench(resistance=100., delta=2., field_scale=10000., golden=False):
    from piec.drivers.dc_calibrator.virtual_calibrator import VirtualCalibrator
    from piec.drivers.lockin.virtual_lockin import VirtualLockin
    from piec.drivers.stepper_motor.virtual_stepper import VirtualStepper
    bench = VirtualBench(seed=42)
    material = bench.add_model('material', AmrGoldenMaterial if golden else MagneticSample,
                               r_base=resistance, amr_ratio=delta/resistance)
    cal = bench.add_instrument('calibrator', VirtualCalibrator)
    dmm = bench.add_instrument('dmm', VirtualDMM)
    stepper = bench.add_instrument('arduino', VirtualStepper)
    lockin = bench.add_instrument('lockin', VirtualLockin, excitation_current=1e-6)

    def apply_field(voltage):
        material.current_field = voltage * field_scale

    def apply_angle(angle):
        material.current_angle = angle

    def field_voltage():
        if cal.state['output_on'] is None:
            raise RuntimeError('unconfirmed calibrator output')
        return material.current_field / field_scale

    def transport(excitation_current):
        if stepper.state['moving'] is None or cal.state['output_on'] is None:
            raise RuntimeError('unconfirmed AMR plant state')
        return material.get_voltage_response(excitation_current, time=bench.timebase.current_time)

    cal.output_hook = apply_field
    stepper.angle_hook = apply_angle
    dmm.voltage_reader = field_voltage
    lockin.xy_reader = transport
    return bench, dict(calibrator=cal, dmm=dmm, arduino=stepper, lockin=lockin)


def moke_bench(linear=False, output_unit='V'):
    bench = VirtualBench(seed=42)
    source = bench.add_instrument('source', VirtualSourcemeter)
    detector = bench.add_instrument('detector', VirtualDMM)
    bench.add_model('load', ResistorLoad, resistance=1000. if output_unit == 'V' else 1.)
    bench.add_model('material', LinearFieldFixture if linear else HystereticMagneticMaterial)
    # Independent plant law, not the calibration being tested by the measurement.
    plant = FieldCalibration([(-5., -500.), (5., 500.)], output_unit=output_unit)
    bench.connect_moke('optics', 'source', 'load', 'material', 'detector', plant,
                       optical_gain=.2 if linear else .02)
    return bench, source, detector


def iv_bench(resistance=100.0):
    bench = VirtualBench(seed=42)
    source = bench.add_instrument('source', VirtualSourcemeter)
    bench.add_model('load', ResistorLoad, resistance=resistance)
    bench.connect_load('electrical', 'source', 'load')
    return bench, source


def fe_bench(points=50):
    """Explicit FE plant and preparation waveform matching the reference fixtures."""
    import json
    from pathlib import Path
    import numpy as np
    from piec.drivers.awg.virtual_awg import VirtualAwg
    from piec.drivers.oscilloscope.virtual_oscilloscope import VirtualScope
    from piec.simulation import Ferroelectric

    bench = VirtualBench(seed=42)
    material_parameters = json.loads((Path(__file__).parent / 'fe_material.json').read_text(encoding='utf-8'))
    material = bench.add_model('material', Ferroelectric, material_dict=material_parameters)
    material.prep_points = 20
    awg = bench.add_instrument('awg', VirtualAwg, simulation_points=points)
    scope = bench.add_instrument('scope', VirtualScope, simulation_points=points)

    def capture(v, t):
        voltage = np.concatenate([np.zeros(material.prep_points), v])
        time = np.linspace(0., (t[-1] - t[0]) * len(voltage) / len(v), len(voltage))
        material.apply_waveform(voltage, time)
        # The waveform contract integrates its local duration. Coordinate the
        # bench clock explicitly after this fixture's synchronous acquisition.
        bench.advance(time[-1] - time[0])

    awg.waveform_hook = capture
    scope.waveform_hook = lambda: material.get_voltage_response()
    return bench, awg, scope
