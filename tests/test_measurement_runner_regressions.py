"""Pre-I/O failures and terminal delivery must retain runner ownership."""
import threading
from unittest.mock import patch

import pytest

from piec.measurement.base import BaseMeasurement
from piec.measurement.runner import MeasurementRunner
from piec.measurement.contracts import ConcurrentRunError, RunState, SafetyStatus, TerminalEvent


def test_options_rejected_before_reserving_or_launching():
    class Measurement(BaseMeasurement):
        def _validate_options(self, options):
            if options.get('bad'):
                raise ValueError('invalid settings')
    measurement = Measurement()
    runner = MeasurementRunner(measurement)
    with patch('piec.measurement.runner.threading.Thread') as thread:
        with pytest.raises(ValueError, match='invalid settings'):
            runner.start(options={'bad': True})
        thread.assert_not_called()
    assert runner.run_state == RunState.IDLE
    assert runner.active_token is None
    assert runner.run_records == ()
    assert runner.can_close()
    runner.start(save=False)
    assert runner.join(2)
    assert runner.last_error is None


@pytest.mark.parametrize('stop', [False, True])
def test_worker_validation_failure_finalizes_unconsumed_reservation(stop):
    class Measurement(BaseMeasurement):
        validations = 0
        def _validate_options(self, options):
            self.validations += 1
            if self.validations == 2:
                if stop:
                    self.request_stop()
                raise ValueError('worker validation failed')
        def _configure_instruments(self, request):
            raise AssertionError('must not configure')
        def _safe_shutdown(self):
            raise AssertionError('must not touch hardware')
    runner = MeasurementRunner(Measurement())
    runner.start(save=False)
    assert runner.join(2)
    assert isinstance(runner.last_error, ValueError)
    assert runner.run_state == RunState.FAILED
    assert runner.safety_status == SafetyStatus.NOT_NEEDED
    assert len(runner.run_records) == 1
    events = []
    while not runner.control_queue.empty():
        events.append(runner.control_queue.get_nowait())
    assert sum(isinstance(e, TerminalEvent) for e in events) == 1
    assert runner.can_close()


def test_thread_constructor_failure_finalizes_reservation():
    runner = MeasurementRunner(BaseMeasurement())
    with patch('piec.measurement.runner.threading.Thread', side_effect=RuntimeError('no thread')):
        with pytest.raises(RuntimeError, match='no thread'):
            runner.start(save=False)
    assert runner.run_state == RunState.FAILED
    assert runner.safety_status == SafetyStatus.NOT_NEEDED
    assert len(runner.run_records) == 1
    assert runner.can_close()


def test_new_start_cannot_replace_worker_still_delivering_terminal():
    measurement = BaseMeasurement()
    runner = MeasurementRunner(measurement)
    entered, release = threading.Event(), threading.Event()
    def terminal(event):
        if event.generation == 1:
            entered.set()
            assert release.wait(3)
    measurement.add_event_listener(terminal)
    runner.start(save=False)
    try:
        assert entered.wait(2)
        assert runner.run_state == RunState.COMPLETED
        with pytest.raises(ConcurrentRunError):
            runner.start(save=False)
        assert runner.is_worker_alive
        assert not runner.can_close()
    finally:
        release.set()
        assert runner.join(3)
    assert runner.can_close()
    runner.start(save=False)
    assert runner.join(2)
    assert len(runner.run_records) == 2
