"""
Consolidated GUI Tests for All Measurement Applications.

Consolidates:
- DC IV Sweep GUI (IVSweepApp)
- MOKE GUI (MokeMeasurementApp)
- FE Hysteresis & PUND GUI (FEMeasurementApp)
- FE GUI state retention & combobox behavior
- AMR GUI (AMRMeasurementApp)

Verifies:
- Headless instantiation and Tk widget mocking.
- Parameter validation before hardware connection.
- Virtual instrument execution through GUI runner.
- Live display queue consumption and terminal plot updates.
- Pause/resume and stop controls.
- Safe closure coordination and deferral while worker active.
- Unsafe hardware status blocking closure and disabling run controls.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from unittest.mock import MagicMock, Mock, PropertyMock, call, patch
import warnings

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
import pytest

from piec.analysis.field_calibration import FieldCalibration
from piec.analysis.hysteresis import (
    STANDARD_HYSTERESIS_COLUMNS,
    STANDARD_HYSTERESIS_UNITS,
)
from piec.analysis.pund import (
    STANDARD_PUND_COLUMNS,
    STANDARD_PUND_UNITS,
)
from piec.drivers.dmm.virtual_dmm import VirtualDMM
from piec.drivers.lockin.srs830 import SRS830
from piec.drivers.lockin.virtual_lockin import VirtualLockin
from piec.drivers.sourcemeter.virtual_sourcemeter import VirtualSourcemeter
from piec.measurement import (
    BaseMeasurement,
    CloseCoordinationStatus,
    HardwareSafetyError,
    MeasurementRunner,
    RunState,
    SafetyAlertEvent,
    SafetyReport,
    SafetyStatus,
    TerminalEvent,
)
from piec.measurement.amr import AMR
from piec.measurement.discrete_waveform import HysteresisLoop, ThreePulsePund
from piec.measurement.iv_sweep import IVSweep
from piec.measurement.moke import MokeMeasurement, MokeSnapshot
from Measurements.DCIV.IV_sweep_GUI import IVSweepApp
from tests.fixtures.virtual_setups import (
    amr_bench,
    fe_bench,
    iv_bench,
    moke_bench,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ==============================================================================
# Part 1: IV Sweep GUI (IVSweepApp)
# ==============================================================================
def test_iv_sweep_gui_imports_and_structure():
    """Verify IV Sweep GUI imports target components without legacy shims."""
    gui_path = REPO_ROOT / "Measurements" / "DCIV" / "IV_sweep_GUI.py"
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

# ==============================================================================
# Part 2: MOKE GUI (MokeMeasurementApp)
# ==============================================================================
MOKE_GUI_PATH = REPO_ROOT / "Measurements" / "MOKE" / "MOKE_GUI.py"
MOKE_NOTEBOOK_PATH = REPO_ROOT / "Measurements" / "MOKE" / "MOKE_testing.ipynb"

def _load_moke_gui_module():
    spec = importlib.util.spec_from_file_location("piec_moke_gui", MOKE_GUI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_moke_gui_imports_without_starting_tk_mainloop():
    module = _load_moke_gui_module()
    assert module.MokeMeasurementApp.__name__ == "MokeMeasurementApp"


def test_moke_gui_output_cycle_is_closed_and_has_requested_size():
    cycle = _load_moke_gui_module().make_output_cycle(-2, 3, 21)
    assert len(cycle) == 21
    assert cycle[0] == cycle[-1] == -2
    assert cycle.max() == 3


def test_gui_virtual_setup_runs_the_normal_measurement_and_generates_a_loop():
    module = _load_moke_gui_module()
    calibration = FieldCalibration([(-5, -500), (0, 0), (5, 500)])
    source = VirtualSourcemeter("VIRTUAL")
    detector = VirtualDMM("VIRTUAL")
    module.connect_virtual_detector(
        source, detector, calibration, noise=0.0, seed=0
    )
    outputs = module.make_output_cycle(-5, 5, 41)
    measurement = MokeMeasurement(
        sourcemeter=source,
        dmm=detector,
        calibration=calibration,
        output_values=outputs,
        compliance=0.01,
        max_output_step=1.0,
        dwell_time=0.0,
        ramp_delay=0.0,
        n_cycles=2,
        average_cycles=2,
    )

    data = measurement.run_experiment(save=False)

    assert measurement.completed_cycles == 2
    assert len(data) == 2 * len(outputs)
    assert np.ptp(data["detector_voltage"]) > 0.03
    assert source.state["output_on"] is False


def test_moke_gui_plot_snapshot_labels_combine_plain_name_and_unit():
    module = _load_moke_gui_module()
    mock_app = Mock()
    mock_app.show_raw.get.return_value = True
    mock_app.show_last.get.return_value = True
    mock_app.show_average.get.return_value = True
    mock_app.geometry_entry.get.return_value = "in-plane"
    mock_app.ax.lines = []

    calibration = FieldCalibration([(-5, -500), (0, 0), (5, 500)], field_unit="Oe")
    source = VirtualSourcemeter("VIRTUAL")
    detector = VirtualDMM("VIRTUAL")
    meas = MokeMeasurement(
        sourcemeter=source, dmm=detector, calibration=calibration,
        output_values=[-5, 0, 5, 0, -5], compliance=0.01, max_output_step=5.0,
        dwell_time=0.0, ramp_delay=0.0,
    )
    mock_app.experiment = meas

    # 1. Calibrated field mode
    snap_cal = MokeSnapshot(
        raw=pd.DataFrame({"field_calibrated": [0.0], "detector_voltage": [0.5]}),
        last_cycle=pd.DataFrame(),
        cycle_average=pd.DataFrame(),
        completed_cycles=0,
        field_column="field_calibrated",
    )
    module.MokeMeasurementApp._plot_snapshot(mock_app, snap_cal)
    mock_app.ax.set_xlabel.assert_called_once_with("field_calibrated (Oe)")
    mock_app.ax.set_ylabel.assert_called_once_with("detector_voltage (V)")

    # 2. Measured field mode
    meas.field_reader = lambda: 50.0
    meas.field_reader_unit = "Oe"
    snap_meas = MokeSnapshot(
        raw=pd.DataFrame({"field_measured": [50.0], "detector_voltage": [0.5]}),
        last_cycle=pd.DataFrame(),
        cycle_average=pd.DataFrame(),
        completed_cycles=0,
        field_column="field_measured",
    )
    mock_app.ax.reset_mock()
    module.MokeMeasurementApp._plot_snapshot(mock_app, snap_meas)
    mock_app.ax.set_xlabel.assert_called_once_with("field_measured (Oe)")
    mock_app.ax.set_ylabel.assert_called_once_with("detector_voltage (V)")


def test_moke_notebook_code_cells_compile():
    notebook = json.loads(MOKE_NOTEBOOK_PATH.read_text(encoding="utf-8"))
    for index, cell in enumerate(notebook["cells"]):
        if cell.get("cell_type") == "code":
            compile(
                "".join(cell.get("source", [])),
                f"{MOKE_NOTEBOOK_PATH}:cell-{index}",
                "exec",
            )


def make_headless_moke_gui(tmp_path=None):
    """Construct a fully populated headless MokeMeasurementApp for interaction testing."""
    module = _load_moke_gui_module()
    app = module.MokeMeasurementApp.__new__(module.MokeMeasurementApp)
    app.root = Mock()
    app.root.winfo_exists.return_value = True
    app.experiment = None
    app.runner = None
    app._terminal_event = None
    app.is_measuring = False
    app._close_when_safe = False
    app._instruments = []
    app._poll_events_id = None
    app._geometry_settings = {}
    app._selected_geometry = "in-plane"
    app._shutdown_handlers = {}

    app.run_button = Mock()
    app.stop_button = Mock()
    app.status_label = Mock()
    app.source_address_entry = Mock(get=Mock(return_value="VIRTUAL"))
    app.detector_address_entry = Mock(get=Mock(return_value="VIRTUAL"))
    app.field_reader_address_entry = Mock(get=Mock(return_value="NONE"))
    app.geometry_entry = Mock(get=Mock(return_value="in-plane"))
    cal_path = Path(__file__).resolve().parents[1] / "Measurements" / "MOKE" / "example_calibration.csv"
    app.calibration_entry = Mock(get=Mock(return_value=str(cal_path)))
    app.source_channel_entry = Mock(get=Mock(return_value=""))
    app.field_per_volt_entry = Mock(get=Mock(return_value="1.0"))
    app.field_offset_entry = Mock(get=Mock(return_value="0.0"))
    app.save_dir_entry = Mock(get=Mock(return_value=str(tmp_path or Path.cwd())))

    app.dynamic_inputs = {
        "output_min": Mock(get=Mock(return_value="-2.0")),
        "output_max": Mock(get=Mock(return_value="2.0")),
        "points_per_cycle": Mock(get=Mock(return_value="5")),
        "n_cycles": Mock(get=Mock(return_value="1")),
        "average_cycles": Mock(get=Mock(return_value="1")),
        "compliance": Mock(get=Mock(return_value="0.01")),
        "max_output_step": Mock(get=Mock(return_value="2.0")),
        "dwell_time": Mock(get=Mock(return_value="0.0")),
        "ramp_delay": Mock(get=Mock(return_value="0.0")),
        "raw_window_points": Mock(get=Mock(return_value="100")),
    }
    app.show_raw = Mock(get=Mock(return_value=True))
    app.show_last = Mock(get=Mock(return_value=True))
    app.show_average = Mock(get=Mock(return_value=True))
    app.save_data = Mock(get=Mock(return_value=False))

    app.ax = Mock()
    app.ax.lines = []
    app.canvas = Mock()
    return app, module


def test_moke_gui_controls_before_first_run_are_safe():
    """Verify trace checkbuttons, geometry entry, STOP, and redraw are harmless no-ops before run."""
    app, module = make_headless_moke_gui()
    assert app.experiment is None

    app._redraw_current()
    app.stop_measurement()
    app.geometry_entry.set = Mock()
    app.geometry_entry.set("out-of-plane")
    app._redraw_current()

    app.ax.plot.assert_not_called()
    app.canvas.draw_idle.assert_not_called()


def test_moke_gui_single_hardware_writer_rule():
    """Verify callbacks reject hardware actions when is_measuring is True."""
    app, module = make_headless_moke_gui()
    app.is_measuring = True

    with patch.object(app, "get_visa_resources") as mock_visa:
        app.refresh_instruments()
        assert not mock_visa.called

    with patch.object(module.filedialog, "askopenfilename") as mock_dialog:
        app.browse_calibration()
        assert not mock_dialog.called

    with patch.object(app, "_create_experiment") as mock_create:
        app.run_measurement()
        assert not mock_create.called


def test_moke_gui_stop_before_start():
    """Verify Stop-before-start zero-I/O abort and clean instrument cleanup."""
    app, module = make_headless_moke_gui()
    original_run = MokeMeasurement.run_experiment

    def stopping_run(measurement, *args, **kwargs):
        # Reservation exists, but the execution wrapper has not begun I/O.
        app.stop_measurement()
        return original_run(measurement, *args, **kwargs)

    with patch.object(MokeMeasurement, "run_experiment", stopping_run):
        app.run_measurement()
        assert app.runner.join(timeout=5)
    app._poll_events()

    assert app.runner.run_state == RunState.ABORTED
    assert app.runner.safety_status == SafetyStatus.NOT_NEEDED
    assert not app.is_measuring
    assert app.runner.can_close()
    assert len(app._instruments) == 0


def test_moke_gui_active_close_requests_stop_and_defers_close():
    """Verify active close requests cooperative stop and defers destruction until worker exit."""
    app, module = make_headless_moke_gui()
    app.dynamic_inputs["dwell_time"].get.return_value = "0.5"
    app.dynamic_inputs["points_per_cycle"].get.return_value = "11"

    app.run_measurement()
    assert app.runner.is_worker_alive

    finish_mock = Mock()
    app._finish_close = finish_mock

    app.on_closing()
    assert app.runner.is_closing is True
    assert app._close_when_safe is True
    assert not finish_mock.called

    assert app.runner.join(timeout=5)
    assert app.runner.can_close()

    app._poll_events()
    assert finish_mock.called
    assert len(app._instruments) == 0


def test_moke_gui_deferred_close_releases_connections_after_safety_retry(monkeypatch):
    """Verify deferred close retains connections while unsafe and releases them after retry."""
    app, module = make_headless_moke_gui()
    monkeypatch.setattr(module.messagebox, "showerror", Mock())

    def failing_shutdown(recorder):
        raise RuntimeError("failing hardware shutdown")

    monkeypatch.setattr(MokeMeasurement, "_safe_shutdown", failing_shutdown)

    app.run_measurement()
    assert app.runner.join(timeout=5)
    assert app.runner.safety_status == SafetyStatus.UNSAFE
    app._poll_events()

    instruments_before = list(app._instruments)
    assert len(instruments_before) >= 2

    finish_mock = Mock()
    app._finish_close = finish_mock

    # Close is requested and deferred because safety is UNSAFE
    app.on_closing()
    assert not finish_mock.called
    assert len(app._instruments) >= 2

    # Now retry safing with successful shutdown
    monkeypatch.undo()
    app.experiment.safe_shutdown()
    assert app.runner.can_close()

    app._poll_events()
    assert finish_mock.called
    assert len(app._instruments) == 0


def test_moke_gui_reports_recovery_paths_from_failed_save_record(monkeypatch, tmp_path, capsys):
    """Verify failed save publication reports recoverable staging paths from RunRecord metadata."""
    from piec.measurement import persistence
    app, module = make_headless_moke_gui(tmp_path=tmp_path)
    app.save_data.get.return_value = True
    monkeypatch.setattr(module.messagebox, "showerror", Mock())
    monkeypatch.setattr(
        persistence, "atomic_publish_no_replace",
        Mock(side_effect=OSError("filesystem publication failed")),
    )
    app.run_measurement()
    assert app.runner.join(timeout=5)

    record = app.experiment.last_run_record
    paths = record.metadata["recoverable_staging_paths"]
    assert record.state == RunState.FAILED
    assert paths and all(Path(p).is_file() for p in paths)

    app._poll_events()
    output = capsys.readouterr().out
    assert "Recoverable data staging paths:" in output
    assert all(p in output for p in paths) or str(paths) in output


def test_moke_gui_geometry_change_preserves_acquisition_title():
    """Selecting the next setup must never relabel previously acquired data."""
    app, module = make_headless_moke_gui()
    snap = MokeSnapshot(
        raw=pd.DataFrame({"field_calibrated": [0.0, 1.0], "detector_voltage": [0.1, 0.2]}),
        last_cycle=pd.DataFrame(),
        cycle_average=pd.DataFrame(),
        completed_cycles=1,
        field_column="field_calibrated",
        geometry="in-plane",
    )
    app._plot_snapshot(snap)
    app.ax.set_title.assert_called_with("MOKE loop: in-plane")

    app.geometry_entry.get.return_value = "out-of-plane"
    app._redraw_current()
    app.ax.set_title.assert_called_with("MOKE loop: in-plane")


def test_geometry_profiles_restore_independent_settings():
    app, module = make_headless_moke_gui()
    # Give the mocked widgets real value storage for selection/restoration.
    for widget in [app.geometry_entry, *app._profile_widgets().values()]:
        widget.set.side_effect = lambda value, w=widget: setattr(w.get, "return_value", str(value))
        widget.insert.side_effect = lambda index, value, w=widget: w.set(value)
    app.source_address_entry.set("physical-source")
    app.dynamic_inputs["compliance"].set("0.002")
    app.geometry_entry.set("out-of-plane")
    app._on_geometry_changed()
    assert app.source_address_entry.get() == "VIRTUAL"
    app.dynamic_inputs["compliance"].set("0.003")
    app.geometry_entry.set("in-plane")
    app._on_geometry_changed()
    assert app.source_address_entry.get() == "physical-source"
    assert app.dynamic_inputs["compliance"].get() == "0.002"
    app.geometry_entry.set("out-of-plane")
    app._on_geometry_changed()
    assert app.dynamic_inputs["compliance"].get() == "0.003"


@pytest.mark.parametrize("active", [True, False])
def test_geometry_selection_blocked_during_run_or_unsafe_recovery(active):
    app, module = make_headless_moke_gui()
    app.is_measuring = active
    app.runner = Mock(can_close=Mock(return_value=False))
    app.geometry_entry.get.return_value = "out-of-plane"
    app._on_geometry_changed()
    app.geometry_entry.set.assert_called_once_with("in-plane")
    assert app._geometry_settings == {}


@pytest.mark.parametrize("key,value", [("compliance", "nan"), ("max_output_step", "0"), ("dwell_time", "-1"), ("n_cycles", "0")])
def test_profile_validation_precedes_instrument_connection(key, value):
    app, module = make_headless_moke_gui()
    app.dynamic_inputs[key].get.return_value = value
    app._connect = Mock()
    with pytest.raises(ValueError):
        app._create_experiment()
    app._connect.assert_not_called()


def test_profile_captures_geometry_and_shutdown_policy_for_actual_run():
    app, module = make_headless_moke_gui()
    app.geometry_entry.get.return_value = "out-of-plane"
    def shutdown(source):
        source.set_source_voltage(voltage=0)
        source.output(on=False)
    handler = Mock(side_effect=shutdown)
    app._shutdown_handlers["out-of-plane"] = handler
    experiment = app._create_experiment()
    app.geometry_entry.get.return_value = "in-plane"
    experiment.run_experiment(save=False)
    handler.assert_called_once()
    assert experiment.geometry == "out-of-plane"
    assert experiment.metadata.loc[0, "geometry"] == "out-of-plane"
    assert experiment.snapshot().get("geometry") == "out-of-plane"


def test_display_poll_renders_at_most_one_frame_and_handles_controls_first():
    app, module = make_headless_moke_gui()
    order = []
    app.runner = Mock()
    def no_control_events():
        order.append("control")
        raise queue.Empty
    app.runner.control_queue.get_nowait.side_effect = no_control_events
    app.runner.display_queue.get_nowait.return_value = object()
    app._plot_snapshot = lambda snapshot: order.append("display")
    app._poll_events()
    assert order == ["control", "display"]
    app.runner.display_queue.get_nowait.assert_called_once()
    app.root.after.assert_called_once()


def test_terminal_snapshot_wins_over_pending_live_frame():
    app, module = make_headless_moke_gui()
    app.run_measurement()
    assert app.runner.join(timeout=5)
    app._plot_snapshot = Mock()
    app._poll_events()
    app._plot_snapshot.assert_called_once()
    assert app._plot_snapshot.call_args.args[0].completed_steps == 5


def test_moke_gui_setup_validation_errors(monkeypatch):
    """Verify invalid setup inputs show error dialog and clean up before starting runner."""
    app, module = make_headless_moke_gui()
    mock_showerror = Mock()
    monkeypatch.setattr(module.messagebox, "showerror", mock_showerror)

    # Inverted output min/max
    app.dynamic_inputs["output_min"].get.return_value = "5.0"
    app.dynamic_inputs["output_max"].get.return_value = "-5.0"

    app.run_measurement()
    assert mock_showerror.called
    assert app.runner is None
    assert len(app._instruments) == 0

# ==============================================================================
# Part 3: FE Hysteresis & PUND GUI (FEMeasurementApp)
# ==============================================================================
FE_GUI_PATH = REPO_ROOT / "Measurements" / "Ferroelectric Testing" / "FE_testing_GUI.py"

def _load_fe_gui_module():
    spec = importlib.util.spec_from_file_location("fe_gui_module", FE_GUI_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

fe_gui_mod = _load_fe_gui_module()
FEMeasurementApp = fe_gui_mod.FEMeasurementApp
FE_DEFAULTS = fe_gui_mod.DEFAULTS


def test_fe_gui_imports_and_structure():
    """Verify FE GUI imports target components without legacy shims."""
    assert FE_GUI_PATH.is_file()

    with open(FE_GUI_PATH, "r", encoding="utf-8") as f:
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
    monkeypatch.setattr(fe_gui_mod.messagebox, "showerror", MagicMock())

    if bad_field == "vdiv":
        app.vdiv_entry.get.return_value = bad_val
    elif bad_field == "area":
        app.area_entry.get.return_value = bad_val
    elif bad_field == "time_offset":
        app.timeshift_entry.get.return_value = bad_val

    # Ensure no instrument classes are instantiated
    with patch.object(fe_gui_mod, "VirtualAwg") as mock_awg, \
         patch.object(fe_gui_mod, "VirtualScope") as mock_osc:
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
    monkeypatch.setattr(fe_gui_mod.messagebox, "showerror", MagicMock())
    app.dynamic_inputs[bad_param].get.return_value = bad_val

    with patch.object(fe_gui_mod, "VirtualAwg") as mock_awg, \
         patch.object(fe_gui_mod, "VirtualScope") as mock_osc:
        app.run_measurement()
        assert not mock_awg.called
        assert not mock_osc.called
        assert len(app._instruments) == 0
        assert app.runner is None


def test_fe_gui_rejects_mixed_or_empty_addresses(monkeypatch):
    """Verify mixed virtual/physical addresses and empty addresses are rejected pre-connection."""
    monkeypatch.setattr(fe_gui_mod.messagebox, "showerror", MagicMock())

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
    monkeypatch.setattr(fe_gui_mod.messagebox, "showerror", MagicMock())

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

# ==============================================================================
# Part 4: FE GUI State & Combobox Reviews
# ==============================================================================
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
    with patch.object(fe_gui_mod.messagebox, "showerror"), target:
        app.run_measurement()
    assert not app._busy()
    assert not app._awaiting_terminal
    assert not app._instruments
    app.measurement_type.config.assert_called_with(state="readonly")
    with patch.object(fe_gui_mod.messagebox, "showerror"):
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
    with patch.object(fe_gui_mod, "MeasurementRunner", return_value=runner), \
         patch.object(fe_gui_mod.messagebox, "showerror"):
        app.run_measurement()
    assert app._busy()
    assert app._awaiting_terminal
    assert len(app._instruments) == 2
    app.measurement_type.config.assert_called_with(state="disabled")

# ==============================================================================
# Part 5: AMR GUI (AMRMeasurementApp)
# ==============================================================================
AMR_GUI_PATH = REPO_ROOT / "Measurements" / "AMR" / "amr_GUI.py"

def _load_amr_gui_module():
    spec = importlib.util.spec_from_file_location("amr_gui_module", AMR_GUI_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


amr_gui_mod = _load_amr_gui_module()
AMRApp = amr_gui_mod.AMRApp
AMR_DEFAULTS = amr_gui_mod.DEFAULTS


def test_amr_gui_imports_and_structure():
    """Verify AMR GUI imports target components without legacy execution shims."""
    assert AMR_GUI_PATH.is_file()
    content = AMR_GUI_PATH.read_text(encoding="utf-8")

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
    assert AMR_DEFAULTS["initialize_lockin"] is False
    assert AMR_DEFAULTS["dmm_address"] == "VIRTUAL"
    assert AMR_DEFAULTS["lockin_address"] == "VIRTUAL"


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
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", MagicMock())
    app.dynamic_inputs[bad_param].get.return_value = bad_val

    with patch.object(amr_gui_mod, "VirtualDMM") as mock_dmm,          patch.object(amr_gui_mod, "VirtualCalibrator") as mock_cal,          patch.object(amr_gui_mod, "VirtualStepper") as mock_step,          patch.object(amr_gui_mod, "VirtualLockin") as mock_lock:
        app.run_measurement()
        assert not mock_dmm.called
        assert not mock_cal.called
        assert not mock_step.called
        assert not mock_lock.called
        assert len(app._instruments) == 0
        assert app.runner is None


def test_amr_gui_requires_shutdown_handler_for_physical_instruments(monkeypatch):
    """Verify physical instruments require explicit excitation_shutdown_handler and reject pre-connection."""
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", MagicMock())

    # Set lockin to physical address with NO excitation_shutdown_handler
    app = make_headless_amr_gui(excitation_shutdown_handler=None)
    app.lockin_address_entry.get.return_value = "GPIB0::8::INSTR"

    with patch.object(amr_gui_mod, "SRS830") as mock_srs:
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
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", MagicMock())

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
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", MagicMock())

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

    monkeypatch.setattr(amr_gui_mod, "VirtualDMM", MockDMM)
    monkeypatch.setattr(amr_gui_mod, "VirtualCalibrator", MockCalibrator)
    monkeypatch.setattr(amr_gui_mod, "VirtualStepper", failing_stepper)

    app.run_measurement()

    # DMM and Calibrator were created and then cleanly closed on stepper failure
    assert len(closed_instances) == 2
    assert len(app._instruments) == 0
    assert app.runner is None


def test_amr_gui_unsafe_state_blocks_refresh_autodetect_and_stepper_test(monkeypatch):
    """Regression: unsafe shutdown leaves hardware retained, blocking Run, Refresh, Autodetect, and Test Stepper."""
    app = make_headless_amr_gui()
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", MagicMock())

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
    with patch.object(amr_gui_mod, "Geos_Stepper") as mock_stepper:
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
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", mock_error)

    for entry_name in ["dmm_address_entry", "calibrator_address_entry", "stepper_address_entry", "lockin_address_entry"]:
        getattr(app, entry_name).get.return_value = "   "
        with patch.object(amr_gui_mod, "VirtualDMM") as mock_dmm:
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
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", mock_error)

    # total_angle > 0 but angle_step < 0
    app.dynamic_inputs["total_angle"].get.return_value = "180"
    app.dynamic_inputs["angle_step"].get.return_value = "-10"

    with patch.object(amr_gui_mod, "VirtualDMM") as mock_dmm:
        app.run_measurement()
        assert not mock_dmm.called
        assert mock_error.called
        assert "opposes total_angle" in mock_error.call_args[0][1]
        assert not app._busy()


def test_amr_gui_preflight_rejects_excessive_sweep_intervals(monkeypatch):
    """Preflight: sweep interval count exceeding 1,000,000 is rejected before opening drivers."""
    app = make_headless_amr_gui()
    mock_error = MagicMock()
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", mock_error)

    app.dynamic_inputs["total_angle"].get.return_value = "360"
    app.dynamic_inputs["angle_step"].get.return_value = "0.0000001"

    with patch.object(amr_gui_mod, "VirtualDMM") as mock_dmm:
        app.run_measurement()
        assert not mock_dmm.called
        assert mock_error.called
        assert "Sweep exceeds one million" in mock_error.call_args[0][1]


def test_amr_gui_preflight_rejects_simulation_shutdown_on_physical_instruments(monkeypatch):
    """Preflight: simulation shutdown handler cannot be used when any physical instrument is selected."""
    app = make_headless_amr_gui()
    mock_error = MagicMock()
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", mock_error)

    app.lockin_address_entry.get.return_value = "GPIB0::8::INSTR"
    app.excitation_shutdown_handler = app._simulation_excitation_shutdown

    with patch.object(amr_gui_mod, "SRS830") as mock_srs:
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
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", MagicMock())

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
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", MagicMock())
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
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", MagicMock())
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
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", MagicMock())

    runner = MagicMock()
    runner.can_close.return_value = False
    runner.start.side_effect = RuntimeError("error after ownership acquired")

    with patch.object(amr_gui_mod, "MeasurementRunner", return_value=runner):
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
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", MagicMock())

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
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", mock_error)

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
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", mock_error)

    with patch("piec.drivers.autodetect.autodetect", side_effect=RuntimeError("VISA bus enumeration timeout")):
        app.autodetect_instruments()

    assert mock_error.called
    assert "Autodetect failed" in str(mock_error.call_args)
    assert not app._busy()


def test_amr_gui_test_stepper_rejects_empty_address(monkeypatch):
    """Auxiliary actions: test_stepper with blank address shows error dialog and does not attempt connection."""
    app = make_headless_amr_gui()
    mock_error = MagicMock()
    monkeypatch.setattr(amr_gui_mod.messagebox, "showerror", mock_error)

    app.stepper_address_entry.get.return_value = "   "
    with patch.object(amr_gui_mod, "VirtualStepper") as mock_step:
        app.test_stepper()
        assert not mock_step.called
        assert mock_error.called
        assert "No address selected" in str(mock_error.call_args)
        assert not app._busy()
