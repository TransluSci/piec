"""Executable notebook and GUI display-error regressions."""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from tests.test_measurement_amr_gui import make_headless_amr_gui
from tests.test_measurement_amr_gui import gui_mod


def test_failed_close_retains_reference_and_allows_explicit_retry():
    app = make_headless_amr_gui()
    instrument = Mock()
    instrument.close.side_effect = [RuntimeError('close failed'), None]
    app._instruments = [instrument, instrument]
    app._finish_close = Mock()
    app.on_closing()
    assert app._instruments == [instrument]
    assert app._busy()
    app._finish_close.assert_not_called()
    app.on_closing()
    assert not app._instruments
    assert instrument.close.call_count == 2
    app._finish_close.assert_called_once()


def test_stepper_query_failure_still_closes_opened_connection():
    app = make_headless_amr_gui()
    instrument = Mock()
    instrument.idn.side_effect = RuntimeError('query failed')
    with patch.object(gui_mod, 'VirtualStepper', return_value=instrument):
        app.test_stepper()
    instrument.close.assert_called_once()
    assert not app._instruments


def test_terminal_plot_failure_cannot_block_connection_cleanup_or_polling(capsys):
    app = make_headless_amr_gui()
    with patch('time.sleep', return_value=None):
        app.run_measurement()
        assert app.runner.join(5)
    app._plot_data = Mock(side_effect=RuntimeError('renderer failed'))
    app._poll_runner()
    assert 'renderer failed' in capsys.readouterr().out
    assert not app._awaiting_terminal
    assert not app._instruments
    assert app._current_plot_data is not None
    app.root.after.assert_called()


def test_empty_plot_clears_previous_run_display():
    app = make_headless_amr_gui()
    app._render_plot(pd.DataFrame())
    app.ax.clear.assert_called_once()
    app.canvas.draw_idle.assert_called_once()


def test_notebook_setup_run_and_plot_cells_execute_in_order(tmp_path):
    notebook = json.loads((Path(__file__).resolve().parents[1] /
        'Measurements/AMR/AMR_testing.ipynb').read_text(encoding='utf-8'))
    namespace = {}
    # Skip only the optional VISA resource-discovery cell. Use a short virtual
    # sweep and temporary output directory for the actual acquisition cells.
    with patch('time.sleep', return_value=None), patch('matplotlib.pyplot.show'):
        for index, cell in enumerate(notebook['cells']):
            if cell['cell_type'] != 'code' or index == 5:
                continue
            exec(compile(''.join(cell['source']), f'AMR_testing.ipynb:cell{index}', 'exec'), namespace)
            if index == 11:
                namespace.update(path=str(tmp_path), measure_time=0, angle_step=45, total_angle=90)
    assert len(namespace['amr_df']) == 3
    assert namespace['experiment'].filename is not None
    namespace['lockin'] = Mock()
    with pytest.raises(TypeError, match='entirely virtual'):
        namespace['simulation_excitation_shutdown']()
    namespace['plt'].close('all')
