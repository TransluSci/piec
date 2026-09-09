"""Rejected execution attempts must have no effects on the active owner."""
import threading

import pandas as pd
import pytest

from piec.measurement.base import BaseMeasurement
from piec.measurement.runner import MeasurementRunner
from piec.measurement.contracts import (
    ConcurrentRunError, DuplicateExecutionError, ReservationToken, StaleTokenError,
)


@pytest.mark.parametrize('attempt', ['duplicate', 'stale', 'concurrent', 'stopped_stale'])
def test_rejected_caller_does_not_safe_or_clear_active_owner(attempt):
    entered, release = threading.Event(), threading.Event()
    shutdown_threads = []

    class Measurement(BaseMeasurement):
        def _capture_data(self, request, on_update=None):
            self._raw_data = pd.DataFrame({'v': [42.]})
            entered.set()
            assert release.wait(3)
            return self._raw_data

        def _safe_shutdown(self):
            shutdown_threads.append(threading.get_ident())
            return super()._safe_shutdown()

    measurement = Measurement()
    runner = MeasurementRunner(measurement)
    token = runner.start(save=False)
    try:
        assert entered.wait(2)
        owner = measurement._active_owner_thread_id
        if attempt == 'stopped_stale':
            runner.request_stop()
        state = measurement.run_state
        kwargs = {'save': False}
        if attempt == 'duplicate':
            kwargs['token'] = token
            error = DuplicateExecutionError
        elif attempt in ('stale', 'stopped_stale'):
            kwargs['token'] = ReservationToken(run_id='stale', generation=0)
            error = StaleTokenError
        else:
            error = ConcurrentRunError
        with pytest.raises(error):
            measurement.run_experiment(**kwargs)
        assert shutdown_threads == []
        assert measurement._active_owner_thread_id == owner
        assert measurement.run_state == state
        assert measurement.raw_data['v'].tolist() == [42.]
        assert measurement.run_records == ()
    finally:
        release.set()
        assert runner.join(3)
    assert runner.last_error is None
    assert shutdown_threads == [owner]
    assert len(measurement.run_records) == 1
