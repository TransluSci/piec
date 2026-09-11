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
import json
import queue
from unittest.mock import MagicMock, Mock, PropertyMock, patch

import numpy as np
import pandas as pd
import pytest

from piec.drivers.lockin.srs830 import SRS830
from piec.drivers.lockin.virtual_lockin import VirtualLockin
from piec.measurement.contracts import RunState, SafetyAlertEvent, SafetyReport, SafetyStatus, TerminalEvent
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

    class DummyVar:
        def __init__(self, value=False):
            self._val = value
        def get(self):
            return self._val
        def set(self, val):
            self._val = val

    # Lock-in initialization checkbox defaults to False
    app.initialize_lockin_var = DummyVar(False)

    # Frames for settings extraction
    app.static_frame = MagicMock()
    app.static_frame.winfo_children.return_value = []
    app.dynamic_frame = MagicMock()
    app.dynamic_frame.cget.return_value = "AMR MEASUREMENT INPUTS"
    app.dynamic_frame.winfo_children.return_value = []
    app.plot_config_frame = MagicMock()
    app.plot_config_frame.winfo_children.return_value = []

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


# ============================================================================
# Checkpoint 25: AMR GUI Ownership and Interaction Audit Tests
# ============================================================================

def test_amr_gui_preflight_rejects_empty_addresses(monkeypatch):
    """Preflight: empty or whitespace instrument addresses are rejected before opening drivers."""
    app = make_headless_amr_gui()
    mock_error = MagicMock()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", mock_error)

    for entry_name in ["dmm_address_entry", "calibrator_address_entry", "stepper_address_entry", "lockin_address_entry"]:
        getattr(app, entry_name).get.return_value = "   "
        with patch.object(gui_mod, "VirtualDMM") as mock_dmm:
            app.run_measurement()
            assert not mock_dmm.called
            assert mock_error.called
            assert "All instrument addresses" in mock_error.call_args[0][1]
            assert not app._busy()
            assert not app._instruments
            mock_error.reset_mock()
        getattr(app, entry_name).get.return_value = "VIRTUAL"


def test_amr_gui_preflight_rejects_opposing_sweep_direction(monkeypatch):
    """Preflight: angle_step opposing total_angle is rejected before touching hardware."""
    app = make_headless_amr_gui()
    mock_error = MagicMock()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", mock_error)

    # total_angle > 0 but angle_step < 0
    app.dynamic_inputs["total_angle"].get.return_value = "180"
    app.dynamic_inputs["angle_step"].get.return_value = "-10"

    with patch.object(gui_mod, "VirtualDMM") as mock_dmm:
        app.run_measurement()
        assert not mock_dmm.called
        assert mock_error.called
        assert "opposes total_angle" in mock_error.call_args[0][1]
        assert not app._busy()


def test_amr_gui_preflight_rejects_excessive_sweep_intervals(monkeypatch):
    """Preflight: sweep interval count exceeding 1,000,000 is rejected before opening drivers."""
    app = make_headless_amr_gui()
    mock_error = MagicMock()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", mock_error)

    app.dynamic_inputs["total_angle"].get.return_value = "360"
    app.dynamic_inputs["angle_step"].get.return_value = "0.0000001"

    with patch.object(gui_mod, "VirtualDMM") as mock_dmm:
        app.run_measurement()
        assert not mock_dmm.called
        assert mock_error.called
        assert "Sweep exceeds one million" in mock_error.call_args[0][1]


def test_amr_gui_preflight_rejects_simulation_shutdown_on_physical_instruments(monkeypatch):
    """Preflight: simulation shutdown handler cannot be used when any physical instrument is selected."""
    app = make_headless_amr_gui()
    mock_error = MagicMock()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", mock_error)

    app.lockin_address_entry.get.return_value = "GPIB0::8::INSTR"
    app.excitation_shutdown_handler = app._simulation_excitation_shutdown

    with patch.object(gui_mod, "SRS830") as mock_srs:
        app.run_measurement()
        assert not mock_srs.called
        assert mock_error.called
        assert "Simulation excitation shutdown policy cannot be used" in mock_error.call_args[0][1]


def test_amr_gui_save_and_load_settings_preserves_lockin_checkbox(tmp_path, monkeypatch):
    """Settings: save_settings persists initialize_lockin_var; load_settings restores it."""
    app = make_headless_amr_gui()
    settings_file = tmp_path / ".AMRApp_settings.json"
    monkeypatch.setattr(app, "get_settings_file_path", lambda: str(settings_file))

    # Set initialize_lockin to True and save
    app.initialize_lockin_var.set(True)
    app.save_settings()
    assert settings_file.exists()
    content_json = json.loads(settings_file.read_text(encoding="utf-8"))
    dyn = content_json.get("dynamic", {})
    val = dyn.get("AMR MEASUREMENT INPUTS", {}).get("Initialize Lock-in?") if "AMR MEASUREMENT INPUTS" in dyn else dyn.get("Initialize Lock-in?")
    assert val is True

    # Create fresh app, verify default is False, then load settings
    app2 = make_headless_amr_gui()
    assert app2.initialize_lockin_var.get() is False
    monkeypatch.setattr(app2, "get_settings_file_path", lambda: str(settings_file))
    app2.load_settings()
    assert app2.initialize_lockin_var.get() is True


