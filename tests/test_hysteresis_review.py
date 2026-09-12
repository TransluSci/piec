from pathlib import Path
from unittest.mock import Mock
import importlib.util
import numpy as np
import pytest
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
from piec.measurement import HysteresisLoop
from tests.fixtures.virtual_setups import fe_bench
from piec.measurement.contracts import SafetyStatus, RunState

ROOT = Path(__file__).resolve().parents[1]

def measurement(tmp_path, **kwargs):
    return HysteresisLoop(*fe_bench()[1:], output_dir=tmp_path, **kwargs)

@pytest.mark.parametrize('failure_index', [1, 2, 3])
def test_plot_failure_cleans_all_pngs_and_figures(tmp_path, monkeypatch, failure_index):
    m = measurement(tmp_path)
    original = Figure.savefig
    count = 0
    def failing_save(fig, *args, **kwargs):
        nonlocal count
        count += 1
        if count == failure_index:
            raise OSError('plot write failed')
        return original(fig, *args, **kwargs)
    figures_before = plt.get_fignums()
    monkeypatch.setattr(Figure, 'savefig', failing_save)
    with pytest.raises(OSError, match='plot write failed'):
        m.run_experiment(save=True)
    assert not list(tmp_path.glob('*.png'))
    assert plt.get_fignums() == figures_before
    assert m.recoverable_staging_paths
    assert all(Path(p).is_file() for p in m.recoverable_staging_paths)

def test_dc_offset_includes_idle_and_does_not_alter_current(tmp_path):
    from piec.analysis.hysteresis import process_hysteresis
    m = measurement(tmp_path, offset=2)
    result = m.run_experiment(save=False)
    zero = process_hysteresis(m.raw_data, m.measurement_metadata, offset=0)
    np.testing.assert_allclose(result.applied_voltage, zero.data.applied_voltage + 2)
    np.testing.assert_allclose(result.current, zero.data.current)
    assert m.measurement_metadata['offset'] == 2

def app(tmp_path):
    spec = importlib.util.spec_from_file_location('fe_gui_review', ROOT/'Measurements/Ferroelectric Testing/FE_testing_GUI.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    gui = mod.FEMeasurementApp.__new__(mod.FEMeasurementApp)
    gui.root = Mock(); gui.run_button = Mock(); gui.stop_button = Mock(); gui.status_label = Mock()
    gui.timeshift_entry = Mock(); gui.runner = None; gui._awaiting_terminal = False
    gui._terminal_event = None; gui._closing = False; gui._poll_id = None
    gui._plot_frame = None; gui._plot_units = {}; gui.experiment = None
    gui.measurement_type = Mock(get=Mock(return_value='HysteresisLoop'))
    gui.x_axis = Mock(get=Mock(return_value='applied voltage (V)'))
    gui.y_axis = Mock(get=Mock(return_value='current (A)'))
    gui.ax = Mock(); gui.canvas = Mock()
    m = measurement(tmp_path, save_plots=False)
    m.awg.close = Mock(); m.osc.close = Mock()
    gui._instruments = []
    def create():
        gui.experiment = m; gui._instruments = [m.awg,m.osc]
    gui._create_experiment = create
    return gui,mod,m

def test_gui_completion_uses_memory_and_releases_instruments(tmp_path, monkeypatch):
    gui,mod,m = app(tmp_path)
    monkeypatch.setattr(mod, 'standard_csv_to_metadata_and_data', Mock(side_effect=AssertionError('disk read')))
    gui.run_measurement(); assert gui.runner.join(timeout=5)
    gui._poll_events()
    assert gui.runner.run_state == RunState.COMPLETED
    assert len(gui._plot_frame) == len(m.data)
    gui.ax.plot.assert_called()
    m.awg.close.assert_called_once(); m.osc.close.assert_called_once()

def test_gui_stop_and_deferred_close(tmp_path):
    import threading
    gui,mod,m = app(tmp_path)
    entered = threading.Event(); release = threading.Event()
    def arm():
        entered.set(); assert release.wait(5)
    m.osc.arm = arm
    gui._finish_close = Mock()
    gui.run_measurement(); assert entered.wait(5)
    try:
        gui.on_closing()
        gui._finish_close.assert_not_called(); m.awg.close.assert_not_called()
        gui._create_experiment = Mock()
        gui.run_measurement(); gui._create_experiment.assert_not_called()
    finally:
        release.set()
    assert gui.runner.join(timeout=5)
    gui._poll_events()
    assert gui.runner.run_state == RunState.ABORTED
    gui._finish_close.assert_called_once(); m.awg.close.assert_called_once()

def test_gui_unsafe_retains_connections_until_retry(tmp_path, monkeypatch):
    gui,mod,m = app(tmp_path)
    monkeypatch.setattr(mod.messagebox, 'showerror', Mock())
    original = m._safe_shutdown
    m._safe_shutdown = Mock(side_effect=OSError('shutdown failed'))
    gui.run_measurement(); assert gui.runner.join(timeout=5)
    gui._poll_events()
    assert gui.runner.safety_status == SafetyStatus.UNSAFE
    gui._finish_close = Mock(); gui.on_closing()
    m.awg.close.assert_not_called(); gui._finish_close.assert_not_called()
    m._safe_shutdown = original; m.safe_shutdown()
    gui._poll_events()
    m.awg.close.assert_called_once(); gui._finish_close.assert_called_once()
