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
