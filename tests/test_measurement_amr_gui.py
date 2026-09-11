"""
Tests for AMR GUI presentation integration (Checkpoint 24c).

Verifies:
- MeasurementRunner lifecycle integration (non-daemon background execution);
- Pre-connection parameter validation;
- Explicit excitation shutdown policy gating:
  - Simulation-only policy restricted to all-virtual instruments;
  - Mandatory external excitation_shutdown_handler for physical instruments;
  - Zero tolerance for no-op callbacks (lambda: None);
  - Restriction of simulation shutdown to VirtualLockin instances and exception propagation;
- Manual lock-in setting preservation by default (initialize_lockin=False);
- Main-thread plotting with metadata-derived units from column_units;
- Bounded raw_window live display updates vs authoritative terminal data;
- Cooperative Pause and Stop controls;
- Open instrument connection retention and window close gating on UNSAFE shutdown;
- Single ownership / busy guard blocking Run, Refresh, Autodetect, and Test Stepper during active or unsafe states;
- Clean closure and release of connections when runner.can_close() allows it (including NOT_NEEDED pre-start aborts);
- Immediate tracking of driver connections and complete cleanup of partial setup failures;
- Save policy with placeholder / valid save_dir.
"""

import importlib.util
import math
from pathlib import Path
import threading
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pandas as pd
import pytest

from piec.drivers.lockin.srs830 import SRS830
from piec.drivers.lockin.virtual_lockin import VirtualLockin
from piec.measurement.contracts import RunState, SafetyAlertEvent, SafetyStatus, TerminalEvent
from piec.measurement.amr import AMR
from piec.measurement.runner import MeasurementRunner

ROOT = Path(__file__).resolve().parents[1]
GUI_PATH = ROOT / "Measurements" / "AMR" / "amr_GUI.py"


