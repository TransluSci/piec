"""AMR sweep fault, cancellation, bounded-display and physical-position checks."""
from unittest.mock import Mock, patch

import pytest

from piec.measurement import AMR
from piec.measurement.contracts import RunState, SafetyStatus, TerminalEvent
from tests.test_measurement_amr_compatibility import create_mock_amr_instruments


def sweep(**kwargs):
    instruments = create_mock_amr_instruments()
    run = AMR(dmm=instruments['dmm'], calibrator=instruments['calibrator'],
        stepper=instruments['arduino'], lockin=instruments['lockin'],
        shutdown_handler=Mock(), measure_time=kwargs.pop('measure_time', 0),
        settling_time=kwargs.pop('settling_time', 0), **kwargs)
    return run, instruments


def test_bounded_live_view_preserves_complete_terminal_result():
    run, _ = sweep(angle_step=1.8, total_angle=36, raw_window_points=3)
    control = run.create_control_queue()
    lengths = []
    result = run.run_experiment(save=False,
        on_update=lambda snapshot: lengths.append(len(snapshot.get_view('raw_window'))))
    assert len(result) == 21
    assert max(lengths) == 3
    terminal = None
    while not control.empty():
        event = control.get_nowait()
        if isinstance(event, TerminalEvent):
            terminal = event
    assert len(terminal.final_snapshot.get_view('data')) == 21


def test_sweep_limit_preflight_happens_before_any_instrument_io():
    run, instruments = sweep(angle_step=1, total_angle=1)
    run.orientation_controller.angle_limits = (0, 1)
    with pytest.raises(ValueError, match='Quantized'):
        run.run_experiment(save=False)
    for key in ('dmm', 'calibrator', 'arduino', 'lockin'):
        assert not instruments[key].mock_calls


def test_stop_during_motor_call_does_not_enter_uncancellable_settle_or_read():
    run, instruments = sweep(start_angle=1.8, total_angle=3.6, angle_step=1.8, settling_time=30)
    instruments['arduino'].step.side_effect = lambda *args: run.request_stop()
    with patch('time.sleep', side_effect=AssertionError('Stop must bypass settling')):
        result = run.run_experiment(save=False)
    assert result.empty
    assert run.run_state == RunState.ABORTED
    assert run.safety_status == SafetyStatus.SAFE
    instruments['lockin'].get_X_Y.assert_not_called()


def test_stop_during_averaging_does_not_read_again_or_publish_shortened_average():
    run, instruments = sweep(total_angle=0, measure_time=60)
    def reading():
        run.request_stop()
        return (1e-5, 2e-5)
    instruments['lockin'].get_X_Y.side_effect = reading
    result = run.run_experiment(save=False)
    assert result.empty
    instruments['lockin'].get_X_Y.assert_called_once()
    assert run.safety_status == SafetyStatus.SAFE


def test_read_fault_preserves_prior_points_and_engine_partial(tmp_path):
    run, instruments = sweep(angle_step=90, total_angle=180, output_dir=tmp_path)
    instruments['lockin'].get_X_Y.side_effect = [(1e-5, 2e-5), RuntimeError('read fault')]
    with pytest.raises(RuntimeError, match='read fault'):
        run.run_experiment(save=True, save_partial=True)
    assert len(run.raw_data) == 1
    assert run.partial_filename is not None
    assert run.safety_status == SafetyStatus.SAFE
    run.transport_readout.shutdown_handler.assert_called_once()


def test_descending_sweep_has_no_extra_endpoint_move():
    run, instruments = sweep(angle_step=-90, total_angle=-180)
    result = run.run_experiment(save=False)
    assert list(result.angle) == [0, -90, -180]
    assert instruments['current_angle'][0] == -180
    assert instruments['arduino'].step.call_count == 2


@pytest.mark.parametrize('kwargs', [{'live_plot': True}, {'save_dir': 'out'}, {'plot_config': {}}])
def test_removed_compatibility_keywords_are_rejected(kwargs):
    with pytest.raises(TypeError):
        AMR(**kwargs)


def test_consumer_does_not_fabricate_shutdown_and_gui_gates_before_connection():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    gui = (root / 'Measurements/AMR/amr_GUI.py').read_text(encoding='utf-8')
    notebook = (root / 'Measurements/AMR/AMR_testing.ipynb').read_text(encoding='utf-8')
    assert 'shutdown_handler=lambda: None' not in gui + notebook
    assert gui.index('if not callable(shutdown_handler):') < gui.index('# Initialize drivers')
