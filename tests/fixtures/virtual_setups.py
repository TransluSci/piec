"""Owned simulation setups for measurement numerical and lifecycle fixtures."""
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.simulation import ResistorLoad, VirtualBench


def iv_bench(resistance=100.0):
    bench = VirtualBench(seed=42)
    source = bench.add_instrument('source', VirtualSourcemeter)
    bench.add_model('load', ResistorLoad, resistance=resistance)
    bench.connect_load('electrical', 'source', 'load')
    return bench, source
