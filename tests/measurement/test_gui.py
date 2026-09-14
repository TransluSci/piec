"""Shared lifecycle contract for every discovered measurement GUI.

Scientific parameter validation, schemas, and physics belong to measurement tests.
"""
import pandas as pd
import pytest

from piec.measurement import RunState
from tests.support.gui_contract import discover_guis, gui

GUI_CLASSES = discover_guis()
pytestmark = pytest.mark.parametrize("gui", GUI_CLASSES, indirect=True,
                                     ids=[cls.__name__ for _, cls in GUI_CLASSES])


def start(gui):
    gui.app.run_measurement()
    assert gui.app.runner is not None, gui.errors.call_args_list
    assert gui.entered.wait(3), "GUI did not start acquisition"
    assert gui.app.runner.is_worker_alive


def finish(gui):
    gui.gate.set()
    assert gui.app.runner.join(timeout=3)
    gui.poll()


def test_runs_and_delivers_live_and_final_information(gui):
    start(gui)
    gui.poll()
    assert gui.rendered.called, "Live information never reached the renderer"
    gui.rendered.reset_mock()
    finish(gui)
    assert gui.app.runner.run_state == RunState.COMPLETED
    pd.testing.assert_frame_equal(gui.app.experiment.data, gui.expected)
    assert gui.rendered.called, "Final information never reached the renderer"
    assert gui.app.run_button.cget('state') == 'normal'
    assert not gui.errors.called


def test_stop_cancels_active_run(gui):
    start(gui)
    gui.app.stop_measurement()
    finish(gui)
    assert gui.app.runner.run_state == RunState.ABORTED
    assert gui.app.runner.can_close()


def test_errors_reach_user_and_allow_retry(gui):
    gui.scenario.failure = 'contract acquisition failure'
    start(gui)
    finish(gui)
    assert gui.app.runner.run_state == RunState.FAILED
    assert any('contract acquisition failure' in str(call) for call in gui.errors.call_args_list)
    assert gui.app.run_button.cget('state') == 'normal'


def test_second_start_does_not_replace_active_runner(gui):
    start(gui)
    runner = gui.app.runner
    gui.app.run_measurement()
    assert gui.app.runner is runner
    finish(gui)


def test_close_during_run_defers_window_destruction(gui):
    start(gui)
    gui.app.on_closing()
    gui.app.root.destroy.assert_not_called()
    finish(gui)
    gui.app.root.destroy.assert_called_once()


def test_unsafe_shutdown_blocks_new_runs_and_close(gui):
    gui.scenario.unsafe = True
    start(gui)
    finish(gui)
    runner = gui.app.runner
    assert not runner.can_close()
    gui.app.run_measurement()
    assert gui.app.runner is runner
    gui.app.on_closing()
    gui.app.root.destroy.assert_not_called()