def test_amr_gui_pause_resume_toggles_runner_and_controls():
    """Run/Pause: toggle_pause requests pause on runner, updates button text and status label."""
    app = make_headless_amr_gui()
    # When idle, toggle_pause is safe no-op
    app.toggle_pause()
    assert not app.paused

    pause_btn = MagicMock()
    stop_btn = MagicMock()
    def setup_mock_controls():
        app.pause_button = pause_btn
        app.stop_button = stop_btn
        app.run_button.grid_remove()

    with patch("time.sleep", return_value=None), patch.object(app, "add_control_buttons", side_effect=setup_mock_controls):
        app.run_measurement()
        assert app.runner is not None

        # Pause
        app.toggle_pause()
        assert app.paused is True
        pause_btn.config.assert_called_with(text="RESUME")
        app.status_label.config.assert_called_with(text="Paused")

        # Resume
        app.toggle_pause()
        assert app.paused is False
        pause_btn.config.assert_called_with(text="PAUSE")
        app.status_label.config.assert_called_with(text="Running")

        assert app.runner.join(timeout=5)
        app._poll_runner()


def test_amr_gui_stop_measurement_disables_controls_and_requests_stop():
    """Stop: stop_measurement disables both Stop and Pause buttons, updates status, and requests stop."""
    app = make_headless_amr_gui()
    app.dynamic_inputs["measure_time"].get.return_value = "30.0"

    stop_btn = MagicMock()
    pause_btn = MagicMock()
    def setup_mock_controls():
        app.stop_button = stop_btn
        app.pause_button = pause_btn
        app.run_button.grid_remove()

    with patch.object(app, "add_control_buttons", side_effect=setup_mock_controls):
        app.run_measurement()
        assert app.runner is not None
        assert app.is_measuring is True

        app.stop_measurement()
        stop_btn.config.assert_called_with(state="disabled")
        pause_btn.config.assert_called_with(state="disabled")
        assert any("Stopping" in str(c) for c in app.status_label.config.call_args_list)

        assert app.runner.join(timeout=5)
        app._poll_runner()
        assert not app.is_measuring
        assert app.runner.can_close()
        assert len(app._instruments) == 0


def test_amr_gui_active_window_close_requests_stop_and_defers_close():
    """Close: on_closing while running requests runner close and defers window destruction until worker exits."""
    app = make_headless_amr_gui()
    app.dynamic_inputs["measure_time"].get.return_value = "30.0"

    with patch.object(app, "add_control_buttons", return_value=None):
        app.run_measurement()
        assert app.runner.is_worker_alive

        finish_mock = MagicMock()
        app._finish_close = finish_mock

        app.on_closing()
        assert app.runner.is_closing is True
        assert app._close_when_safe is True
        assert not finish_mock.called
        assert any("Waiting for worker exit" in str(c) for c in app.status_label.config.call_args_list)

        # Let worker terminate cleanly
        assert app.runner.join(timeout=5)
        assert app.runner.can_close()

        # Next poll executes finish_close
        app._poll_runner()
        assert finish_mock.called
        assert len(app._instruments) == 0


def test_amr_gui_start_validation_failure_restores_idle(monkeypatch):
    """Startup failure: runner.start validation failure resets idle state, cleans controls, and closes instruments."""
    app = make_headless_amr_gui()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", MagicMock())

    with patch.object(MeasurementRunner, "start", side_effect=ValueError("simulated validation failure")):
        app.run_measurement()

    assert not app._busy()
    assert not app._awaiting_terminal
    assert not app.is_measuring
    assert len(app._instruments) == 0
    app.status_label.config.assert_called_with(text="Idle")
    app.run_button.config.assert_called_with(state="normal")


@pytest.mark.parametrize("close_fails", [False, True])
def test_autodetect_tracks_connections_through_cleanup(monkeypatch, close_fails):
    app = make_headless_amr_gui()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", MagicMock())
    instrument = MagicMock()
    instrument.instrument.resource_name = "TEST"
    if close_fails:
        instrument.close.side_effect = IOError("close failed")
    with patch("piec.drivers.autodetect.autodetect", side_effect=[instrument, None, None, None]) as detect:
        app.autodetect_instruments()
    instrument.close.assert_called_once()
    assert app._instruments == ([instrument] if close_fails else [])
    assert app._busy() is close_fails
    app.run_button.config.assert_called_with(state="disabled" if close_fails else "normal")
    assert detect.call_count == (1 if close_fails else 4)
    if close_fails:
        app._finish_close = MagicMock()
        app.on_closing()
        app._finish_close.assert_not_called()
        instrument.close.side_effect = None
        app.on_closing()
        app._finish_close.assert_called_once()
        assert app._instruments == []


