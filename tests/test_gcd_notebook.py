"""Run the notebook's default virtual and scripted physical configurations."""

import importlib
import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pytest

from piec.drivers.virtual_instrument import VirtualInstrument
from tests.support.gcd import scripted_smu


@pytest.mark.parametrize('virtual', [True, False], ids=['virtual', 'scripted-physical'])
def test_notebook_uses_one_protocol_with_conditional_simulation(tmp_path, monkeypatch, virtual):
    from piec.drivers import instrument

    def forbidden(*args, **kwargs):
        pytest.fail('Notebook tests must never open real hardware')

    monkeypatch.setattr(instrument, 'PiecManager', forbidden)
    module = importlib.import_module('piec.drivers.sourcemeter.keithley2400')
    real_driver = module.Keithley2400
    physical_address = 'GPIB0::24::INSTR'
    addresses = []

    def connect(address):
        addresses.append(address)
        return real_driver('VIRTUAL') if virtual else scripted_smu(immediate_cutoffs=True)

    monkeypatch.setattr(module, 'Keithley2400', connect)
    monkeypatch.setattr(VirtualInstrument, '_shared_fe_sample', None)
    monkeypatch.setattr(VirtualInstrument, '_shared_mag_sample', None)
    notebook_path = Path(__file__).resolve().parents[1] / 'Measurements/GCD/GCD_testing.ipynb'
    notebook = json.loads(notebook_path.read_text(encoding='utf-8'))
    namespace = {}
    original_backend = matplotlib.get_backend()
    plt.switch_backend('Agg')
    monkeypatch.setattr(plt, 'show', lambda: None)
    try:
        for index, cell in enumerate(notebook['cells']):
            if cell['cell_type'] != 'code':
                continue
            source = ''.join(cell['source'])
            if not virtual:
                source = source.replace('smu_address = "VIRTUAL"', f'smu_address = "{physical_address}"')
            exec(compile(source, f'GCD_testing.ipynb:cell-{index}', 'exec'), namespace)
            if '### VARIABLE DEFINITIONS ###' in source:
                namespace.update(path=tmp_path, n_cycles=1)
                if not virtual:
                    namespace.update(capacity_ah='ignored', initial_soc='ignored')
        assert addresses == ['VIRTUAL' if virtual else physical_address]
        experiment = namespace['experiment']
        assert experiment.status == 'complete'
        assert experiment.completed_cycles == 1
        assert experiment.virtual_time is virtual
        assert Path(experiment.filename).exists()
        assert Path(experiment.plot_filename).exists()
        assert ('simulation_sample' in experiment.metadata) is virtual
        smu = namespace['smu']
        if virtual:
            assert VirtualInstrument._shared_fe_sample is namespace['original_sample']
            assert smu.state['off_mode'] == 'HIMP'
            assert not smu.state['output_on']
        else:
            assert 'sample' not in smu.__dict__
            assert smu.instrument.off_mode == 'HIMP'
            assert not smu.instrument.output_on
            assert '*RST' not in smu.instrument.writes
    finally:
        plt.close('all')
        plt.switch_backend(original_backend)
