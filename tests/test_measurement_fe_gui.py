"""
Tests for FE GUI interaction and ownership hardening (Checkpoint 21).

Verifies that the FE GUI (FEMeasurementApp) fulfills the standardized GUI contract
for both HysteresisLoop and ThreePulsePund:
- Single hardware writer rule (busy state blocks concurrent runs, VISA refresh, dynamic switching);
- Parameter validation occurs strictly before any instrument instantiation/connection;
- Virtual instrument selection and mixed virtual/physical rejection;
- GUI connection ownership and safe close gating (instruments closed only when worker exited and safety confirmed);
- Unsafe shutdown retains open connections, displays alert, and blocks window close;
- Window close coordination with non-blocking polling and cooperative stop;
- Stop-before-start zero-I/O abort;
- Save policy (save=False when save_dir is None/placeholder, save_plots suppressed);
- Main-thread plotting with display queue draining, plain-column mappings, and unit-derived axis labels.
"""

import importlib.util
import threading
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
import numpy as np
import pandas as pd
import pytest

from piec.measurement.contracts import RunState, SafetyAlertEvent, SafetyStatus, TerminalEvent
from piec.measurement.discrete_waveform import HysteresisLoop, ThreePulsePund
from piec.measurement.runner import MeasurementRunner

ROOT = Path(__file__).resolve().parents[1]
GUI_PATH = ROOT / "Measurements" / "Ferroelectric Testing" / "FE_testing_GUI.py"

