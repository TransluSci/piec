"""MOKE ownership, repeat-run, snapshot and GUI regression coverage."""
import threading
from unittest.mock import Mock

import pytest

from piec.measurement import BaseMeasurement, ConcurrentRunError, RunState, SafetyStatus
from piec.measurement.moke import MokeMeasurement
from tests.test_measurement_moke import create_mock_setup
from tests.test_moke_gui import _load_gui_module


def measurement(**kwargs):
    source, dmm, calibration = create_mock_setup()
    options = dict(calibration=calibration, output_values=[-1, 0, 1, 0, -1],
                   compliance=.01, max_output_step=.5, dwell_time=0, ramp_delay=0,
                   n_cycles=2, raw_window_points=3)
    options.update(kwargs)
    return MokeMeasurement(source, dmm, **options)


def test_raw_data_complete_and_snapshots_keep_actual_identity():
    run = measurement()
    assert run.snapshot().safety != SafetyStatus.SAFE
    run.run_experiment(save=False)
    snapshot = run.snapshot()
    assert len(run.raw_data) == 10
    assert len(snapshot.raw) == 3
    assert snapshot.run_id == run.last_run_record.run_id
    assert snapshot.generation == run.last_run_record.generation
    assert snapshot.state == RunState.COMPLETED
    assert snapshot.safety == run.safety_status
    assert MokeMeasurement.snapshot is BaseMeasurement.snapshot
    assert MokeMeasurement.publish_snapshot is BaseMeasurement.publish_snapshot


@pytest.mark.parametrize("method,args", [("set_output", (.5,)), ("set_field", (50,)), ("configure_instruments", ())])
def test_foreign_thread_cannot_issue_hardware_commands(method, args):
    run = measurement()
    errors = []
    with run.session(save=False) as session:
        session.configure_instruments()
        before = list(run.sourcemeter.mock_calls)
        def foreign():
            try:
                getattr(run, method)(*args)
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=foreign)
        thread.start()
        thread.join(2)
        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], ConcurrentRunError)
        assert run.sourcemeter.mock_calls == before


@pytest.mark.parametrize("early_stop", [False, True])
def test_new_run_does_not_reuse_old_views(early_stop):
    run = measurement()
    run.run_experiment(save=False)
    old_id = run.last_run_record.run_id
    if early_stop:
        token = run._reserve()
        run.request_stop()
        run.run_experiment(token=token, save=False)
    else:
        run.sourcemeter.configure_voltage_source.side_effect = RuntimeError("configuration failed")
        with pytest.raises(RuntimeError, match="configuration failed"):
            run.run_experiment(save=False)
    assert run.raw_data is None or run.raw_data.empty
    assert run.completed_cycles == 0
    assert run.last_cycle.empty and run.cycle_average.empty
    snapshot = run.snapshot()
    assert snapshot.run_id != old_id
    assert snapshot.state == run.run_state
    assert snapshot.raw is None or snapshot.raw.empty


def test_snapshot_does_not_hide_unsafe_shutdown():
    run = measurement()
    def callback(snapshot):
        run.sourcemeter.output.side_effect = RuntimeError("disable failed")
        raise ValueError("read callback failed")
    with pytest.raises(ValueError, match="read callback failed"):
        run.run_experiment(save=False, on_update=callback)
    assert run.snapshot().safety == SafetyStatus.UNSAFE
    assert len(run.raw_data) == 1


def test_removed_compatibility_surface_and_unknown_options():
    run = measurement()
    for name in ("analyze", "save_data", "shut_off", "configure_sourcemeter", "configure_dmm", "history"):
        assert not hasattr(run, name)
    for kwargs in ({"save_dir": "unused"}, {"safe_shutdown": lambda source: None}):
        with pytest.raises(TypeError):
            measurement(**kwargs)
    with pytest.raises(ValueError, match="Unknown MOKE"):
        run.run_experiment(save=False, options={"ignored": True})
    assert not run.sourcemeter.mock_calls


def gui_app():
    module = _load_gui_module()
    app = module.MokeMeasurementApp.__new__(module.MokeMeasurementApp)
    app.root = Mock()
    app.root.winfo_exists.return_value = True
    app.is_measuring = False
    app.runner = None
    app._terminal_event = None
    app._close_when_safe = False
    app.save_data = Mock(get=Mock(return_value=False))
    app.status_label = Mock()
    app.run_button = Mock()
    app.stop_button = Mock()
    app._close_instruments = Mock()
    app._plot_snapshot = Mock()
    app._finish_close = Mock()
    app._create_experiment = Mock(return_value=measurement())
    return app, module


def test_gui_uses_runner_and_complete_terminal_delivery():
    app, module = gui_app()
    app.run_measurement()
    assert app.runner._worker_thread.daemon is False
    assert app.runner.join(5)
    app._poll_events()
    assert not app.is_measuring
    app._close_instruments.assert_called_once()
    assert app._plot_snapshot.call_args.args[0].state == RunState.COMPLETED


def test_gui_retains_connections_and_blocks_close_when_unsafe(monkeypatch):
    app, module = gui_app()
    run = app._create_experiment.return_value
    run.shutdown_handler = Mock(side_effect=RuntimeError("unsafe setup"))
    monkeypatch.setattr(module.messagebox, "showerror", Mock())
    app.run_measurement()
    assert app.runner.join(5)
    app._poll_events()
    app.on_closing()
    app._close_instruments.assert_not_called()
    app._finish_close.assert_not_called()
    assert not app.runner.can_close()