def test_autodetect_closes_connection_when_address_update_fails(monkeypatch):
    app = make_headless_amr_gui()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", MagicMock())
    instrument = MagicMock()
    app.dmm_address_entry.set.side_effect = ValueError("address update failed")
    with patch("piec.drivers.autodetect.autodetect", return_value=instrument) as detect:
        app.autodetect_instruments()
    instrument.close.assert_called_once()
    detect.assert_called_once()
    assert not app._busy()
    assert not app._instruments


def test_amr_gui_start_failure_retains_active_ownership_if_cannot_close(monkeypatch):
    """Startup failure: start failure when runner.can_close() is False retains active ownership and busy guard."""
    app = make_headless_amr_gui()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", MagicMock())

    runner = MagicMock()
    runner.can_close.return_value = False
    runner.start.side_effect = RuntimeError("error after ownership acquired")

    with patch.object(gui_mod, "MeasurementRunner", return_value=runner):
        app.run_measurement()

    assert app._busy()
    assert app._awaiting_terminal
    assert len(app._instruments) == 4
    assert any("retained" in str(c) for c in app.status_label.config.call_args_list)


def test_amr_gui_terminal_delivery_before_worker_exit_retains_busy_guard():
    """Terminal ordering: terminal event delivery before worker thread exit keeps _busy() True and retains ownership."""
    app = make_headless_amr_gui()
    with patch("time.sleep", return_value=None):
        app.run_measurement()
        assert app.runner.join(timeout=5)

    # Simulate terminal event in control_queue while worker is artificially marked alive
    with patch.object(MeasurementRunner, "is_worker_alive", new_callable=PropertyMock) as mock_alive:
        mock_alive.return_value = True
        app._poll_runner()

        # Terminal event is stored and plot rendered, but ownership is NOT released yet!
        assert app._terminal_event is not None
        assert app._awaiting_terminal is True
        assert app.is_measuring is True
        assert app._busy() is True
        assert len(app._instruments) == 4

        # Now simulate worker exit
        mock_alive.return_value = False
        app._poll_runner()

        assert app._terminal_event is None
        assert app._awaiting_terminal is False
        assert app.is_measuring is False
        assert not app._busy()
        assert len(app._instruments) == 0


def test_amr_gui_unsafe_status_leaves_run_button_disabled(monkeypatch):
    """UNSAFE status: run button remains disabled and status label reflects unsafe retention."""
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
    assert app._busy() is True
    app.run_button.config.assert_called_with(state="disabled")
    assert any("connections retained" in str(c) for c in app.status_label.config.call_args_list)


def test_amr_gui_safety_alert_event_shows_dialog_and_updates_status(monkeypatch):
    """Safety alert: SafetyAlertEvent displays an error dialog and updates status label."""
    app = make_headless_amr_gui()
    mock_error = MagicMock()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", mock_error)

    alert = SafetyAlertEvent(
        run_id="test_run",
        generation=1,
        safety_status=SafetyStatus.UNSAFE,
        report=SafetyReport(status=SafetyStatus.UNSAFE),
        message="Dangerous overvoltage on excitation line",
    )
    app.runner = MagicMock()
    app.runner.control_queue.get_nowait.side_effect = [alert, queue.Empty]
    app.runner.display_queue.get_nowait.side_effect = queue.Empty
    app.runner.is_worker_alive = True
    app.runner.can_close.return_value = False

    app._poll_runner()

    assert mock_error.called
    assert "Dangerous overvoltage" in str(mock_error.call_args)
    assert any("Hardware unsafe" in str(c) for c in app.status_label.config.call_args_list)


def test_amr_gui_autodetect_exception_does_not_crash_gui(monkeypatch):
    """Auxiliary actions: autodetect driver scan exception is caught and displays error dialog."""
    app = make_headless_amr_gui()
    mock_error = MagicMock()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", mock_error)

    with patch("piec.drivers.autodetect.autodetect", side_effect=RuntimeError("VISA bus enumeration timeout")):
        app.autodetect_instruments()

    assert mock_error.called
    assert "Autodetect failed" in str(mock_error.call_args)
    assert not app._busy()


def test_amr_gui_test_stepper_rejects_empty_address(monkeypatch):
    """Auxiliary actions: test_stepper with blank address shows error dialog and does not attempt connection."""
    app = make_headless_amr_gui()
    mock_error = MagicMock()
    monkeypatch.setattr(gui_mod.messagebox, "showerror", mock_error)

    app.stepper_address_entry.get.return_value = "   "
    with patch.object(gui_mod, "VirtualStepper") as mock_step:
        app.test_stepper()
        assert not mock_step.called
        assert mock_error.called
        assert "No address selected" in str(mock_error.call_args)
        assert not app._busy()
