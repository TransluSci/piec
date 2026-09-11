"""Regressions for actual combobox event ordering and failed runner startup."""
from unittest.mock import Mock, patch

import pytest

from tests.test_measurement_fe_gui import make_headless_fe_gui, gui_mod
from piec.measurement.runner import MeasurementRunner


@pytest.mark.parametrize("meas_type,other", [
    ("HysteresisLoop", "ThreePulsePund"),
    ("ThreePulsePund", "HysteresisLoop"),
])
def test_busy_combobox_restores_value_and_preserves_input_fields(meas_type, other):
    app = make_headless_fe_gui(meas_type)
    app._run_measurement_type = meas_type
    app.runner = Mock()
    app.runner.can_close.return_value = False
    original_fields = dict(app.dynamic_inputs)
    # A real Tk selection changes the widget value before calling the binding.
    app.measurement_type.get.return_value = other
    app.measurement_type.set.side_effect = lambda value: setattr(
        app.measurement_type.get, "return_value", value)
    app.update_dynamic_inputs(None)
    assert app.measurement_type.get() == meas_type
    assert app.dynamic_inputs == original_fields
    app.runner = None
    app._create_experiment()  # No mismatched-fields KeyError on the next run.
    app._close_instruments()


@pytest.mark.parametrize("failure_stage", ["validation", "thread_launch"])
def test_failed_start_restores_idle_and_allows_retry(failure_stage):
    app = make_headless_fe_gui()
    # One failure has no terminal event; Thread.start failure has one queued.
    target = (patch.object(MeasurementRunner, "start", side_effect=ValueError("invalid request"))
              if failure_stage == "validation" else
              patch("piec.measurement.runner.threading.Thread.start", side_effect=RuntimeError("cannot launch")))
    with patch.object(gui_mod.messagebox, "showerror"), target:
        app.run_measurement()
    assert not app._busy()
    assert not app._awaiting_terminal
    assert not app._instruments
    app.measurement_type.config.assert_called_with(state="readonly")
    with patch.object(gui_mod.messagebox, "showerror"):
        app._poll_events()
    assert not app._busy()
    app.run_measurement()
    app.measurement_type.config.assert_called_with(state="disabled")
    assert app.runner.join(5)
    app._poll_events()
    assert not app._busy()
    app.measurement_type.config.assert_called_with(state="readonly")


def test_start_error_does_not_release_active_ownership():
    app = make_headless_fe_gui()
    runner = Mock()
    runner.can_close.return_value = False
    runner.start.side_effect = RuntimeError("error after ownership acquired")
    with patch.object(gui_mod, "MeasurementRunner", return_value=runner), \
         patch.object(gui_mod.messagebox, "showerror"):
        app.run_measurement()
    assert app._busy()
    assert app._awaiting_terminal
    assert len(app._instruments) == 2
    app.measurement_type.config.assert_called_with(state="disabled")