def _load_amr_gui_module():
    spec = importlib.util.spec_from_file_location("amr_gui_module", GUI_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gui_mod = _load_amr_gui_module()
AMRApp = gui_mod.AMRApp
DEFAULTS = gui_mod.DEFAULTS


def test_amr_gui_imports_and_structure():
    """Verify AMR GUI imports target components without legacy execution shims."""
    assert GUI_PATH.is_file()
    content = GUI_PATH.read_text(encoding="utf-8")

    assert "from piec.measurement import MeasurementRunner" in content
    assert "from piec.measurement.amr import AMR" in content
    assert "shutdown_handler=lambda: None" not in content
    assert content.index("if not callable(shutdown_handler):") < content.index("# Initialize drivers")
    assert "threading.Thread(target=self.experiment.run_experiment" not in content


def make_headless_amr_gui(tmp_path=None, excitation_shutdown_handler=None):
    """Construct a fully populated headless AMRApp for lifecycle and interaction testing."""
    app = AMRApp.__new__(AMRApp)
    app.root = MagicMock()
    app.root.winfo_exists.return_value = True

    app.experiment = None
    app.runner = None
    app._terminal_event = None
    app._awaiting_terminal = False
    app._closing = False
    app._close_when_safe = False
    app._instruments = []
    app._active_lockin = None
    app._current_plot_data = None
    app._last_snapshot = None
    app._save_this_run = False
    app.is_measuring = False
    app.paused = False
    app.excitation_shutdown_handler = excitation_shutdown_handler
    app._poll_id = None

    # Static addresses
    app.dmm_address_entry = MagicMock()
    app.dmm_address_entry.get.return_value = "VIRTUAL"
    app.calibrator_address_entry = MagicMock()
    app.calibrator_address_entry.get.return_value = "VIRTUAL"
    app.stepper_address_entry = MagicMock()
    app.stepper_address_entry.get.return_value = "VIRTUAL"
    app.lockin_address_entry = MagicMock()
    app.lockin_address_entry.get.return_value = "VIRTUAL"

    app.save_dir_entry = MagicMock()
    app.save_dir_entry.get.return_value = str(tmp_path) if tmp_path else ""

    # Dynamic inputs
    app.dynamic_inputs = {
        "field": MagicMock(get=MagicMock(return_value="100.0")),
        "angle_step": MagicMock(get=MagicMock(return_value="45.0")),
        "total_angle": MagicMock(get=MagicMock(return_value="90.0")),
        "amplitude": MagicMock(get=MagicMock(return_value="1.0")),
        "frequency": MagicMock(get=MagicMock(return_value="10.0")),
        "measure_time": MagicMock(get=MagicMock(return_value="0.01")),
        "sensitivity": MagicMock(get=MagicMock(return_value="50uv/pa")),
    }

    # Lock-in initialization checkbox defaults to False
    app.initialize_lockin_var = MagicMock()
    app.initialize_lockin_var.get.return_value = False

    # Plot axes
    app.x_axis = MagicMock()
    app.x_axis.get.return_value = "angle"
    app.y_axis = MagicMock()
    app.y_axis.get.return_value = "x"

    # UI controls
    app.run_button = MagicMock()
    app.stop_button = MagicMock()
    app.pause_button = MagicMock()
    app.status_label = MagicMock()
    app.control_frame = None
    app.right_panel = MagicMock()

    # Plot widgets
    app.ax = MagicMock()
    app.canvas = MagicMock()

    return app


def test_amr_gui_defaults():
    """Verify default parameters: initialize_lockin defaults to False (preserve settings)."""
    assert DEFAULTS["initialize_lockin"] is False
    assert DEFAULTS["dmm_address"] == "VIRTUAL"
    assert DEFAULTS["lockin_address"] == "VIRTUAL"


@pytest.mark.parametrize("bad_param, bad_val", [
    ("field", "nan"),
    ("angle_step", "0"),
    ("total_angle", "nan"),
    ("amplitude", "-1"),
    ("frequency", "0"),
    ("measure_time", "-0.1"),
])
def test_amr_gui_preconnection_validation(monkeypatch, bad_param, bad_val):
    """Verify invalid parameters reject execution before initializing any hardware drivers."""
    app = make_headless_amr_gui()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", MagicMock())
    app.dynamic_inputs[bad_param].get.return_value = bad_val

    with patch.object(gui_mod, "VirtualDMM") as mock_dmm,          patch.object(gui_mod, "VirtualCalibrator") as mock_cal,          patch.object(gui_mod, "VirtualStepper") as mock_step,          patch.object(gui_mod, "VirtualLockin") as mock_lock:
        app.run_measurement()
        assert not mock_dmm.called
        assert not mock_cal.called
        assert not mock_step.called
        assert not mock_lock.called
        assert len(app._instruments) == 0
        assert app.runner is None


def test_amr_gui_requires_shutdown_handler_for_physical_instruments(monkeypatch):
    """Verify physical instruments require explicit excitation_shutdown_handler and reject pre-connection."""
    monkeypatch.setattr(gui_mod.messagebox, "showerror", MagicMock())

    # Set lockin to physical address with NO excitation_shutdown_handler
    app = make_headless_amr_gui(excitation_shutdown_handler=None)
    app.lockin_address_entry.get.return_value = "GPIB0::8::INSTR"

    with patch.object(gui_mod, "SRS830") as mock_srs:
        app.run_measurement()
        assert not mock_srs.called
        assert len(app._instruments) == 0
        assert app.runner is None


def test_amr_gui_simulation_shutdown_policy_for_virtual_instruments():
    """Verify all-virtual instruments automatically use _simulation_excitation_shutdown."""
    app = make_headless_amr_gui(excitation_shutdown_handler=None)
    mock_lockin = MagicMock(spec=VirtualLockin)
    app._active_lockin = mock_lockin

    app._simulation_excitation_shutdown()
    mock_lockin.configure_reference.assert_called_once_with(voltage=0.0)


def test_amr_gui_custom_shutdown_handler():
    """Verify custom excitation_shutdown_handler is passed to AMR and executed."""
    custom_shutdown = Mock()
    app = make_headless_amr_gui(excitation_shutdown_handler=custom_shutdown)

    with patch("time.sleep", return_value=None):
        app.run_measurement()
        assert app.runner is not None
        assert app.runner.join(timeout=5)
        app._poll_runner()

    custom_shutdown.assert_called()
    assert app.runner.run_state == RunState.COMPLETED
    assert app.runner.safety_status == SafetyStatus.SAFE


def test_amr_gui_runs_virtual_amr_cleanly():
    """Verify virtual AMR runs via MeasurementRunner, completes, and plots with metadata-derived units."""
    app = make_headless_amr_gui()

    with patch("time.sleep", return_value=None):
        app.run_measurement()
        assert app.runner is not None
        assert app.runner._worker_thread.daemon is False
        assert len(app._instruments) == 4

        # Wait for completion
        assert app.runner.join(timeout=5)
        app._poll_runner()

    assert app.runner.run_state == RunState.COMPLETED
    assert app.runner.safety_status == SafetyStatus.SAFE
    assert len(app._instruments) == 0  # Cleanly closed upon safe completion
    assert app.ax.plot.called

    # Metadata-derived unit labels: angle (deg), x (V)
    app.ax.set_xlabel.assert_called_with("angle (deg)")
    app.ax.set_ylabel.assert_called_with("x (V)")


def test_amr_gui_bounded_display_and_terminal_view():
    """Verify display queue plots raw_window and terminal event plots authoritative terminal data."""
    app = make_headless_amr_gui()

    with patch("time.sleep", return_value=None):
        app.run_measurement()
        assert app.runner.join(timeout=5)
        app._poll_runner()

    # Terminal data was plotted
    assert app._current_plot_data is not None
    assert len(app._current_plot_data) == 3  # 0, 45, 90 deg
    assert set(app._current_plot_data.columns) >= {"angle", "field", "x", "y"}


def test_amr_gui_pause_and_stop_controls():
    """Verify pause toggle and stop delegation to MeasurementRunner."""
    app = make_headless_amr_gui()
    mock_runner = MagicMock()
    app.runner = mock_runner
    app.is_measuring = True

    # Pause
    app.toggle_pause()
    assert app.paused is True
    mock_runner.request_pause.assert_called_with(True)

    # Resume
    app.toggle_pause()
    assert app.paused is False
    mock_runner.request_pause.assert_called_with(False)

    # Stop
    app.stop_measurement()
    mock_runner.request_stop.assert_called_once()


def test_amr_gui_retains_open_connections_when_unsafe(monkeypatch):
    """Verify failing shutdown results in UNSAFE status, retaining connections and blocking close."""
    app = make_headless_amr_gui()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", MagicMock())

    def failing_shutdown(recorder):
        raise RuntimeError("simulated lockin excitation shutdown failure")

    monkeypatch.setattr(AMR, "_safe_shutdown", failing_shutdown)

    with patch("time.sleep", return_value=None):
        app.run_measurement()
        assert app.runner.join(timeout=5)
        app._poll_runner()

    assert app.runner.safety_status == SafetyStatus.UNSAFE
    assert not app.runner.can_close()
    # Instrument connections must NOT be closed on unsafe status!
    assert len(app._instruments) == 4

    # Window close attempt must be deferred/blocked
    finish_mock = MagicMock()
    app._finish_close = finish_mock
    app.on_closing()
    assert not finish_mock.called
    assert len(app._instruments) == 4
    assert app._close_when_safe is True


def test_amr_gui_save_policy(tmp_path):
    """Verify placeholder or empty save_dir sets save=False; valid dir sets save=True."""
    # 1. Placeholder save_dir -> save=False
    app_no_save = make_headless_amr_gui()
    app_no_save.save_dir_entry.get.return_value = r"your\default\save\directory"

    with patch.object(MeasurementRunner, "start") as mock_start:
        app_no_save.run_measurement()
        assert app_no_save.experiment.output_dir is None
        mock_start.assert_called_once_with(save=False, options={"configure_lockin": False})

    # 2. Valid save_dir -> save=True
    app_save = make_headless_amr_gui(tmp_path=tmp_path)
    with patch.object(MeasurementRunner, "start") as mock_start:
        app_save.run_measurement()
        assert Path(app_save.experiment.output_dir) == Path(tmp_path)
        mock_start.assert_called_once_with(save=True, options={"configure_lockin": False})


# ============================================================================
# Fault Regressions for Review Feedback
# ============================================================================

def test_amr_gui_partial_setup_failure_cleans_up_earlier_connections(monkeypatch):
    """Regression: if a later driver constructor fails, earlier connections are cleanly closed."""
    app = make_headless_amr_gui()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", MagicMock())

    closed_instances = []

    class MockDMM:
        def __init__(self, *args, **kwargs):
            pass
        def close(self):
            closed_instances.append(self)

    class MockCalibrator:
        def __init__(self, *args, **kwargs):
            pass
        def close(self):
            closed_instances.append(self)

    def failing_stepper(address):
        raise RuntimeError("simulated stepper motor connection timeout")

    monkeypatch.setattr(gui_mod, "VirtualDMM", MockDMM)
    monkeypatch.setattr(gui_mod, "VirtualCalibrator", MockCalibrator)
    monkeypatch.setattr(gui_mod, "VirtualStepper", failing_stepper)

    app.run_measurement()

    # DMM and Calibrator were created and then cleanly closed on stepper failure
    assert len(closed_instances) == 2
    assert len(app._instruments) == 0
    assert app.runner is None


def test_amr_gui_unsafe_state_blocks_refresh_autodetect_and_stepper_test(monkeypatch):
    """Regression: unsafe shutdown leaves hardware retained, blocking Run, Refresh, Autodetect, and Test Stepper."""
    app = make_headless_amr_gui()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", MagicMock())

    def failing_shutdown(recorder):
        raise RuntimeError("simulated lockin excitation shutdown failure")

    monkeypatch.setattr(AMR, "_safe_shutdown", failing_shutdown)

    with patch("time.sleep", return_value=None):
        app.run_measurement()
        assert app.runner.join(timeout=5)
        app._poll_runner()

    # Hardware is retained in UNSAFE state
    assert app.runner.safety_status == SafetyStatus.UNSAFE
    assert len(app._instruments) == 4
    assert app._busy() is True

    # 1. Run is blocked
    old_runner = app.runner
    app.run_measurement()
    assert app.runner is old_runner

    # 2. Refresh is blocked
    with patch.object(app, "get_visa_resources") as mock_resources:
        app.refresh_instruments()
        assert not mock_resources.called

    # 3. Autodetect is blocked
    with patch("piec.drivers.autodetect.autodetect") as mock_autodetect:
        app.autodetect_instruments()
        assert not mock_autodetect.called

    # 4. Stepper test is blocked
    with patch.object(gui_mod, "Geos_Stepper") as mock_stepper:
        app.test_stepper()
        assert not mock_stepper.called


def test_amr_gui_pre_start_abort_releases_connections_for_not_needed():
    """Regression: Stop-before-start results in NOT_NEEDED; GUI must release connections when can_close() permits."""
    app = make_headless_amr_gui()
    entered, release = threading.Event(), threading.Event()
    original_entry = MeasurementRunner._worker_entry

    def gated_entry(runner_self, *args):
        entered.set()
        assert release.wait(5)
        original_entry(runner_self, *args)

    with patch.object(MeasurementRunner, "_worker_entry", gated_entry):
        app.run_measurement()
    try:
        assert entered.wait(5)
        app.stop_measurement()
        release.set()
        assert app.runner.join(timeout=5)
    finally:
        release.set()

    app._poll_runner()

    assert app.runner.run_state == RunState.ABORTED
    assert app.runner.safety_status == SafetyStatus.NOT_NEEDED
    assert app.runner.can_close()
    # All 4 instrument connections must be cleanly released!
    assert len(app._instruments) == 0


def test_amr_gui_simulation_shutdown_restricts_to_virtual_and_propagates_failures():
    """Regression: simulation excitation shutdown is restricted to VirtualLockin and propagates failures."""
    app = make_headless_amr_gui()

    # 1. No active lockin raises RuntimeError
    app._active_lockin = None
    with pytest.raises(RuntimeError, match="no active lock-in"):
        app._simulation_excitation_shutdown()

    # 2. Non-virtual lockin raises TypeError (never certify physical lockin with simulation shutdown)
    mock_physical = MagicMock(spec=SRS830)
    app._active_lockin = mock_physical
    with pytest.raises(TypeError, match="restricted to VirtualLockin"):
        app._simulation_excitation_shutdown()

    # 3. Virtual lockin error propagates rather than being swallowed
    mock_virtual = MagicMock(spec=VirtualLockin)
    mock_virtual.configure_reference.side_effect = IOError("bus failure during simulation shutdown")
    app._active_lockin = mock_virtual
    with pytest.raises(IOError, match="bus failure during simulation shutdown"):
        app._simulation_excitation_shutdown()
