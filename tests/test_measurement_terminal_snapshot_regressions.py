"""Final results replace stale or truncated display data."""
import pandas as pd
import pytest

from piec.measurement.base import BaseMeasurement


@pytest.mark.parametrize('empty', [False, True])
def test_terminal_snapshot_replaces_display_data_with_analysis_result(empty):
    class Measurement(BaseMeasurement):
        def _capture_data(self, request, on_update=None):
            self.publish_snapshot({'data': pd.DataFrame({'v': [1.]}),
                                   'raw_window': pd.DataFrame({'v': [1.]})})
            return pd.DataFrame({'v': [1., 2.]})
        def _analyze_data(self, raw, request):
            return pd.DataFrame({'v': [] if empty else [10., 20.]})
    measurement = Measurement()
    events = []
    measurement.add_event_listener(events.append)
    result = measurement.run_experiment(save=False)
    pd.testing.assert_frame_equal(events[0].final_snapshot.get_view('data'), result)
    pd.testing.assert_frame_equal(measurement.snapshot().get_view('data'), result)
    assert len(events[0].final_snapshot.get_view('raw_window')) == 1
    result.loc[0, 'v'] = 999.
    assert 999. not in events[0].final_snapshot.get_view('data')['v'].tolist()
