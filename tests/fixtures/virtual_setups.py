"""Owned simulation setups for measurement numerical and lifecycle fixtures."""
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.simulation import ResistorLoad, VirtualBench
from piec.analysis.field_calibration import FieldCalibration
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.simulation import HystereticMagneticMaterial


class LinearFieldFixture(HystereticMagneticMaterial):
    """Preserve the original linear MOKE golden's field-to-voltage fixture law."""

    @property
    def magnetization(self):
        return self.current_field / 500.0


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