def _load_fe_gui_module():
    spec = importlib.util.spec_from_file_location("fe_gui_module", GUI_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

gui_mod = _load_fe_gui_module()
FEMeasurementApp = gui_mod.FEMeasurementApp
DEFAULTS = gui_mod.DEFAULTS


def test_fe_gui_imports_and_structure():
    """Verify FE GUI imports target components without legacy shims."""
    assert GUI_PATH.is_file()

    with open(GUI_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    assert "from piec.measurement import MeasurementRunner" in content
    assert "apply_and_capture_waveform" not in content
    assert "_process_raw_hyst_file" not in content
    assert "_process_raw_3pp_file" not in content


def make_headless_fe_gui(meas_type="HysteresisLoop", tmp_path=None):
    """Construct a fully populated headless FEMeasurementApp for interaction testing."""
    app = FEMeasurementApp.__new__(FEMeasurementApp)
    app.root = MagicMock()
    app.root.winfo_exists.return_value = True
    app.experiment = None
    app.runner = None
    app._terminal_event = None
    app._awaiting_terminal = False
    app._closing = False
    app._close_when_safe = False
    app._instruments = []
    app._poll_id = None
    app._plot_frame = None
    app._plot_units = {}
    app._saved_dynamic = {}

    app.run_button = MagicMock()
    app.stop_button = MagicMock()
    app.status_label = MagicMock()

    app.measurement_type = MagicMock()
    app.measurement_type.get.return_value = meas_type

    app.awg_address_entry = MagicMock()
    app.awg_address_entry.get.return_value = "VIRTUAL"
    app.osc_address_entry = MagicMock()
    app.osc_address_entry.get.return_value = "VIRTUAL"

    app.save_dir_entry = MagicMock()
    app.save_dir_entry.get.return_value = str(tmp_path) if tmp_path else ""

    app.vdiv_entry = MagicMock()
    app.vdiv_entry.get.return_value = "0.01"

    app.area_entry = MagicMock()
    app.area_entry.get.return_value = "1.0e-5**2"

    app.timeshift_entry = MagicMock()
    app.timeshift_entry.get.return_value = "100"

    app.auto_timeshift_entry = MagicMock()
    app.auto_timeshift_entry.get.return_value = False

    app.saveplots_entry = MagicMock()
    app.saveplots_entry.get.return_value = False

    if meas_type == "HysteresisLoop":
        app.dynamic_inputs = {
            "frequency": MagicMock(get=MagicMock(return_value="1.0e6")),
            "amplitude": MagicMock(get=MagicMock(return_value="1.0")),
            "offset": MagicMock(get=MagicMock(return_value="0.0")),
            "n_cycles": MagicMock(get=MagicMock(return_value="2")),
        }
        app.x_axis = MagicMock()
        app.x_axis.get.return_value = "applied voltage (V)"
        app.y_axis = MagicMock()
        app.y_axis.get.return_value = "polarization (uC/cm^2)"
    elif meas_type == "ThreePulsePund":
        app.dynamic_inputs = {
            "reset_amp": MagicMock(get=MagicMock(return_value="1.0")),
            "reset_width": MagicMock(get=MagicMock(return_value="1.0e-7")),
            "reset_delay": MagicMock(get=MagicMock(return_value="1.0e-7")),
            "p_u_amp": MagicMock(get=MagicMock(return_value="1.0")),
            "p_u_width": MagicMock(get=MagicMock(return_value="1.0e-7")),
            "p_u_delay": MagicMock(get=MagicMock(return_value="1.0e-7")),
            "offset": MagicMock(get=MagicMock(return_value="0.0")),
        }
        app.x_axis = MagicMock()
        app.x_axis.get.return_value = "time (s)"
        app.y_axis = MagicMock()
        app.y_axis.get.return_value = "dP (uC/cm^2)"

    app.dynamic_frame = MagicMock()
    app.dynamic_frame.cget.return_value = f"{meas_type} INPUTS"
    app.dynamic_frame.winfo_children.return_value = []

    app.ax = MagicMock()
    app.canvas = MagicMock()

    return app


def test_fe_gui_dynamic_axis_columns_for_hyst_and_pund():
    """Verify switching between Hysteresis and PUND dynamically updates axis choices."""
    app = make_headless_fe_gui("HysteresisLoop")
    app.x_axis = {}
    app.y_axis = {}

    # Update to Hysteresis
    app.update_dynamic_inputs(None)
    assert "applied voltage (V)" in app.x_axis["values"]
    assert "polarization (uC/cm^2)" in app.y_axis["values"]
    assert "dP (uC/cm^2)" not in app.x_axis["values"]

    # Switch to PUND
    app.measurement_type.get.return_value = "ThreePulsePund"
    app.update_dynamic_inputs(None)
    assert "dP (uC/cm^2)" in app.x_axis["values"]
    assert "P^ (uC/cm^2)" in app.y_axis["values"]
    assert "P* (uC/cm^2)" in app.y_axis["values"]


@pytest.mark.parametrize("bad_field,bad_val", [
    ("vdiv", "invalid"),
    ("vdiv", "-0.01"),
    ("vdiv", "0.0"),
    ("vdiv", "nan"),
    ("area", "syntax error"),
    ("area", "-1e-6"),
    ("area", "0.0"),
    ("area", "nan"),
    ("time_offset", "-10"),
    ("time_offset", "nan"),
    ("time_offset", "bad"),
])
def test_fe_gui_static_validation_precedes_instrument_creation(monkeypatch, bad_field, bad_val):
    """Verify static parameter validation fails before creating any hardware connections."""
    app = make_headless_fe_gui("HysteresisLoop")
    monkeypatch.setattr(gui_mod.messagebox, "showerror", MagicMock())

    if bad_field == "vdiv":
        app.vdiv_entry.get.return_value = bad_val
    elif bad_field == "area":
        app.area_entry.get.return_value = bad_val
    elif bad_field == "time_offset":
        app.timeshift_entry.get.return_value = bad_val

    # Ensure no instrument classes are instantiated
    with patch.object(gui_mod, "VirtualAwg") as mock_awg, \
         patch.object(gui_mod, "VirtualScope") as mock_osc:
        app.run_measurement()
        assert not mock_awg.called
        assert not mock_osc.called
        assert len(app._instruments) == 0
        assert app.runner is None


@pytest.mark.parametrize("meas_type,bad_param,bad_val", [
    ("HysteresisLoop", "frequency", "0"),
    ("HysteresisLoop", "frequency", "-1000"),
    ("HysteresisLoop", "frequency", "nan"),
    ("HysteresisLoop", "amplitude", "0"),
    ("HysteresisLoop", "amplitude", "nan"),
    ("HysteresisLoop", "offset", "nan"),
    ("HysteresisLoop", "n_cycles", "0"),
    ("HysteresisLoop", "n_cycles", "-1"),
    ("ThreePulsePund", "reset_amp", "0"),
    ("ThreePulsePund", "reset_amp", "nan"),
    ("ThreePulsePund", "reset_width", "0"),
    ("ThreePulsePund", "reset_width", "-1e-7"),
    ("ThreePulsePund", "reset_delay", "0"),
    ("ThreePulsePund", "reset_delay", "-1e-7"),
    ("ThreePulsePund", "p_u_amp", "nan"),
    ("ThreePulsePund", "p_u_width", "0"),
    ("ThreePulsePund", "p_u_width", "-1e-7"),
    ("ThreePulsePund", "p_u_delay", "0"),
    ("ThreePulsePund", "p_u_delay", "-1e-7"),
    ("ThreePulsePund", "offset", "nan"),
])
def test_fe_gui_dynamic_validation_precedes_instrument_creation(monkeypatch, meas_type, bad_param, bad_val):
    """Verify dynamic parameter validation fails before creating any hardware connections."""
    app = make_headless_fe_gui(meas_type)
    monkeypatch.setattr(gui_mod.messagebox, "showerror", MagicMock())
    app.dynamic_inputs[bad_param].get.return_value = bad_val

    with patch.object(gui_mod, "VirtualAwg") as mock_awg, \
         patch.object(gui_mod, "VirtualScope") as mock_osc:
        app.run_measurement()
        assert not mock_awg.called
        assert not mock_osc.called
        assert len(app._instruments) == 0
        assert app.runner is None


def test_fe_gui_rejects_mixed_or_empty_addresses(monkeypatch):
    """Verify mixed virtual/physical addresses and empty addresses are rejected pre-connection."""
    monkeypatch.setattr(gui_mod.messagebox, "showerror", MagicMock())

    # Empty AWG address
    app = make_headless_fe_gui("HysteresisLoop")
    app.awg_address_entry.get.return_value = ""
    app.run_measurement()
    assert len(app._instruments) == 0
    assert app.runner is None

    # Mixed AWG virtual and Scope physical
    app = make_headless_fe_gui("HysteresisLoop")
    app.awg_address_entry.get.return_value = "VIRTUAL"
    app.osc_address_entry.get.return_value = "USB0::0x0957::0x17A6::MY52160123::INSTR"
    app.run_measurement()
    assert len(app._instruments) == 0
    assert app.runner is None

    # Mixed AWG physical and Scope virtual
    app = make_headless_fe_gui("HysteresisLoop")
    app.awg_address_entry.get.return_value = "USB0::0x0957::0x17A6::MY52160123::INSTR"
    app.osc_address_entry.get.return_value = "VIRTUAL"
    app.run_measurement()
    assert len(app._instruments) == 0
    assert app.runner is None


def test_fe_gui_runs_hysteresis_cleanly():
    """Verify Hysteresis measurement runs via MeasurementRunner, completes, and cleans up."""
    app = make_headless_fe_gui("HysteresisLoop")
    app.run_measurement()

    assert app.runner is not None
    assert app.runner._worker_thread.daemon is False
    assert len(app._instruments) == 2

    # Allow run to complete
    assert app.runner.join(timeout=5)
    app._poll_events()

    assert app.runner.run_state == RunState.COMPLETED
    assert app.runner.safety_status == SafetyStatus.SAFE
    assert len(app._instruments) == 0
    assert app.run_button.config.called
    assert app.stop_button.config.called
    assert app.ax.plot.called
    assert app.timeshift_entry.delete.called
    assert app.timeshift_entry.insert.called


def test_fe_gui_runs_pund_cleanly():
    """Verify PUND measurement runs via MeasurementRunner, completes, and cleans up."""
    app = make_headless_fe_gui("ThreePulsePund")
    app.run_measurement()

    assert app.runner is not None
    assert app.runner._worker_thread.daemon is False
    assert len(app._instruments) == 2

    # Allow run to complete
    assert app.runner.join(timeout=5)
    app._poll_events()

    assert app.runner.run_state == RunState.COMPLETED
    assert app.runner.safety_status == SafetyStatus.SAFE
    assert len(app._instruments) == 0
    assert app.ax.plot.called


def test_fe_gui_save_policy(tmp_path):
    """Verify save policies: placeholder/empty save_dir sets save=False and suppresses plots."""
    # 1. Default placeholder save_dir -> save=False
    app_no_save = make_headless_fe_gui("HysteresisLoop")
    app_no_save.save_dir_entry.get.return_value = r"your\default\save\directory"
    app_no_save.saveplots_entry.get.return_value = True

    with patch.object(MeasurementRunner, "start") as mock_start:
        app_no_save.run_measurement()
        assert app_no_save.experiment.output_dir is None
        assert app_no_save.experiment.save_plots is False
        mock_start.assert_called_once_with(save=False)

    # 2. Valid save_dir -> save=True
    app_save = make_headless_fe_gui("HysteresisLoop", tmp_path=tmp_path)
    with patch.object(MeasurementRunner, "start") as mock_start:
        app_save.run_measurement()
        assert Path(app_save.experiment.output_dir) == Path(tmp_path)
        mock_start.assert_called_once_with(save=True)


@pytest.mark.parametrize("meas_type", ["HysteresisLoop", "ThreePulsePund"])
def test_fe_gui_stop_before_start(meas_type):
    """Verify Stop-before-start aborts with zero hardware I/O."""
    app = make_headless_fe_gui(meas_type)
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
        # All measurement instrument I/O is behind these lifecycle hooks.
        # Install spies while execution is gated, before requesting Stop.
        with patch.object(app.experiment, "_configure_instruments") as configure, \
             patch.object(app.experiment, "_capture_data") as capture, \
             patch.object(app.experiment, "_safe_shutdown") as shutdown:
            app.stop_measurement()
            release.set()
            assert app.runner.join(timeout=5)
            configure.assert_not_called()
            capture.assert_not_called()
            shutdown.assert_not_called()
    finally:
        release.set()
        app.stop_measurement()
        app.runner.join(timeout=5)
    app._poll_events()

    assert app.runner.run_state == RunState.ABORTED
    assert app.runner.safety_status == SafetyStatus.NOT_NEEDED
    assert app.runner.can_close()
    assert len(app._instruments) == 0


def test_fe_gui_active_close_defers_until_worker_exit():
    """Verify active close requests stop and defers destruction until worker exits and safe."""
    app = make_headless_fe_gui("HysteresisLoop")
    app.dynamic_inputs["n_cycles"].get.return_value = "50"

    app.run_measurement()
    assert app.runner.is_worker_alive

    finish_mock = MagicMock()
    app._finish_close = finish_mock

    # Request window close while measuring
    app.on_closing()
    assert app.runner.is_closing is True
    assert app._close_when_safe is True
    assert not finish_mock.called

    # Wait for cooperative stop to complete
    assert app.runner.join(timeout=5)
    assert app.runner.can_close()

    # Next poll executes deferred finish close
    app._poll_events()
    assert finish_mock.called
    assert len(app._instruments) == 0


def test_fe_gui_retains_connections_and_blocks_close_when_unsafe(monkeypatch):
    """Verify unsafe shutdown retains open connections, alerts user, and blocks window close."""
    app = make_headless_fe_gui("HysteresisLoop")
    monkeypatch.setattr(gui_mod.messagebox, "showerror", MagicMock())

    def failing_shutdown(recorder):
        raise RuntimeError("simulated hardware safing failure")

    monkeypatch.setattr(HysteresisLoop, "_safe_shutdown", failing_shutdown)

    app.run_measurement()
    assert app.runner.join(timeout=5)

    # Deliver terminal events
    app._poll_events()

    assert app.runner.safety_status == SafetyStatus.UNSAFE
    assert not app.runner.can_close()
    # Instruments must NOT be closed
    assert len(app._instruments) == 2

    # Attempt window close
    finish_mock = MagicMock()
    app._finish_close = finish_mock
    app.on_closing()

    # Window close must be blocked
    assert not finish_mock.called
    assert len(app._instruments) == 2
    assert app._close_when_safe is True


def test_fe_gui_single_hardware_writer_blocks_busy_actions():
    """Verify callbacks and actions reject execution while the runner is active."""
    app = make_headless_fe_gui("HysteresisLoop")
    app.run_measurement()
    assert app._busy()

    # 1. Concurrent run_measurement is blocked
    old_runner = app.runner
    app.run_measurement()
    assert app.runner is old_runner

    # 2. VISA refresh is blocked
    with patch.object(app, "get_visa_resources") as mock_visa:
        app.refresh_instruments()
        assert not mock_visa.called

    # 3. Dynamic measurement type change is blocked
    app.select_measurement("ThreePulsePund")
    assert app.measurement_type.set.call_count == 0

    # 4. update_dynamic_inputs is blocked
    app.update_dynamic_inputs(None)
    assert not app.dynamic_frame.config.called

    # Clean up
    app.stop_measurement()
    assert app.runner.join(timeout=5)
    app._poll_events()


def test_fe_gui_plot_data_mapping_and_unit_labels():
    """Verify in-memory plot_data maps columns and applies unit labels properly."""
    app = make_headless_fe_gui("HysteresisLoop")
    app.experiment = MagicMock()
    app._plot_units = {
        "time": "s",
        "voltage": "V",
        "applied_voltage": "V",
        "polarization": "uC/cm^2",
        "delta_polarization": "uC/cm^2",
    }

    # 1. Test raw acquisition fallback
    raw_df = pd.DataFrame({"time": [1e-9, 2e-9], "voltage": [0.1, 0.2]})
    app._plot_frame = raw_df
    app.x_axis.get.return_value = "applied voltage (V)"
    app.y_axis.get.return_value = "polarization (uC/cm^2)"
    app.plot_data()

    # Must fall back to time vs voltage during raw streaming
    assert app.ax.plot.called
    app.ax.set_xlabel.assert_called_with("time (s)")
    app.ax.set_ylabel.assert_called_with("voltage (V)")

    # 2. Test processed data plotting
    app.ax.reset_mock()
    proc_df = pd.DataFrame({
        "time": [1e-9, 2e-9],
        "voltage": [0.1, 0.2],
        "applied_voltage": [1.0, 2.0],
        "polarization": [5.0, 10.0],
    })
    app._plot_frame = proc_df
    app.plot_data()

    app.ax.set_xlabel.assert_called_with("applied_voltage (V)")
    app.ax.set_ylabel.assert_called_with("polarization (uC/cm^2)")


def test_fe_gui_close_instruments_deduplication():
    """Verify _close_instruments calls close() once even if duplicate references exist."""
    app = make_headless_fe_gui("HysteresisLoop")
    inst = MagicMock()
    app._instruments = [inst, inst]

    app._close_instruments()
    assert inst.close.call_count == 1
    assert len(app._instruments) == 0
