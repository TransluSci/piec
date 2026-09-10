"""
Tests for IV Sweep GUI interaction and ownership hardening (Checkpoint 15).

Verifies that the GUI consumer fulfills the standardized GUI contract:
- Single hardware writer rule (no commands/queries while active);
- GUI connection ownership and safe close gating (instruments closed only when
  worker terminated and safety confirmed);
- Unsafe shutdown retains connections and blocks normal close;
- Window close coordination with non-blocking polling and cooperative stop;
- Stop-before-start zero-I/O abort;
- Terminal errors, safety alerts, and complete dataset presentation.
"""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.measurement.contracts import RunState, SafetyAlertEvent, SafetyStatus, TerminalEvent
from piec.measurement.iv_sweep import IVSweep
from piec.measurement.runner import MeasurementRunner
from Measurements.DCIV.IV_sweep_GUI import IVSweepApp, DEFAULTS


def test_iv_sweep_gui_imports_and_structure():
    """Verify IV Sweep GUI imports target components without legacy shims."""
    gui_path = Path("Measurements/DCIV/IV_sweep_GUI.py")
    assert gui_path.is_file()

    with open(gui_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Must import MeasurementRunner and read_measurement_csv
    assert "from piec.measurement.runner import MeasurementRunner" in content
    assert "from piec.measurement.persistence import read_measurement_csv" in content
    assert "standard_csv_to_metadata_and_data" not in content
    # Target columns
    assert '"voltage", "current"' in content
    assert "save_dir=save_dir" not in content


def test_iv_sweep_gui_logic_headless():
    """Verify GUI instantiation and measurement setup in headless mode."""
    root = MagicMock()
    with patch("Measurements.DCIV.IV_sweep_GUI.MeasurementApp.__init__") as mock_init, \
         patch("Measurements.DCIV.IV_sweep_GUI.MeasurementRunner") as mock_runner_cls, \
         patch("Measurements.DCIV.IV_sweep_GUI.VirtualSourcemeter") as mock_vsm:

        mock_vsm_inst = MagicMock()
        mock_vsm.return_value = mock_vsm_inst

        app = IVSweepApp.__new__(IVSweepApp)
        app.root = root
        app.run_button = MagicMock()
        app.stop_button = MagicMock()
        app.status_label = MagicMock()
        app.sm_address_entry = MagicMock()
        app.sm_address_entry.get.return_value = "VIRTUAL"
        app.save_dir_entry = MagicMock()
        app.save_dir_entry.get.return_value = ""
        app.sense_mode_entry = MagicMock()
        app.sense_mode_entry.get.return_value = "2W"
        app.dynamic_inputs = {
            "v_start": MagicMock(get=MagicMock(return_value="0.0")),
            "v_stop": MagicMock(get=MagicMock(return_value="1.0")),
            "num_steps": MagicMock(get=MagicMock(return_value="5")),
            "current_compliance": MagicMock(get=MagicMock(return_value="0.1")),
            "dwell_time": MagicMock(get=MagicMock(return_value="0.01")),
        }
        app.x_axis = MagicMock()
        app.x_axis.get.return_value = "voltage"
        app.y_axis = MagicMock()
        app.y_axis.get.return_value = "current"
        app.ax = MagicMock()
        app.canvas = MagicMock()

        # Run measurement
        app.run_measurement()

        assert hasattr(app, "experiment")
        assert app.experiment.v_start == 0.0
        assert app.experiment.v_stop == 1.0
        assert app.experiment.num_steps == 5
        assert app.experiment.output_dir is None
        assert mock_runner_cls.called

        # Test plotting helper with dataframe
        test_df = pd.DataFrame({"voltage": [0.0, 0.5, 1.0], "current": [0.0, 0.005, 0.01]})
        app._plot_dataframe(test_df)
        assert app.ax.plot.called
        assert app.ax.set_xlabel.called
        assert app.ax.set_ylabel.called
        assert app.canvas.draw.called


def make_headless_iv_gui():
    """Construct a fully populated headless IVSweepApp for interaction testing."""
    app = IVSweepApp.__new__(IVSweepApp)
    app.root = MagicMock()
    app.root.winfo_exists.return_value = True
    app.experiment = None
    app.runner = None
    app._terminal_event = None
    app.is_measuring = False
    app._close_when_safe = False
    app._instruments = []
    app._poll_runner_id = None

    app.run_button = MagicMock()
    app.stop_button = MagicMock()
    app.status_label = MagicMock()
    app.sm_address_entry = MagicMock()
    app.sm_address_entry.get.return_value = "VIRTUAL"
    app.save_dir_entry = MagicMock()
    app.save_dir_entry.get.return_value = ""
    app.sense_mode_entry = MagicMock()
    app.sense_mode_entry.get.return_value = "2W"
    app.dynamic_inputs = {
        "v_start": MagicMock(get=MagicMock(return_value="0.0")),
        "v_stop": MagicMock(get=MagicMock(return_value="0.2")),
        "num_steps": MagicMock(get=MagicMock(return_value="3")),
        "current_compliance": MagicMock(get=MagicMock(return_value="0.1")),
        "dwell_time": MagicMock(get=MagicMock(return_value="0.0")),
    }
    app.x_axis = MagicMock()
    app.x_axis.get.return_value = "voltage"
    app.y_axis = MagicMock()
    app.y_axis.get.return_value = "current"
    app.ax = MagicMock()
    app.canvas = MagicMock()
    return app


def test_gui_uses_runner_and_complete_terminal_delivery():
    """Verify non-daemon execution, complete terminal data delivery, and clean close gating."""
    app = make_headless_iv_gui()
    app.run_measurement()

    assert app.is_measuring is True
    assert app.runner is not None
    assert app.runner._worker_thread.daemon is False
    assert len(app._instruments) == 1

    # Allow worker to complete
    assert app.runner.join(timeout=5)
    app._poll_runner()

    assert app.is_measuring is False
    assert app.runner.run_state == RunState.COMPLETED
    assert app.runner.safety_status == SafetyStatus.SAFE
    assert len(app._instruments) == 0  # Sourcemeter closed and cleared
    assert app.run_button.config.called
    assert app.stop_button.config.called
    assert app.ax.plot.called


def test_gui_retains_connections_and_blocks_close_when_unsafe(monkeypatch):
    """Verify unsafe shutdown retains open connections and blocks window close."""
    import Measurements.DCIV.IV_sweep_GUI as gui_mod

    app = make_headless_iv_gui()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", MagicMock())

    # Force shutdown to fail
    def failing_shutdown(recorder):
        raise RuntimeError("hardware safing failed")

    monkeypatch.setattr(IVSweep, "_safe_shutdown", failing_shutdown)

    app.run_measurement()
    assert app.runner.join(timeout=5)

    # First poll delivers events
    app._poll_runner()

    assert app.runner.safety_status == SafetyStatus.UNSAFE
    assert not app.runner.can_close()
    # Sourcemeter MUST NOT be closed
    assert len(app._instruments) == 1

    # Attempt window close
    finish_mock = MagicMock()
    app._finish_close = finish_mock
    app.on_closing()

    # Close must be blocked
    assert not finish_mock.called
    assert len(app._instruments) == 1
    assert app._close_when_safe is True
    assert not app.runner.can_close()


def test_gui_stop_before_start():
    """Verify Stop-before-start transitions cleanly without hardware I/O."""
    app = make_headless_iv_gui()

    original_start = MeasurementRunner.start

    def stopping_start(runner_self, *args, **kwargs):
        token = original_start(runner_self, *args, **kwargs)
        app.stop_measurement()
        return token

    with patch.object(MeasurementRunner, "start", stopping_start):
        app.run_measurement()

    assert app.runner.join(timeout=5)
    app._poll_runner()

    assert app.runner.run_state == RunState.ABORTED
    assert app.runner.safety_status in (SafetyStatus.NOT_NEEDED, SafetyStatus.SAFE)
    assert not app.is_measuring
    assert app.runner.can_close()
    assert len(app._instruments) == 0


def test_gui_active_close_requests_stop_and_defers_close():
    """Verify active close requests stop and defers destruction until worker exit and safety confirmed."""
    app = make_headless_iv_gui()
    # Set longer dwell time to ensure worker is alive during close request
    app.dynamic_inputs["dwell_time"].get.return_value = "0.5"

    app.run_measurement()
    assert app.runner.is_worker_alive

    finish_mock = MagicMock()
    app._finish_close = finish_mock

    # Request window close while running
    app.on_closing()
    assert app.runner.is_closing is True
    assert app._close_when_safe is True
    assert not finish_mock.called

    # Wait for cooperative stop to complete
    assert app.runner.join(timeout=5)
    assert app.runner.can_close()

    # Next poll executes deferred finish close
    app._poll_runner()
    assert finish_mock.called
    assert len(app._instruments) == 0


def test_gui_does_not_issue_hardware_commands_while_measuring():
    """Verify single hardware writer rule: callbacks reject commands during an active run."""
    app = make_headless_iv_gui()
    app.is_measuring = True

    # 1. run_measurement should be a no-op
    app.run_measurement()
    assert app.runner is None

    # 2. refresh_instruments should not query resources
    with patch.object(app, "get_visa_resources") as mock_visa:
        app.refresh_instruments()
        assert not mock_visa.called


def test_gui_handles_terminal_error_and_displays_message(monkeypatch):
    """Verify terminal errors trigger error dialog and update status."""
    import Measurements.DCIV.IV_sweep_GUI as gui_mod

    app = make_headless_iv_gui()
    mock_showerror = MagicMock()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", mock_showerror)

    # Force acquisition read failure
    def failing_read(self, *args, **kwargs):
        raise RuntimeError("communication timeout during read")

    monkeypatch.setattr(VirtualSourcemeter, "get_current", failing_read)

    app.run_measurement()
    assert app.runner.join(timeout=5)
    app._poll_runner()

    assert app.runner.run_state == RunState.FAILED
    assert not app.is_measuring
    assert mock_showerror.called
    assert "IV Sweep measurement failed" in mock_showerror.call_args[0][0]
    assert "communication timeout" in str(mock_showerror.call_args[0][1])


def test_gui_handles_invalid_numeric_inputs(monkeypatch):
    """Verify invalid numeric inputs produce an error dialog without touching hardware."""
    import Measurements.DCIV.IV_sweep_GUI as gui_mod

    app = make_headless_iv_gui()
    mock_showerror = MagicMock()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", mock_showerror)

    app.dynamic_inputs["v_start"].get.return_value = "not_a_number"
    app.run_measurement()

    assert mock_showerror.called
    assert "Invalid Input" in mock_showerror.call_args[0][0]
    assert app.runner is None
    assert len(app._instruments) == 0


def test_gui_handles_sourcemeter_connection_failure(monkeypatch):
    """Verify instrument connection errors are surfaced and cleaned up safely."""
    import Measurements.DCIV.IV_sweep_GUI as gui_mod

    app = make_headless_iv_gui()
    mock_showerror = MagicMock()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", mock_showerror)

    def failing_vsm(*args, **kwargs):
        raise ConnectionError("device address unreachable")

    monkeypatch.setattr(gui_mod, "VirtualSourcemeter", failing_vsm)

    app.run_measurement()

    assert mock_showerror.called
    assert "Sourcemeter connection error" in mock_showerror.call_args[0][0]
    assert app.runner is None
    assert len(app._instruments) == 0


def test_gui_axis_change_before_first_run_is_noop():
    app = make_headless_iv_gui()
    assert app.experiment is None
    app.plot_data()
    app.ax.plot.assert_not_called()
    app.canvas.draw.assert_not_called()


def test_gui_deferred_close_releases_connections_after_safety_retry(monkeypatch):
    import Measurements.DCIV.IV_sweep_GUI as gui_mod

    app = make_headless_iv_gui()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", Mock())
    with patch.object(IVSweep, "_safe_shutdown", side_effect=RuntimeError("unsafe")):
        app.run_measurement()
        assert app.runner.join(timeout=5)
        source = app._instruments[0]
        source.close = Mock()
        app._poll_runner()

    def finish():
        assert app._instruments == []
        source.close.assert_called_once_with()
    app._finish_close = Mock(side_effect=finish)
    app.on_closing()
    source.close.assert_not_called()
    app._finish_close.assert_not_called()

    app.experiment.safe_shutdown()
    assert app.runner.can_close()
    app._poll_runner()
    app._finish_close.assert_called_once_with()


def test_gui_reports_recovery_paths_from_failed_save_record(monkeypatch, tmp_path, capsys):
    import Measurements.DCIV.IV_sweep_GUI as gui_mod
    from piec.measurement import persistence

    app = make_headless_iv_gui()
    app.save_dir_entry.get.return_value = str(tmp_path)
    monkeypatch.setattr(gui_mod.messagebox, "showerror", Mock())
    monkeypatch.setattr(persistence, "atomic_publish_no_replace",
                        Mock(side_effect=OSError("publication failed")))
    app.run_measurement()
    assert app.runner.join(timeout=5)
    record = app.experiment.last_run_record
    paths = record.metadata["recoverable_staging_paths"]
    assert record.state == RunState.FAILED
    assert paths and all(Path(path).is_file() for path in paths)
    app._poll_runner()
    output = capsys.readouterr().out
    assert "Recoverable data staging paths:" in output
    assert all(path in output for path in paths) or str(paths) in output
